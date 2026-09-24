"""Validate a fixed-circuit evidence handoff and derive condition-scoped summaries.

Standard library only. Structural validation implements exactly the schema keywords
used by the shipped schema via the frozen static tool. This is not an entailment
checker and cannot prove that a reviewer identity or a simulator status is truthful.
"""
import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent/'vendor/src'))
from analog_evidence.evidence import shape_errors

FILES=('manifest','report_requirements','design_evidence','metrics','coverage','review')
SCHEMA=Path(__file__).resolve().parents[1]/'schemas/handoff.schema.json'

def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'),parse_constant=lambda x: (_ for _ in ()).throw(ValueError('nonfinite JSON: '+x)))

def file_hash(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()

def artifact_path(root, relative):
    p=Path(relative)
    if p.is_absolute() or '..' in p.parts:raise ValueError('artifact path must stay relative to source root')
    target=root/p
    for ancestor in [target,*target.parents]:
        if ancestor==root:break
        if ancestor.is_symlink() or getattr(ancestor,'is_junction',lambda:False)():raise ValueError('linked artifact path')
    target.resolve().relative_to(root.resolve())
    return target

def validate(bundle, source_root, verify_files=True):
    schema=read(SCHEMA)
    errors=shape_errors(bundle,schema,schema)
    warnings=[];summary=[]
    if errors:return {'valid':False,'errors':errors,'warnings':warnings,'summaries':summary}
    def fail(message):errors.append(message)
    def index(rows,label):
        result={}
        for row in rows:
            if row['id'] in result:fail(f'duplicate {label}: {row["id"]}')
            result[row['id']]=row
        return result
    m=bundle['manifest'];ev=bundle['design_evidence']
    artifacts=index(m['artifacts'],'artifact');runs=index(m['runs'],'run')
    claims=index(ev['claims'],'claim');modes=index(ev['modes'],'mode')
    metrics=index(bundle['metrics']['metrics'],'metric');requirements=index(bundle['report_requirements']['requirements'],'requirement')
    if not claims or not requirements or not modes:fail('claims, requirements and modes must be nonempty')
    def refs(values,table,label):
        for value in values:
            if value not in table:fail(f'{label}: unknown reference {value}')
    for artifact in artifacts.values():
        try:
            p=artifact_path(Path(source_root),artifact['path'])
            if verify_files and file_hash(p)!=artifact['sha256']:fail('hash mismatch: '+artifact['id'])
            if verify_files and m['schema_version']=='0.2' and artifact['role']=='model_metadata':
                try:
                    metadata=read(p)
                    required={'name','device_type','pins','source_sha256','source_locator'}
                    if not isinstance(metadata,dict) or set(metadata)!={'schema_version','models'} or metadata['schema_version']!='metadata-1' or not isinstance(metadata['models'],list):
                        raise ValueError('expected extracted metadata-1')
                    for row in metadata['models']:
                        if not required<=set(row) or set(row)-required-{'section'} or not isinstance(row['pins'],list):raise ValueError('unexpected model fields')
                except (ValueError,TypeError,KeyError):fail('model metadata is not extracted metadata-1: '+artifact['id'])
        except (OSError,ValueError) as exc:fail('artifact '+artifact['id']+': '+str(exc))
        if artifact['role']=='reference' and not m['reference_assisted']:fail('reference source requires reference_assisted=true')
    review=bundle['review'];checks=index(review['checks'],'review check')
    independent=review['independent'] and review['author_id']!=review['reviewer_id']
    if not independent:warnings.append('independent review not established; partial delivery only')
    for run in runs.values():
        refs(run['artifact_refs'],artifacts,'run '+run['id'])
        refs([run['mode_ref']],modes,'run '+run['id'])
        check=checks.get(run['fixture_review_ref'])
        if run['status']=='valid' and (not check or check['result']!='pass' or run['id'] not in check['subject_refs']):fail('valid run lacks fixture review: '+run['id'])
        if run['status']!='valid' and not run['reason'].strip():fail('excluded/failed run needs reason: '+run['id'])
    # Calculation artifacts carry transitive inputs in v0.2. A null sample
    # run_ref must not erase the validity of the simulation it was computed from.
    owners={}
    for run in runs.values():
        for aid in run['artifact_refs']:owners.setdefault(aid,[]).append(run)
    lineage_cache={}
    def lineage(aid, active=()):
        if aid in active:fail('artifact lineage cycle: '+aid);return set()
        if aid in lineage_cache:return lineage_cache[aid]
        a=artifacts.get(aid)
        if not a:fail('unknown calculation input: '+aid);return set()
        result={r['id'] for r in owners.get(aid,[]) if a['role'] in ('data','run_log')}
        inputs=a.get('input_refs',[])
        if a['role']=='calculation' and not inputs:
            (fail if m['schema_version']=='0.2' else warnings.append)('calculation lacks input lineage: '+aid)
        for dep in inputs:result|=lineage(dep,active+(aid,))
        lineage_cache[aid]=result;return result
    for aid in artifacts:lineage(aid)
    for c in claims.values():
        refs(c['source_refs'],artifacts,'claim '+c['id']);refs(c['run_refs'],runs,'claim '+c['id'])
        if c['kind']!='UNKNOWN' and not c['source_refs']:fail('supported claim needs source: '+c['id'])
        if c['kind']=='UNKNOWN' and not c['uncertainty'].strip():fail('UNKNOWN needs reason: '+c['id'])
        if c['kind']=='DERIVED' and not c['method'].strip():fail('DERIVED needs calculation method: '+c['id'])
        if c['kind']=='DERIVED':
            inherited=set(c['run_refs'])
            for aid in c['source_refs']:inherited|=lineage(aid)
            if any(runs.get(r,{}).get('status')!='valid' for r in inherited):fail('DERIVED claim inherits invalid run: '+c['id'])
        if c['kind']=='INFERRED' and (not c['alternatives'] or not c['verification'] or not c['uncertainty'].strip()):fail('INFERRED needs alternatives, verification and uncertainty: '+c['id'])
        if c['kind']=='SIMULATED' and (not c['run_refs'] or any(runs.get(r,{}).get('status')!='valid' for r in c['run_refs'])):fail('SIMULATED claim needs valid runs: '+c['id'])
        if c['kind']=='DIRECT' and c['source_refs'] and all(artifacts.get(r,{}).get('role')=='reference' for r in c['source_refs']):fail('reference report alone cannot establish circuit DIRECT fact: '+c['id'])
    ports={}
    for port in ev['ports']:
        if port['name'] in ports:fail('duplicate port: '+port['name'])
        ports[port['name']]=port;refs(port['claim_refs'],claims,'port '+port['name'])
    for mode in modes.values():
        refs(mode['claim_refs'],claims,'mode '+mode['id']);seen=set()
        for d in mode['drivers']:
            refs(d['claim_refs'],claims,'driver');port=ports.get(d['port'])
            if not port:fail('driver for undeclared port: '+d['port'])
            if d['port'] in seen:fail('multiple driver records for port in mode: '+d['port'])
            seen.add(d['port'])
            if port and port['direction'] in ('output','inout','unknown') and d['behavior']=='drive' and not d['external_drive_justification'].strip():fail('unjustified forced output/inout/unknown: '+d['port'])
    for metric in metrics.values():
        mid=metric['id'];refs([metric['mode_ref']],modes,'metric '+mid);refs(metric['claim_refs'],claims,'metric '+mid)
        cases=index(metric['expected_cases'],'case '+mid);seen=set();values=[]
        if not cases and metric['status']!='not_applicable':fail('metric lacks predefined cases: '+mid)
        for s in metric['samples']:
            cid=s['case_id']
            if cid in seen:fail('duplicate metric case: '+mid+'/'+cid)
            seen.add(cid)
            if cid not in cases:fail('sample outside expected cases: '+mid+'/'+cid)
            if not math.isfinite(s['value']):fail('nonfinite sample: '+mid)
            refs([s['source_ref']],artifacts,'sample '+mid)
            if metric['kind']=='SIMULATED':
                run=runs.get(s['run_ref'])
                if not run or run['status']!='valid':fail('invalid simulation sample: '+mid)
                elif run['mode_ref']!=metric['mode_ref']:fail('sample run mode differs from metric: '+mid)
                elif s['source_ref'] not in run['artifact_refs']:fail('sample source not in run artifacts: '+mid)
            elif s['run_ref'] is not None:fail('DERIVED sample must use calculation source, not a run reference: '+mid)
            if metric['kind']=='DERIVED' and any(runs.get(r,{}).get('status')!='valid' for r in lineage(s['source_ref'])):
                fail('DERIVED sample inherits invalid run: '+mid)
            values.append(s)
        complete=bool(cases) and seen==set(cases)
        status=metric['status']
        if status=='complete' and any(claims.get(c,{}).get('kind')=='UNKNOWN' for c in metric['claim_refs']):fail('complete metric depends on UNKNOWN: '+mid)
        if status=='complete' and not complete:fail('complete metric missing cases: '+mid)
        if status=='partial' and (not seen or complete):fail('partial metric must contain a proper subset: '+mid)
        if status in ('unmeasured','not_applicable') and seen:fail('unmeasured/NA metric has samples: '+mid)
        if status!='complete' and not all(metric[k].strip() for k in ('reason','impact','next_action')):fail('incomplete metric lacks reason/impact/next_action: '+mid)
        typical=metric['typical_case_id']
        if typical is not None and typical not in cases:fail('typical case outside expected set: '+mid)
        low=min(values,key=lambda s:s['value']) if values else None;high=max(values,key=lambda s:s['value']) if values else None
        typ=next((s for s in values if s['case_id']==typical),None)
        summary.append({'id':mid,'mode':metric['mode_ref'],'unit':metric['unit'],'scope':metric['scope'],'status':status,'range_interpretation':'single_point_only' if len(values)==1 else 'observed_samples_only' if values else 'unmeasured','measured_cases':len(values),'expected_cases':len(cases),'min':low,'typ':typ,'max':high,'conditions':cases})
    seen=set()
    for item in bundle['coverage']['items']:
        rid=item['requirement_ref'];refs([rid],requirements,'coverage');refs(item['claim_refs'],claims,'coverage');refs(item['metric_refs'],metrics,'coverage')
        if rid in seen:fail('duplicate coverage: '+rid)
        seen.add(rid)
        if item['status']=='complete':
            if not item['claim_refs'] and not item['metric_refs']:fail('complete requirement lacks evidence: '+rid)
            if any(claims.get(c,{}).get('kind')=='UNKNOWN' for c in item['claim_refs']):fail('complete coverage cites UNKNOWN: '+rid)
            if any(metrics.get(c,{}).get('status')!='complete' for c in item['metric_refs']):fail('complete coverage cites incomplete metric: '+rid)
        elif not all(item[k].strip() for k in ('reason','impact','next_action')):fail('coverage gap lacks explanation: '+rid)
    for rid,r in requirements.items():
        if r['required'] and rid not in seen:fail('required requirement omitted: '+rid)
    subjects=set(claims)|set(metrics)|set(modes)|set(runs)|set(ports)|set(requirements)
    for check in checks.values():
        refs(check['subject_refs'],subjects,'review');refs(check['artifact_refs'],artifacts,'review')
    checked={ref for check in checks.values() if check['result']=='pass' for ref in check['subject_refs']}
    critical={cid for cid,c in claims.items() if c.get('critical_review_required') is True}
    declared={cid for cid,c in claims.items() if 'critical_review_required' in c}
    ambiguous=critical & (set(metrics)|set(modes)|set(runs)|set(ports)|set(requirements))
    if ambiguous:fail('ambiguous critical claim subject IDs: '+', '.join(sorted(ambiguous)))
    covered=(critical & checked)-ambiguous
    missing=critical-covered
    key_state=('no_claims' if not claims else 'ambiguous' if ambiguous else
               'undeclared' if not declared else 'declaration_incomplete' if declared!=set(claims) else
               'empty_declared' if not critical else 'covered' if not missing else
               'partial' if covered else 'unreviewed')
    key_review={'status':key_state,'claim_count':len(claims),'declared_count':len(declared),
                'required_count':len(critical),'covered_count':len(covered)}
    if key_state!='covered':warnings.append('critical claim review coverage: '+key_state)
    if missing:warnings.append('review missing for critical claims: '+', '.join(sorted(missing)))
    if set(claims)-declared:warnings.append('critical review declaration missing: '+', '.join(sorted(set(claims)-declared)))
    unreviewed=(set(modes)|set(ports)|set(metrics))-checked
    if unreviewed:warnings.append('review missing for interfaces/modes/metrics: '+', '.join(sorted(unreviewed)))
    if any(check['result']=='fail' for check in checks.values()):fail('failed review check remains in handoff')
    for f in index(review['findings'],'finding').values():
        refs(f['affected_refs'],subjects,'finding')
        if f['status']=='resolved' and not f['resolution'].strip():fail('resolved finding lacks resolution: '+f['id'])
        if f['status']=='open' and f['severity']=='blocking':fail('open blocking finding: '+f['id'])
    if 'report_map' in bundle:
        blocks=index(bundle['report_map']['blocks'],'report block')
        for b in blocks.values():
            refs(b['claim_refs'],claims,'report');refs(b['metric_refs'],metrics,'report')
            if not b['claim_refs'] and not b['metric_refs']:fail('report block lacks evidence: '+b['id'])
            transitive_claims=set(b['claim_refs'])
            for mid in b['metric_refs']:
                transitive_claims.update(metrics.get(mid,{}).get('claim_refs',[]))
            kinds={claims[c]['kind'] for c in transitive_claims if c in claims}
            if 'UNKNOWN' in kinds and b['stance']!='unknown':fail('UNKNOWN promoted into assertion: '+b['id'])
            if 'INFERRED' in kinds and b['stance']=='asserted':fail('inference needs qualified stance: '+b['id'])
    gaps=[x['requirement_ref'] for x in bundle['coverage']['items'] if x['status'] not in ('complete','not_applicable')]
    return {'valid':not errors,'delivery_status':'invalid' if errors else 'partial' if gaps or not independent or unreviewed or key_state!='covered' else 'ready_for_editorial_review','key_claim_review':key_review,'errors':errors,'warnings':warnings,'gaps':gaps,'summaries':summary,'limits':['Checks do not prove natural-language entailment, physical correctness, exhaustive PVT, reviewer independence or semantic freshness of review records.']}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('bundle',type=Path);p.add_argument('--source-root',type=Path,required=True);p.add_argument('--summary',type=Path)
    a=p.parse_args()
    try:
        bundle={name:read(a.bundle/(name+'.json')) for name in FILES}
        if (a.bundle/'report_map.json').exists():bundle['report_map']=read(a.bundle/'report_map.json')
        result=validate(bundle,a.source_root)
        if a.summary and result['valid']:
            if a.summary.exists():raise ValueError('summary output exists; choose new path')
            a.summary.parent.mkdir(parents=True,exist_ok=True);a.summary.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
        print(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False));return 0 if result['valid'] else 1
    except (OSError,ValueError,KeyError,TypeError) as exc:
        print(json.dumps({'valid':False,'errors':[str(exc)]},ensure_ascii=False));return 2

if __name__=='__main__':sys.exit(main())
