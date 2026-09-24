"""Evidence creation plus structural, reference and selected entailment checks."""
import copy
import hashlib
import json
import re
import sys
from pathlib import Path
from .graph import elaborate, compare
from .numeric import scalar, decimal_text, NumericError
from .acceptance import policy_fields


VERSION='0.2.0'
SCHEMA_PATH=Path(__file__).resolve().parents[2]/'schemas'/'design_evidence.schema.json'
if not SCHEMA_PATH.exists():
    SCHEMA_PATH=Path(sys.prefix)/'share'/'analog-evidence'/'schemas'/'design_evidence.schema.json'


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()


def shape_errors(value,rule,root,path='$'):
    """Validate exactly the keywords used by the checked-in schema (not a general JSON Schema engine)."""
    errors=[]
    if '$ref' in rule:
        target=root
        for part in rule['$ref'][2:].split('/'):target=target[part]
        errors.extend(shape_errors(value,target,root,path))
    types={'object':lambda x:isinstance(x,dict),'array':lambda x:isinstance(x,list),'string':lambda x:isinstance(x,str),
           'integer':lambda x:type(x) is int,'number':lambda x:type(x) in (int,float),'boolean':lambda x:type(x) is bool,'null':lambda x:x is None}
    wanted=rule.get('type')
    if wanted and not any(types[t](value) for t in ([wanted] if isinstance(wanted,str) else wanted)):
        return errors+[path+': wrong type']
    if 'enum' in rule and not any(value==option and (type(value) is bool)==(type(option) is bool) for option in rule['enum']):errors.append(path+': enum')
    if isinstance(value,str):
        if len(value)<rule.get('minLength',0):errors.append(path+': too short')
        if 'pattern' in rule and not re.search(rule['pattern'],value):errors.append(path+': pattern')
    if type(value) in (int,float) and value<rule.get('minimum',value):errors.append(path+': minimum')
    if isinstance(value,list):
        if len(value)<rule.get('minItems',0):errors.append(path+': too few items')
        for i,v in enumerate(value):errors.extend(shape_errors(v,rule.get('items',{}),root,f'{path}[{i}]'))
    if isinstance(value,dict):
        for key in rule.get('required',[]):
            if key not in value:errors.append(path+': missing '+key)
        props=rule.get('properties',{})
        if rule.get('additionalProperties') is False:
            errors.extend(path+': unexpected '+key for key in value if key not in props)
        for key,v in value.items():
            if key in props:errors.extend(shape_errors(v,props[key],root,path+'.'+key))
    return errors


