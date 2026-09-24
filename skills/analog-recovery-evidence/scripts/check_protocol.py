"""Check declared verification boundaries and runtime evidence; no circuit-specific rules.

This checks an explicit protocol, not the truth of its declarations or analog correctness.
Use alongside check_bundle.py; historical 0.1 bundles remain readable.
"""
import argparse
import json
import math


def validate(p):
    errors=[]
    def fail(s):errors.append(s)
    def finite(x):return type(x) in (int,float) and math.isfinite(x)
    def text(x):return isinstance(x,str) and bool(x.strip())
    def strings(x):return isinstance(x,list) and all(text(v) for v in x)
    def unique(rows,key,label):
        seen=set()
        for r in rows:
            value=r.get(key)
            if not text(value):fail(label+' missing '+key)
            elif value in seen:fail(label+' duplicate '+value)
            else:seen.add(value)
    try:
        if p['version']!='0.2':fail('unsupported protocol version')
        if p['scope'] not in ('standalone','integrated'):fail('invalid boundary scope')
        if not finite(p['budget_s']) or p['budget_s']<=0:fail('invalid budget_s')
        if type(p['max_parallel']) is not int or p['max_parallel']<1:fail('invalid max_parallel')
        if not strings(p['clarification']['blocking']) or not strings(p['clarification']['assumptions']):fail('invalid clarification record')
        if not p['boundary'] or not p['measurements']:fail('boundary and measurements cannot be empty')
        unique(p['boundary'],'port','boundary');unique(p['measurements'],'id','measurement');unique(p['runs'],'id','run')
        for b in p['boundary']:
            if not all(isinstance(b[k],str) for k in ['source','compliance','role_basis']):fail('invalid boundary text fields')
            if b['state'] not in ('driven','observed','disconnected'):fail('invalid boundary state')
            if not text(b['role_basis']):fail('port role lacks evidence basis: '+b['port'])
            if b['state']=='driven' and (not text(b['source']) or not text(b['compliance'])):fail('driven port lacks source/compliance: '+b['port'])
            if b['state']=='disconnected' and b['source']:fail('disconnected port has source: '+b['port'])
        for m in p['measurements']:
            if m['quantity'] not in ('voltage','current','power','other'):fail('invalid quantity')
            if not text(m['definition']) or not text(m['domain']):fail('measurement lacks definition/domain')
            if m['quantity']=='current' and m['domain']=='mixed':fail('mixed-domain current is not total system power')
            if not strings(m['source_terms']) or not m['source_terms']:fail('measurement missing source terms')
            if not strings(m['excludes']):fail('measurement missing exclusions')
            if m['classification'] not in ('SIMULATED','DERIVED'):fail('invalid measurement classification')
            if m['classification']=='DERIVED' and not text(m['method']):fail('derived measurement lacks method')
        total=0
        for r in p['runs']:
            rid=r['id'];status=r['status'];runtime=r['runtime_s']
            if not all(strings(r[k]) for k in ['warnings','limitations','saved_signals','required_signals']):
                fail('signal/warning fields must be string arrays: '+rid);continue
            if status not in ('planned','valid','qualified','failed'):fail('invalid run status: '+rid)
            if type(r['completed']) is not bool:fail('invalid completion: '+rid)
            if r['exit_code'] is not None and type(r['exit_code']) is not int:fail('invalid exit code: '+rid)
            if status=='planned':
                if r['completed'] or runtime is not None or r['exit_code'] is not None:fail('planned run contains executed state: '+rid)
            else:
                if not finite(runtime) or runtime<0:fail('executed run lacks finite nonnegative runtime: '+rid)
                else:total+=runtime
            if r['analysis'] not in ('dc','hold','startup','other'):fail('invalid analysis: '+rid)
            if r['claim_scope'] not in ('operating_point','hold_only','startup','other'):fail('invalid claim_scope: '+rid)
            if r['analysis']=='hold' and r['claim_scope']=='startup':fail('DC initialized hold cannot prove startup: '+rid)
            if status in ('valid','qualified'):
                if not r['completed'] or r['exit_code']!=0:fail('accepted run did not successfully complete: '+rid)
                if status=='valid' and r['warnings']:fail('warnings require qualified status and interpretation: '+rid)
                if status=='qualified' and not r['limitations']:fail('qualified run lacks limitations: '+rid)
                known=set(r['saved_signals']);derived=r['derived_signals'];unique(derived,'name','derived signal')
                # Dependency closure permits chained deterministic measurements, never cycles.
                for _ in range(len(derived)+1):
                    for d in derived:
                        if text(d['method']) and d['inputs'] and set(d['inputs'])<=known:known.add(d['name'])
                missing=set(r['required_signals'])-known
                if missing:fail('missing measurement signals '+rid+': '+', '.join(sorted(missing)))
        if finite(p['budget_s']) and total>p['budget_s']:fail('cumulative executed runtime exceeds budget (failed runs included)')
        if p['clarification']['blocking'] and any(r['status'] in ('valid','qualified') for r in p['runs']):fail('blocking questions unresolved for accepted protocol')
    except (KeyError,TypeError,ValueError,AttributeError) as e:
        fail('malformed protocol: '+str(e))
    return {'valid':not errors,'errors':errors,'limits':['Declarations require independent source review; actual concurrency and physical correctness are not inferred.']}


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('protocol');a=ap.parse_args()
    try:
        with open(a.protocol,encoding='utf-8-sig') as f:p=json.load(f)
        result=validate(p)
    except (OSError,ValueError) as e:result={'valid':False,'errors':[str(e)]}
    print(json.dumps(result,ensure_ascii=False,indent=2));return 0 if result['valid'] else 1

if __name__=='__main__':raise SystemExit(main())
