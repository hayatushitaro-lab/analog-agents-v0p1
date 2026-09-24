"""Design-only expansion and conservative structural correspondence."""
from collections import defaultdict
from .numeric import scalar, decimal_text, NumericError


def elaborate(view, top, max_occurrences=100000, max_depth=64):
    defs={d['canonical_name']:d for d in view['definitions']}
    insts={i['id']:i for i in view['instances']};occ=[];diags=[];aid=view['artifact_ref']
    def fail(code,reason,refs,scope,severity='error'):
        diags.append({'id':f'{aid}:elabdiag:{len(diags)}','code':code,'severity':severity,'stage':'elaboration',
                      'source_span_refs':refs,'affected_scope_refs':[scope],'reason':reason,'recovery_action':'Resolve hierarchy; no automatic pin or parameter repair.'})
    if top not in defs:
        fail('UNRESOLVED_SUBCKT','requested root is absent',[],aid);return occ,diags
    root=defs[top]
    def values(params, environment):
        raw={p['canonical_key']:p['raw_expr'] for p in params};env={**environment,**raw};out={}
        for k,x in raw.items():
            try:out[k]=decimal_text(scalar(x,view['dialect'],env))
            except NumericError:out[k]=None
        return out
    global_env={p['canonical_key']:p['raw_expr'] for p in view.get('global_parameters',[])}
    def visit(definition,path,parent,bindings,overrides,stack,instance=None):
        if len(occ)>=max_occurrences or len(stack)>max_depth:
            fail('EXPANSION_LIMIT','occurrence/depth budget exceeded',definition['span_refs'],definition['id']);return
        if definition['id'] in stack:
            fail('HIERARCHY_CYCLE','recursive subckt call',definition['span_refs'],definition['id']);return
        env={**global_env,**{p['canonical_key']:p['raw_expr'] for p in definition['parameters']},**overrides}
        oid=aid+':occ:'+path
        entry={'id':oid,'root_ref':root['id'],'instance_path':path,'definition_ref':definition['id'],
               'instance_ref':instance['id'] if instance else None,'parent_ref':parent,
               'port_bindings':bindings,'terminal_bindings':[],
               'parameter_environment':values(definition['parameters'],env), 'status':definition['status'],
               'role':'dut' if parent is None else 'design_subckt','support_refs':list(definition['span_refs'])+(instance['span_refs'] if instance else [])}
        # Override values take precedence over definition defaults.
        for key in overrides:
            try:entry['parameter_environment'][key]=decimal_text(scalar(overrides[key],view['dialect'],env))
            except NumericError:entry['parameter_environment'][key]=None
        occ.append(entry)
        by_port={b['formal_name']:b['resolved_net'] for b in bindings}
        def resolve(t):
            name=t['canonical_name']
            if name in view['globals']:return aid+':global:'+name
            return by_port.get(name,oid+':net:'+name)
        for iid in definition['instance_refs']:
            i=insts[iid];ipath=path+'/'+i['raw_name'];terms=i['ordered_terminals']
            tb=[{'ordinal':t['ordinal'],'actual_name':t['canonical_name'],'source_net_ref':t['net_ref'],'resolved_net':resolve(t)} for t in terms]
            child=defs.get(i['master_ref_or_name'])
            if child:
                if len(terms)!=len(child['formal_ports']):
                    fail('ARITY_MISMATCH','actual/formal terminal counts differ',i['span_refs'],definition['id']);entry['status']='blocked';continue
                child_bind=[{**b,'formal_name':p['canonical_name'],'formal_net_ref':p['net_ref']} for p,b in zip(child['formal_ports'],tb)]
                child_overrides={}
                for p in i['parameters']:
                    try:child_overrides[p['canonical_key']]=decimal_text(scalar(p['raw_expr'],view['dialect'],env))
                    except NumericError:child_overrides[p['canonical_key']]='__unresolved_override__'
                visit(child,ipath,oid,child_bind,child_overrides,stack+[definition['id']],i)
            else:
                status='opaque_model'
                if i['is_subckt_call']:
                    fail('UNRESOLVED_SUBCKT','subckt call has no admitted definition',i['span_refs'],definition['id']);status='blocked'
                evaluated=values(i['parameters'],env)
                for key,value in evaluated.items():
                    if value is None:fail('PARAMETER_EXPRESSION_UNRESOLVED','unresolved occurrence parameter: '+key,i['span_refs'],i['id'],'warning')
                occ.append({'id':aid+':occ:'+ipath,'root_ref':root['id'],'instance_path':ipath,'definition_ref':None,
                            'instance_ref':i['id'],'parent_ref':oid,'port_bindings':[],'terminal_bindings':tb,
                            'parameter_environment':evaluated,'status':status,'role':'device_master',
                            'support_refs':i['span_refs']})
                if len(occ)>=max_occurrences:
                    fail('EXPANSION_LIMIT','occurrence budget exceeded',i['span_refs'],definition['id']);return
    initial=[{'ordinal':p['ordinal'],'formal_name':p['canonical_name'],'formal_net_ref':p['net_ref'],
              'actual_name':p['canonical_name'],'source_net_ref':p['net_ref'],
              'resolved_net':aid+':global:'+p['canonical_name'] if p['canonical_name'] in view['globals'] else aid+':occ:/'+top+':port:'+p['canonical_name']} for p in root['formal_ports']]
    visit(root,'/'+top,None,initial,{},[])
    for i in view['instances']:
        if i['definition_scope_ref']!=aid+':harness' or i['master_ref_or_name']!=top:continue
        bindings=[];status='binding_available'
        if len(i['ordered_terminals'])!=len(root['formal_ports']):
            fail('ARITY_MISMATCH','harness arity mismatch',i['span_refs'],i['id']);status='blocked'
        else:
            bindings=[{'ordinal':p['ordinal'],'formal_name':p['canonical_name'],'formal_net_ref':p['net_ref'],
                       'actual_name':t['canonical_name'],'source_net_ref':t['net_ref'],'resolved_net':t['net_ref']}
                      for p,t in zip(root['formal_ports'],i['ordered_terminals'])]
        occ.append({'id':aid+':harness_occ:'+i['raw_name'],'root_ref':root['id'],'instance_path':'/@harness/'+i['raw_name'],
                    'definition_ref':root['id'],'instance_ref':i['id'],'parent_ref':None,'port_bindings':bindings,'terminal_bindings':[],
                    'parameter_environment':{},'status':status,'role':'export_harness','support_refs':i['span_refs']+root['span_refs']})
    return occ,diags


