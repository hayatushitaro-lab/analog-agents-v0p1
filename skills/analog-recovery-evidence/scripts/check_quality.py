"""Offline engineering consistency checks. No simulation or natural-language entailment.

Graphs and observations must be independently extracted/reviewed; this checker
does not assert their truth merely because they are internally consistent.
"""
import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent/'vendor/src'))
from analog_evidence.evidence import shape_errors

def digest(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def check_scope():
    return {
        'edge_semantics': 'wire_alias_and_hierarchy_binding_only',
        'graph_source_fidelity': 'NOT_VERIFIED',
        'device_mediated_paths': 'NOT_EVALUATED',
        'effective_control': 'NOT_EVALUATED',
        'negative_result_means': 'No path in the submitted wire/binding graph; '
                                 'not proof of electrical isolation or ineffective control.',
    }

def validate(p, root, verify_files=True):
    errors=[]; warnings=[]; checked=[]; direct_connections=[]
    schema=json.loads((Path(__file__).resolve().parents[1]/'schemas/quality.schema.json').read_text(encoding='utf-8'))
    syntax=shape_errors(p,schema,schema)
    if syntax:return dict(valid=False,errors=syntax,warnings=[],checked=[],
                          check_scope=check_scope(),direct_connection_checks=[])
    def fail(code, obj): errors.append({'code':code,'object':str(obj)})
    def table(rows, name):
        out={}
        for r in rows:
            if not isinstance(r,dict) or not isinstance(r.get('id'),str) or not r['id']:
                fail('missing_id',name);continue
            if r['id'] in out: fail('duplicate_id',r['id'])
            out[r['id']]=r
        return out
    try:
        if p.get('schema_version')!='1': fail('schema_version','quality')
        required=('artifacts','fixtures','calculations','metrics','runs','claims','uses')
        if any(not isinstance(p.get(k),list) for k in required):
            raise ValueError('required arrays: '+','.join(required))
        artifacts=table(p['artifacts'],'artifacts');root=Path(root).resolve()
        for aid,a in artifacts.items():
            path=(root/a['path']).resolve()
            if not path.is_relative_to(root): fail('artifact_outside_root',aid);continue
            if verify_files and digest(path)!=a['sha256']: fail('artifact_changed',aid)
        def sources(item):
            refs=item.get('source_refs',[])
            if verify_files and not refs: fail('missing_sources',item['id'])
            if any(ref not in artifacts for ref in refs): fail('unknown_source',item['id'])
        for f in p['fixtures']:
            sources(f);nodes=set(f['dut_nodes']);graph={}
            for a,b in f['edges']:
                graph.setdefault(a,set()).add(b);graph.setdefault(b,set()).add(a)
            for scan in f['scans']:
                sid=scan['id'];sources(scan)
                if scan['kind']=='electrical':
                    reached=set();pending=[scan['node']]
                    while pending:
                        n=pending.pop()
                        if n not in reached: reached.add(n);pending.extend(graph.get(n,set())-reached)
                    if not reached & nodes: fail('unreachable_scan',sid)
                    if 'target_nodes' in scan:
                        targets = set(scan['target_nodes'])
                        if len(targets) != len(scan['target_nodes']) or any(not t.strip() for t in targets):
                            fail('invalid_scan_targets',sid)
                        if not targets <= nodes: fail('scan_target_not_dut',sid)
                        if not targets <= reached: fail('unreachable_scan_target',sid)
                        for target in sorted(targets):
                            direct_connections.append({'fixture_id': f['id'], 'scan_id': sid,
                                'source_node': scan['node'], 'target_node': target,
                                'in_submitted_wire_graph': 'reachable' if target in reached else 'not_reachable'})
                        if 'measurement' not in scan: fail('missing_measurement_handoff',sid)
                    else:
                        warnings.append('legacy_scan_without_target:'+sid+
                                        ': DUT contact only; intended control and measurement unverified.')
                elif scan['kind'] in ('temperature','corner','load','parameter'):
                    if not scan.get('binding'): fail('missing_environment_binding',sid)
                else: fail('unknown_scan_kind',sid)
                if 'measurement' in scan:
                    measurement = scan['measurement']
                    if measurement['node'] not in nodes: fail('measurement_node_not_dut',sid)
                    if not measurement['source_refs'] or any(r not in artifacts for r in measurement['source_refs']):
                        fail('measurement_source_missing',sid)
                    if any(not measurement[k].strip() for k in
                           ('node','unit','event','threshold','window','range')):
                        fail('blank_measurement_field',sid)
                # Identical outputs are not evidence of either disconnection or correctness.
                checked.append('scan:'+sid)
            for d in f['domains']:
                if d['low']>d['high'] or any(not math.isfinite(v) or not d['low']<=v<=d['high'] for v in d['levels']):
                    fail('domain_level',d['id'])
        for c in p['calculations']:
            sources(c)
            if c['kind']!='db_ratio': fail('unsupported_calculation',c['id']);continue
            if c['convention'] not in ('transfer','rejection'): fail('db_convention',c['id']);continue
            if c['numerator']<=0 or c['denominator']<=0: fail('db_domain',c['id']);continue
            expected=20*math.log10(c['numerator']/c['denominator'])*(1 if c['convention']=='transfer' else -1)
            if not all(math.isfinite(v) for v in (expected,c['reported'],c['tolerance'])) or c['tolerance']<0:
                fail('nonfinite_or_tolerance',c['id'])
            elif abs(expected-c['reported'])>c['tolerance']: fail('calculation_mismatch',c['id'])
            checked.append('calculation:'+c['id'])
        for m in p['metrics']:
            if set(m['case_ids'])!=set(m['displayed_case_ids']): fail('condition_scope',m['id'])
            if m['range_kind'] not in ('observed','lower_bound','upper_bound'): fail('range_kind',m['id'])
            if m['range_kind']!='observed' and m['typical_case_id'] is not None: fail('bound_not_typical',m['id'])
        runs=table(p['runs'],'runs');claims=table(p['claims'],'claims');cache={}
        def status(cid, active):
            if cid in active: fail('lineage_cycle',cid);return 2
            if cid not in claims: fail('unknown_parent',cid);return 2
            if cid in cache:return cache[cid]
            c=claims[cid];level={'supported':0,'diagnostic':1,'unknown':2}.get(c['status'])
            if level is None: fail('claim_status',cid);level=2
            for rid in c['run_refs']:
                rs=runs.get(rid,{}).get('status')
                if rs!='valid': level=max(level,1 if rs in ('qualified','partial') else 2)
            for parent in c['parents']:level=max(level,status(parent,active|{cid}))
            cache[cid]=level;return level
        for cid in claims:status(cid,set())
        for use in p['uses']:
            cid=use['claim_ref'];level=status(cid,set())
            claimed={'supported':0,'diagnostic':1,'unknown':2}.get(use['qualification'],-1)
            if claimed<level: fail('qualification_lost',cid)
            if level:
                qualifier=claims.get(cid,{}).get('qualifier','')
                # An explicit textual caveat is necessary, but never sufficient for entailment.
                if not qualifier or qualifier not in use['text']: fail('missing_local_qualifier',cid)
        if verify_files and not artifacts:fail('missing_sources','packet')
        if not p['fixtures'] and not p['calculations'] and not p['uses']:fail('empty_check_scope','packet')
        warnings.append('Bounded checks only: graph extraction, source interpretation, causal explanations and natural language still need independent review.')
    except (KeyError,TypeError,ValueError,OSError,OverflowError) as exc:
        fail('malformed_or_missing_input',str(exc))
    return dict(valid=not errors,errors=errors,warnings=warnings,checked=checked,
                check_scope=check_scope(),direct_connection_checks=direct_connections)

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('packet',type=Path)
    ap.add_argument('--source-root',required=True,type=Path);ap.add_argument('--out',type=Path);a=ap.parse_args()
    result=validate(json.loads(a.packet.read_text(encoding='utf-8-sig')),a.source_root)
    raw=json.dumps(result,ensure_ascii=False,indent=2)
    if a.out:
        with a.out.open('x',encoding='utf-8') as f:f.write(raw+'\n')
    else:print(raw)
    return 0 if result['valid'] else 1
if __name__=='__main__':raise SystemExit(main())