def build_snapshot(views,top,project_id,artifact_entries,sources,identity,metadata=()):
    views=copy.deepcopy(views);entries={e['id']:e for e in artifact_entries}
    ir={'schema_version':VERSION,'snapshot_id':'pending','parent_snapshot_id':None,'project_id':project_id,'stage':'static_inspection',
        'created_by':{'tool':'analog-evidence-static','version':VERSION,'code_sha256':identity.get('code_sha256','unknown'),
                      'schema_sha256':identity.get('schema_sha256','unknown'),'manifest_sha256':identity.get('manifest_sha256','unknown')},
        'scope':{},'artifacts':[],'source_spans':[],'definitions':[],'instances':[],'occurrences':[],'nets':[],'dependencies':[],
        'claims':[],'records':[],'conditions':[],'requirements':[],'gaps':[],'diagnostics':[],'views':[],'comparisons':[]}
    for aid,data in sources.items():
        e=entries.get(aid,{})
        ir['artifacts'].append({'id':aid,'role':e.get('role','design'),'uri':e.get('path',f'synthetic/{aid}'),
            'sha256':hashlib.sha256(data).hexdigest(),'byte_size':len(data),'source_attestation':e.get('source_attestation',{'provider':'synthetic_fixture'}),
            'admission':'hash_verified' if e else 'synthetic','access_scope':e.get('access_scope','design')})
    for v in views:
        occ,diag=elaborate(v,top)
        for key in ('source_spans','definitions','instances','nets','dependencies','conditions','diagnostics'):ir[key].extend(v[key])
        ir['occurrences'].extend(occ);ir['diagnostics'].extend(diag)
        ir['views'].append({k:v[k] for k in ('artifact_ref','dialect','statements','dialect_contexts','status','line_count','globals')})
    for m in metadata:ir['source_spans'].extend(m['source_spans'])
    baseline=views[0]['artifact_ref'];root=next((d['id'] for d in ir['definitions'] if d['artifact_ref']==baseline and d['canonical_name']==top),None)
    ir['scope']={'dut_definition_ref':root,'structural_baseline_ref':baseline,'comparison_refs':[v['artifact_ref'] for v in views[1:]],
                 'harness_refs':[o['id'] for o in ir['occurrences'] if o['role']=='export_harness'],
                 'model_resolution_status':'metadata_partial','implementation_stage':'unknown',
                 'stages':{'syntax':'partial' if any(v['status']!='complete' for v in views) else 'complete',
                           'design_elaboration':'partial' if any(d['severity']=='error' for d in ir['diagnostics']) else 'complete',
                           'model_binding':'partial','simulation':'not_run','report':'not_run'}}
    def claim(subject,predicate,value,kind,support,uncertainty=(),status=None):
        c={'id':f'claim:{len(ir["claims"])}','subject_ref':subject,'predicate':predicate,'value':value,'kind':kind,
           'status':status or ('blocked' if kind=='UNKNOWN' else 'supported'),'support_refs':list(support),'condition_ref':None,'assumption_refs':[],
           'uncertainty':list(uncertainty),'confidence':{'level':'low' if kind=='UNKNOWN' else 'high','basis':'static source/algorithm' if kind!='UNKNOWN' else 'insufficient evidence','calibrated':False},'ancestry_kinds':[]}
        ir['claims'].append(c);return c
    def derived(subject,predicate,value,inputs,method,rtype='calculation'):
        rid=f'record:{len(ir["records"])}';c=claim(subject,predicate,value,'DERIVED',[rid],['Scalar or structural calculation only; physical meaning not established.'])
        ir['records'].append({'id':rid,'type':rtype,'inputs':inputs,'outputs':[c['id']],'method_ref':method,'version':VERSION,'support_refs':[]})
        return c,rid
    def unknown(subject,predicate,reason,stage='physical_verification'):
        c=claim(subject,predicate,None,'UNKNOWN',[],[reason])
        ir['gaps'].append({'id':f'gap:{len(ir["gaps"])}','category':predicate,'reason':reason,'affected_refs':[subject,c['id']],
                           'blocking_stage':stage,'next_evidence':'Admitted interface/fixture/specification or validated analysis evidence.'})
    literal_claims={};formal_claims={};connection_claims={}
    dialect_by_aid={v['artifact_ref']:v['dialect'] for v in views}
    def params(subject,ps,aid):
        for p in ps:
            c=claim(subject,'declared_parameter.'+p['canonical_key'],{'type':'expression','text':p['raw_expr']},'DIRECT',p['raw_span_refs'])
            literal_claims[(subject,p['canonical_key'])]=c['id']
            if p['normalized_value'] is not None:
                nc,rid=derived(subject,'normalized_scalar.'+p['canonical_key'],{'type':'quantity',**p['normalized_value']},[c['id']],f'literal_decimal:{dialect_by_aid[aid]}','normalization')
                p['normalization_record_ref']=rid
    for d in ir['definitions']:
        c=claim(d['id'],'declared_formal_ports',{'type':'ordered_list','items':[p['raw_name'] for p in d['formal_ports']]},'DIRECT',[d['span_refs'][0]])
        formal_claims[d['id']]=c['id'];params(d['id'],d['parameters'],d['artifact_ref'])
        for p in d['formal_ports']:
            if p['declared_direction']:
                claim(d['id'],'declared_port_direction.'+p['canonical_name'],{'type':'enum','text':p['declared_direction']},'DIRECT',p['direction_span_refs'],['Export annotation; not verified electrical behavior.'])
    for i in ir['instances']:
        c=claim(i['id'],'declared_connections',{'type':'ordered_list','items':[t['raw_name'] for t in i['ordered_terminals']]},'DIRECT',i['span_refs'])
        connection_claims[i['id']]=c['id']
        claim(i['id'],'declared_master',{'type':'string','text':i['master_ref_or_name']},'DIRECT',i['span_refs'])
        params(i['id'],i['parameters'],i['artifact_ref'])
        declarations=[d for m in metadata for d in m['declarations'] if d['name']==i['master_ref_or_name']]
        i['model_declaration_refs']=[s for d in declarations for s in d['span_refs']]
        if declarations and not i['is_subckt_call']:
            i['resolution_status']='declaration_found_binding_unverified'
        if not i['is_subckt_call']:unknown(i['id'],'physical_parameter_semantics','Raw geometry/multipliers preserved; no effective W/R/C interpretation.')
    for d in ir['definitions']:
        inputs=[formal_claims[d['id']]]+[connection_claims[x] for x in d['instance_refs']]
        derived(d['id'],'direct_instance_count',{'type':'quantity','decimal_string':str(len(d['instance_refs'])),'unit':'1','dimension':'count'},inputs,'count_definition_instances')
    for o in ir['occurrences']:
        if o['port_bindings']:
            inputs=[formal_claims[o['definition_ref']]]
            if o['instance_ref']:inputs.append(connection_claims[o['instance_ref']])
            derived(o['id'],'positional_port_bindings',{'type':'ordered_list','items':o['port_bindings']},inputs,'bind_ports_by_ordinal')
    for c in ir['conditions']:
        # Parsed settings are not validated operating conditions.
        aid=c['id'].split(':',1)[0];params(c['id'],c['entries'],aid)
    for dep in ir['dependencies']:
        claim(dep['id'],'declared_include',{'type':'string','text':dep['requested_path'],'section':dep['requested_section']},'DIRECT',dep['span_refs'])
    for m in metadata:
        for d in m['declarations']:
            claim(m['artifact_ref'],'model_declaration',{'type':'string','text':d['name'],'section':d['section'],'formal_ports':d['formal_ports']},'DIRECT',d['span_refs'],['Declaration found; active branch and runtime binding unverified.'])
    if root:
        for pred,reason in [('original_specification','No original specification admitted; no product pass/fail.'),
                            ('valid_fixture','No valid testbench admitted; harness and options are not verification.'),
                            ('operating_point','No simulator execution or output.'),
                            ('control_polarity','Port names/annotations do not prove active levels.'),
                            ('operating_limits','Supply, bias, load and allowed ranges not established.'),
                            ('model_active_binding','Selected section declarations do not establish full model semantics.')]:unknown(root,pred,reason)
    for v in views[1:]:ir['comparisons'].extend(compare(views[0],v))
    # Conservatively retain every diagnostic as an explicit scope gap.
    for d in ir['diagnostics']:
        ir['gaps'].append({'id':f'gap:{len(ir["gaps"])}','category':d['code'],'reason':d['reason'],
                           'affected_refs':d['affected_scope_refs'],'blocking_stage':d['stage'],'next_evidence':d['recovery_action']})
    ir['scope'].update(policy_fields(ir))
    fill_ancestry(ir)
    ir['snapshot_id']=digest(ir)
    return ir