def compare(left,right):
    result=[];ld={d['canonical_name']:d for d in left['definitions']};rd={d['canonical_name']:d for d in right['definitions']}
    def add(l,r,scope,status,basis,diffs):
        result.append({'id':f'comparison:{left["artifact_ref"]}:{right["artifact_ref"]}:{len(result)}',
                       'left_refs':[l['id']] if l else [],'right_refs':[r['id']] if r else [],'status':status,
                       'comparison_scope':scope,'match_basis':basis,'differences':diffs,
                       'uncertainty':['Local labelled connectivity comparison; no electrical equivalence or physical parameter conversion.'],
                       'support_refs':(l['span_refs'] if l else [])+(r['span_refs'] if r else [])})
    for name in sorted(set(ld)|set(rd)):
        l=ld.get(name);r=rd.get(name)
        if not l or not r:add(l,r,'definition','unmatched','definition name',[]);continue
        lp=[p['canonical_name'] for p in l['formal_ports']];rp=[p['canonical_name'] for p in r['formal_ports']]
        add(l,r,'formal_ports','confirmed_local_match' if lp==rp else 'representation_difference','ordered canonical formal names',[] if lp==rp else [{'left':lp,'right':rp}])
        if lp!=rp:continue
        li=[i for i in left['instances'] if i['definition_scope_ref']==l['id']]
        ri=[i for i in right['instances'] if i['definition_scope_ref']==r['id']]
        def key(i):return i['master_ref_or_name'],tuple(t['canonical_name'] for t in i['ordered_terminals'])
        lm=defaultdict(list);rm=defaultdict(list)
        for i in li:lm[key(i)].append(i)
        for i in ri:rm[key(i)].append(i)
        for k in sorted(set(lm)|set(rm)):
            a=lm[k];b=rm[k]
            if len(a)!=1 or len(b)!=1:
                for i in a:add(i,None,'instance_parameters','unmatched','ambiguous or absent master+ordered-net signature',[])
                for i in b:add(None,i,'instance_parameters','unmatched','ambiguous or absent master+ordered-net signature',[])
                continue
            a=a[0];b=b[0];ap={p['canonical_key']:p for p in a['parameters']};bp={p['canonical_key']:p for p in b['parameters']};diffs=[]
            for p in sorted(set(ap)|set(bp)):
                av=ap.get(p);bv=bp.get(p)
                if av is None or bv is None or av['raw_expr']!=bv['raw_expr']:
                    same_scalar=bool(av and bv and av['normalized_value'] and bv['normalized_value'] and av['normalized_value']['decimal_string']==bv['normalized_value']['decimal_string'])
                    diffs.append({'parameter':p,'left':av['raw_expr'] if av else None,'right':bv['raw_expr'] if bv else None,
                                  'classification':'lexical_representation' if same_scalar else 'missing_or_different_scalar','physical_equivalence':'unknown'})
            add(a,b,'instance_parameters','representation_difference' if diffs else 'confirmed_local_match','unique same-master and ordered canonical net names within matched definition',diffs)
    return result
