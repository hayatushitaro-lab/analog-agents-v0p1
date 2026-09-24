"""Command-line static pipeline. No external commands, discovery, or network calls."""
import argparse
import hashlib
import json
import sys
import time
from collections import Counter
from pathlib import Path
from .admission import Admission, AdmissionError, no_links
from .parser import parse, diagnostic
from .metadata import scan_metadata, section_closure
from .evidence import build_snapshot, validate, SCHEMA_PATH, digest
from .acceptance import acceptance


def code_identity():
    h=hashlib.sha256()
    for p in sorted(Path(__file__).parent.glob('*.py')):
        h.update(p.name.encode());h.update(p.read_bytes())
    return h.hexdigest()


def read_manifest(path):
    path=no_links(Path(path).absolute());raw=path.read_bytes();m=json.loads(raw)
    if m.get('simulation_policy')!='disabled' or m.get('model_policy')!='metadata_only':
        raise AdmissionError('only static/metadata-only manifests supported')
    by_id={e['id']:e for e in m['inputs']}
    design_ids=[m['structural_baseline']]+m.get('comparison_artifacts',[])
    if len(by_id)!=len(m['inputs']) or len(set(design_ids))!=len(design_ids):
        raise AdmissionError('duplicate input or design view id')
    if by_id[m['structural_baseline']].get('dialect')!='spectre':
        raise AdmissionError('primary structural source must be Spectre/SCS')
    if m.get('source_policy','primary_required_auxiliary_optional')!='primary_required_auxiliary_optional':
        raise AdmissionError('unsupported source policy')
    for e in m['inputs']:
        if e['role'] not in ('design','model_metadata'):raise AdmissionError('unsupported input role')
        e['source_attestation']=m.get('source_attestation',{'provider':'unspecified'}) if e['role']=='design' else {'provider':'user_path','package_origin':'unverified','remote_identity':'unverified'}
    return m,hashlib.sha256(raw).hexdigest()