def fill_ancestry(ir):
    claims={c['id']:c for c in ir['claims']};records={r['id']:r for r in ir['records']};memo={}
    def visit(ref,stack=()):
        if ref in stack:return set()
        if ref in memo:return memo[ref]
        c=claims.get(ref);r=records.get(ref)
        kinds={c['kind']} if c else set()
        refs=(c['support_refs']+c['assumption_refs']) if c else (r['inputs']+r['support_refs']) if r else []
        for x in refs:kinds|=visit(x,stack+(ref,))
        memo[ref]=kinds;return kinds
    for c in ir['claims']:
        kinds=set()
        for ref in c['support_refs']+c['assumption_refs']:kinds|=visit(ref)
        c['ancestry_kinds']=sorted(kinds)


def validate(ir,sources, schema_path=SCHEMA_PATH):
    try:
        return _validate(ir,sources,schema_path)
    except (KeyError,TypeError,ValueError,IndexError,RecursionError) as exc:
        return ['Malformed evidence rejected: '+type(exc).__name__+': '+str(exc)]


def _validate(ir,sources, schema_path):
    schema=json.loads(Path(schema_path).read_text(encoding='utf8'))
    errors=shape_errors(ir,schema,schema)
    if errors:return errors
    unhashed=copy.deepcopy(ir);unhashed['snapshot_id']='pending'
    if ir['snapshot_id']!=digest(unhashed):errors.append('snapshot content identity mismatch')
    collections=('artifacts','source_spans','definitions','instances','occurrences','nets','dependencies','claims','records','conditions','requirements','gaps','diagnostics','comparisons')
    registry={};duplicates=[]
    for key in collections:
        for obj in ir[key]:
            if obj['id'] in registry:duplicates.append(obj['id'])
            registry[obj['id']]=obj
    errors+=['duplicate id: '+x for x in duplicates]
    allowed=set(registry)
    for a in ir['artifacts']:allowed.update((a['id']+':harness',a['id']+':global'))
    for v in ir['views']:
        allowed.update(c['id'] for c in v['dialect_contexts'])
    def refs(obj,path='$'):
        if isinstance(obj,dict):
            for key,value in obj.items():
                if key.endswith('_ref') and isinstance(value,str) and key not in ('method_ref','semantic_contract_ref'):
                    if value not in allowed:errors.append(path+'.'+key+': dangling '+value)
                elif key.endswith('_refs') and isinstance(value,list):
                    for r in value:
                        if isinstance(r,str) and r not in allowed:errors.append(path+'.'+key+': dangling '+r)
                refs(value,path+'.'+key)
        elif isinstance(obj,list):
            for i,v in enumerate(obj):refs(v,f'{path}[{i}]')
    for key in collections:refs(ir[key],key)
    refs(ir['scope'],'scope')
    for a in ir['artifacts']:
        data=sources.get(a['id'])
        if data is None:errors.append('source unavailable: '+a['id']);continue
        if hashlib.sha256(data).hexdigest()!=a['sha256'] or len(data)!=a['byte_size']:errors.append('artifact identity mismatch: '+a['id'])
    spans={s['id']:s for s in ir['source_spans']};span_text={}
    for sid,s in spans.items():
        data=sources.get(s['artifact_ref'],b'');pieces=[]
        for f in s['fragments']:
            lo,hi=f['byte_start'],f['byte_end']
            if not 0<=lo<hi<=len(data):errors.append('span bounds: '+sid);continue
            if data[:lo].count(b'\n')+1!=f['line']:errors.append('span line mismatch: '+sid)
            pieces.append(data[lo:hi].decode('utf8'))
        span_text[sid]=''.join(pieces)
    for v in ir['views']:
        fragments=sorted((f for s in spans.values() if s['artifact_ref']==v['artifact_ref'] for f in s['fragments']),key=lambda f:f['byte_start'])
        cursor=0
        for f in fragments:
            if f['byte_start']!=cursor:errors.append('source ledger gap/overlap: '+v['artifact_ref']);break
            cursor=f['byte_end']
        if cursor!=len(sources.get(v['artifact_ref'],b'')):errors.append('source ledger incomplete: '+v['artifact_ref'])
        for row in v['statements']:
            if row['raw']!=span_text.get(row['span_ref']):errors.append('statement raw/source mismatch: '+row['id'])
    # Independent source checks use raw span text, not the producer's parsed fields.
    # This intentionally duplicates a small supported lexical subset for auditing.
    def logical(ref_list):
        raw=''.join(span_text.get(s,'') for s in ref_list)
        aid=registry.get(ref_list[0],{}).get('artifact_ref') if ref_list else None
        if dialect_by_aid.get(aid)=='spectre':
            # Independent source audit: preserve quoted/escaped text, discard only comments.
            raw=re.sub(r'''"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|\\.|//[^\r\n]*''',
                       lambda m: '' if m[0].startswith('//') else m[0],raw)
        return re.sub(r'\r?\n\s*\+', ' ', re.sub(r'\\[ \t]*\r?\n',' ',raw)).strip()
    dialect_by_aid={v['artifact_ref']:v['dialect'] for v in ir['views']}
    def canon(name,aid):
        return name.replace('\\<','<').replace('\\>','>') if dialect_by_aid.get(aid)=='spectre' else name
    for d in ir['definitions']:
        raw=logical(d['span_refs'][:1]);m=re.match(r'\.?subckt\s+(\S+)\s*(.*)',raw,re.I|re.S)
        if not m:errors.append('definition missing from source: '+d['id']);continue
        tail=re.split(r'\bparams:|\s+\$?\w+\s*=',m[2],maxsplit=1,flags=re.I)[0].strip()
        if tail.startswith('(') and tail.endswith(')'):tail=tail[1:-1]
        rawports=tail.split()
        if m[1]!=d['raw_name'] or rawports!=[p['raw_name'] for p in d['formal_ports']]:errors.append('formal source mismatch: '+d['id'])
        for k,p in enumerate(d['formal_ports']):
            n=registry.get(p['net_ref'],{})
            if p['ordinal']!=k+1 or p['canonical_name']!=canon(p['raw_name'],d['artifact_ref']) or n.get('canonical_name')!=p['canonical_name']:
                errors.append('formal net/source mismatch: '+d['id'])
        actual=[i['id'] for i in ir['instances'] if i['definition_scope_ref']==d['id']]
        if actual!=d['instance_refs']:errors.append('definition membership mismatch: '+d['id'])
    for i in ir['instances']:
        raw=logical(i['span_refs']);aid=i['artifact_ref'];rawpins=None;rawmaster=None;rawname=None
        if dialect_by_aid.get(aid)=='spectre':
            m=re.match(r'(\S+)\s+\(([^)]*)\)\s+(\S+)',raw,re.S)
            if m:rawname=m[1];rawpins=m[2].split();rawmaster=m[3]
        else:
            words=raw.split()
            if words:
                rawname=words[0];prefix=rawname[0].upper()
                if prefix=='M' and len(words)>=6:rawpins=words[1:5];rawmaster=words[5]
                elif prefix in ('R','C') and len(words)>=3:
                    rawpins=words[1:3];sub=re.search(r'\$SUB=(\S+)',raw,re.I);master=re.search(r'\$\[([^]]+)\]',raw)
                    if sub:rawpins.append(sub[1])
                    if master:rawmaster=master[1]
                elif prefix=='X':
                    head=re.split(r'\s+\w+\s*=',raw,maxsplit=1)[0].split()[1:]
                    if head:rawmaster=head[-1];rawpins=head[:-2] if '/' in head else head[:-1]
        if rawpins!=[t['raw_name'] for t in i['ordered_terminals']] or rawname!=i['raw_name'] or rawmaster is None or canon(rawmaster,aid)!=i['master_ref_or_name']:
            errors.append('instance source mismatch: '+i['id'])
        for k,t in enumerate(i['ordered_terminals']):
            n=registry.get(t['net_ref'],{})
            if t['ordinal']!=k+1 or t['canonical_name']!=canon(t['raw_name'],aid) or n.get('canonical_name')!=t['canonical_name']:
                errors.append('net/source mismatch: '+i['id'])
            if n.get('scope_ref') not in (i['definition_scope_ref'],aid+':global'):errors.append('net scope mismatch: '+i['id'])
        owner=registry.get(i['definition_scope_ref'])
        if owner and owner.get('formal_ports') is not None and len(owner['span_refs'])>=2:
            begins=spans[owner['span_refs'][0]]['fragments'][0]['byte_start'];ends=spans[owner['span_refs'][-1]]['fragments'][-1]['byte_end']
            own=spans.get(i['span_refs'][0],{}).get('fragments',[{}])[0].get('byte_start',-1)
            if not begins<own<ends:errors.append('instance outside definition source: '+i['id'])
    graph={}
    for c in ir['claims']:graph[c['id']]=c['support_refs']+c['assumption_refs']
    for r in ir['records']:
        graph[r['id']]=r['inputs']+r['support_refs']
        for ref in r['inputs']+r['outputs']:
            if ref not in registry:errors.append('record dangling: '+r['id'])
    seen=set();active=set()
    def walk(n):
        if n in active:errors.append('support cycle: '+n);return
        if n in seen:return
        active.add(n)
        for x in graph.get(n,[]):walk(x)
        active.remove(n);seen.add(n)
    for n in graph:walk(n)
    claims={c['id']:c for c in ir['claims']};records={r['id']:r for r in ir['records']}
    dialect={v['artifact_ref']:v['dialect'] for v in ir['views']}
    for c in ir['claims']:
        obj=registry.get(c['subject_ref'],{});pred=c['predicate'];kind=c['kind'];val=c['value']
        if kind in ('SIMULATED','INFERRED'):errors.append('static producer cannot assert '+kind+': '+c['id'])
        if kind=='UNKNOWN':
            if val is not None or c['status']!='blocked' or not c['uncertainty']:errors.append('invalid UNKNOWN: '+c['id'])
            if not any(c['id'] in g['affected_refs'] for g in ir['gaps']):errors.append('UNKNOWN without gap: '+c['id'])
        elif not c['support_refs']:errors.append('unsupported claim: '+c['id'])
        if kind=='DIRECT':
            if not all(x in spans for x in c['support_refs']):errors.append('DIRECT needs source spans: '+c['id'])
            text=' '.join(span_text.get(x,'') for x in c['support_refs'])
            if pred.startswith('declared_parameter.'):
                key=pred.split('.',1)[1];params=obj.get('parameters',obj.get('entries',[]));p=next((x for x in params if x['canonical_key']==key),None)
                if p is None or val!={'type':'expression','text':p['raw_expr']} or c['support_refs']!=p['raw_span_refs']:
                    errors.append('parameter entailment mismatch: '+c['id'])
                elif not re.search(re.escape(p['raw_key'])+r'\s*=\s*'+re.escape(p['raw_expr'])+r'(?=\s|$)',text):errors.append('parameter absent from source: '+c['id'])
            elif pred=='declared_connections':
                if val!={'type':'ordered_list','items':[t['raw_name'] for t in obj.get('ordered_terminals',[])]}:errors.append('connections mismatch: '+c['id'])
            elif pred=='declared_formal_ports':
                if val!={'type':'ordered_list','items':[p['raw_name'] for p in obj.get('formal_ports',[])]}:errors.append('formal ports mismatch: '+c['id'])
            elif pred=='declared_master':
                if val.get('text')!=obj.get('master_ref_or_name') or val.get('text') not in text.replace('\\<','<').replace('\\>','>'):errors.append('master mismatch: '+c['id'])
            elif pred=='declared_include':
                if val.get('text')!=obj.get('requested_path') or val.get('text') not in text:errors.append('include mismatch: '+c['id'])
            elif pred=='model_declaration':
                if not re.search(r'\b(?:model|subckt)\s+'+re.escape(val.get('text',''))+r'\b',text,re.I):errors.append('model declaration mismatch: '+c['id'])
            elif pred.startswith('declared_port_direction.'):
                if pred.split('.',1)[1]+':'+val.get('text','') not in text:errors.append('PININFO mismatch: '+c['id'])
            else:errors.append('unrecognized DIRECT predicate: '+pred)
        if kind=='DERIVED':
            r=records.get(c['support_refs'][0],{}) if len(c['support_refs'])==1 else {}
            if not r or c['id'] not in r.get('outputs',[]):errors.append('missing derivation: '+c['id']);continue
            method=r['method_ref']
            if method.startswith('literal_decimal:'):
                source=claims.get(r['inputs'][0],{})
                try:expected=decimal_text(scalar(source['value']['text'],method.split(':',1)[1]))
                except (NumericError,KeyError,TypeError):expected=None
                if val.get('decimal_string')!=expected or expected is None:errors.append('normalization mismatch: '+c['id'])
            elif method=='count_definition_instances':
                if val.get('decimal_string')!=str(len(obj.get('instance_refs',[]))):errors.append('count mismatch: '+c['id'])
            elif method=='bind_ports_by_ordinal':
                if val.get('items')!=obj.get('port_bindings'):errors.append('binding calculation mismatch: '+c['id'])
            else:errors.append('unsupported derivation method: '+method)
    if not any('support cycle' in e for e in errors):
        copied=copy.deepcopy(ir);fill_ancestry(copied)
        if [c['ancestry_kinds'] for c in copied['claims']]!=[c['ancestry_kinds'] for c in ir['claims']]:errors.append('ancestry mismatch')
    for key,value in policy_fields(ir).items():
        if ir['scope'].get(key)!=value:errors.append('source policy/status mismatch: '+key)
    # Validate positional mappings against their independent formal/actual arrays.
    for o in ir['occurrences']:
        if not o['port_bindings']:continue
        d=registry.get(o['definition_ref'],{});i=registry.get(o['instance_ref'],{})
        ports=d.get('formal_ports',[]);terms=i.get('ordered_terminals',[])
        if len(ports)!=len(o['port_bindings']):errors.append('binding arity mismatch: '+o['id']);continue
        for k,(p,b) in enumerate(zip(ports,o['port_bindings'])):
            if b['ordinal']!=k+1 or b['formal_name']!=p['canonical_name']:errors.append('formal binding order: '+o['id'])
            if terms and (k>=len(terms) or b['actual_name']!=terms[k]['canonical_name']):errors.append('actual binding order: '+o['id'])
    if ir['requirements']:errors.append('static MVP-A does not accept product requirements without a specification adapter')
    return sorted(set(errors))