def run(manifest_path,root,output):
    started=time.perf_counter();m,mhash=read_manifest(manifest_path)
    root=no_links(Path(root).absolute());output=no_links(Path(output).absolute())
    try:output.relative_to(root)
    except ValueError:raise AdmissionError('output outside workspace')
    gate=Admission(root,m['inputs'],m.get('path_maps',[]));sources={};views=[]
    by_id={e['id']:e for e in m['inputs']}
    design_ids=[m['structural_baseline']]+m.get('comparison_artifacts',[])
    for aid in design_ids:
        if by_id[aid]['role']!='design':raise AdmissionError('design id refers to non-design input')
        data=gate.read(aid);sources[aid]=data;views.append(parse(data,aid,by_id[aid]['dialect']))
    needed={i['master_ref_or_name'] for v in views for i in v['instances'] if not i['is_subckt_call']}
    metadata={}
    for e in m['inputs']:
        if e['role']=='model_metadata':
            data=gate.read(e['id']);sources[e['id']]=data;metadata[e['id']]=scan_metadata(data,e['id'],needed)
    closure=[]
    for v in views:
        for dep in v['dependencies']:
            target=gate.resolve(v['artifact_ref'],dep['requested_path']);dep['local_candidate_ref']=target
            dep['resolution_state']='local_candidate_metadata_unverified' if target else 'not_admitted'
            if target:
                c=section_closure(metadata,target,dep['requested_section'],gate.resolve);c['dependency_ref']=dep['id'];closure.append(c)
                if c['cycles']:diagnostic(v,'SECTION_CYCLE','section-aware dependency cycle detected',dep['span_refs'],v['artifact_ref'],stage='model_metadata')
                if c['unresolved']:diagnostic(v,'MODEL_METADATA_PARTIAL','lexical include closure has unresolved edges',dep['span_refs'],v['artifact_ref'],'warning','model_metadata')
            else:diagnostic(v,'INCLUDE_NOT_ADMITTED','include target is outside exact read allowlist',dep['span_refs'],v['artifact_ref'],'warning','admission')
        if v['dependencies'] and any('insensitive=' in s['declaration'] for md in metadata.values() for s in md['settings']):
            diagnostic(v,'NAME_POLICY_UNRESOLVED','Included model declares insensitive setting; propagation into design context remains unverified.',v['dependencies'][0]['span_refs'],v['artifact_ref'],'warning','model_metadata')
    identity={'code_sha256':code_identity(),'schema_sha256':hashlib.sha256(SCHEMA_PATH.read_bytes()).hexdigest(),'manifest_sha256':mhash}
    ir=build_snapshot(views,m['dut_definition'],m['project_id'],m['inputs'],sources,identity,list(metadata.values()))
    validation=validate(ir,sources)
    verdict=acceptance(ir,validation)
    summary={'project_id':m['project_id'],'snapshot_id':ir['snapshot_id'],'tool_identity':identity,
             'schema_validation_errors':len(validation),'stage_status':ir['scope']['stages'],
             'acceptance':verdict,'source_statuses':ir['scope']['source_statuses'],
             'comparison_coverage':ir['scope']['comparison_coverage'],
             'claims_by_kind':dict(Counter(c['kind'] for c in ir['claims'])),
             'definitions':[{'id':d['id'],'ports':len(d['formal_ports']),'direct_instances':len(d['instance_refs'])} for d in ir['definitions']],
             'occurrences_by_role':dict(Counter(o['role'] for o in ir['occurrences'])),
             'comparisons_by_status':dict(Counter(c['status'] for c in ir['comparisons'])),
             'diagnostics_by_code':dict(Counter(d['code'] for d in ir['diagnostics'])),
             'model_metadata':{aid:{'sections':len(md['sections']),'requested_master_declarations':len(md['declarations'])} for aid,md in metadata.items()},
             'simulation_executed':False,'elapsed_seconds':round(time.perf_counter()-started,3),
             'limitations':['No physical model execution or electrical equivalence proof.','Case-setting propagation unresolved.','No OS sandbox; allowlist enforced by this reader.','Only the documented static dialect subset is supported.']}
    outdir=output/'snapshots'/ir['snapshot_id'];no_links(outdir);outdir.mkdir(parents=True,exist_ok=True)
    def write(name,value,immutable=False):
        path=outdir/name;no_links(path);content=(json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode()
        if path.exists() and immutable:
            if path.read_bytes()!=content:raise AdmissionError('immutable snapshot collision')
            return
        path.write_bytes(content)
    write('design_evidence.json',ir,True)
    write('model_metadata.json',{'indexes':metadata,'selected_lexical_closures':closure},True)
    write('validation.json',{'valid':not validation,'errors':validation},True)
    write('acceptance.json',verdict,True)
    write('comparisons.json',ir['comparisons'],True)
    if not (outdir/'summary.json').exists():write('summary.json',summary)
    # Recheck admitted bytes after work; never modify an input.
    for aid in sources:gate.read(aid)
    if not (outdir/'access_audit.json').exists():write('access_audit.json',gate.audit)
    executions=output/'executions';no_links(executions);executions.mkdir(exist_ok=True)
    execution_path=executions/(str(time.time_ns())+'.json')
    execution_path.write_text(json.dumps({'summary':summary,'access_audit':gate.audit},ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    latest=output/'latest.json';no_links(latest)
    latest.write_text(json.dumps({'snapshot_id':ir['snapshot_id'],'path':str(outdir.relative_to(output)).replace('\\','/'),
                                 'structurally_valid':not validation,'accepted':verdict['accepted'],
                                 'acceptance_status':verdict['status']},indent=2)+'\n',encoding='utf8')
    print(json.dumps(summary,ensure_ascii=False,indent=2))
    if validation:print(json.dumps(validation[:20],ensure_ascii=False,indent=2),file=sys.stderr)
    return 0 if verdict['accepted'] else 1


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
    r=sub.add_parser('run');r.add_argument('--manifest',required=True);r.add_argument('--root',default='.');r.add_argument('--output',required=True)
    v=sub.add_parser('validate');v.add_argument('--manifest',required=True);v.add_argument('--root',default='.');v.add_argument('--evidence',required=True)
    a=p.parse_args(argv)
    try:
        if a.command=='run':return run(a.manifest,a.root,a.output)
        m,mhash=read_manifest(a.manifest);gate=Admission(a.root,m['inputs'],m.get('path_maps',[]))
        evidence_path=no_links(Path(a.evidence).absolute());ir=json.loads(evidence_path.read_text(encoding='utf8'))
        sources={e['id']:gate.read(e['id']) for e in m['inputs']};errors=validate(ir,sources)
        if ir.get('created_by',{}).get('manifest_sha256')!=mhash:errors.append('manifest identity mismatch')
        if ir.get('scope',{}).get('structural_baseline_ref')!=m['structural_baseline']:errors.append('primary source differs from manifest')
        verdict=acceptance(ir,errors) if not errors else {'status':'invalid_evidence','accepted':False}
        print(json.dumps({'structurally_valid':not errors,'errors':errors,'acceptance':verdict},ensure_ascii=False,indent=2))
        return 0 if verdict['accepted'] else 1
    except (ValueError,OSError,KeyError) as exc:
        print(type(exc).__name__+': '+str(exc),file=sys.stderr);return 2


if __name__=='__main__':sys.exit(main())
