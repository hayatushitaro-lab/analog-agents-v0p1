"""Lossless line ledger and explicit restricted SCS / auCdl adapters."""
import re
from .numeric import scalar, decimal_text, NumericError


def canonical(name, dialect):
    # Only the observed Spectre escaped bus delimiters are normalized.
    return name.replace('\\<','<').replace('\\>','>') if dialect=='spectre' else name


def diagnostic(view, code, reason, refs=(), scope=None, severity='error', stage='syntax'):
    d={'id':f"{view['artifact_ref']}:diag:{len(view['diagnostics'])}", 'code':code,
       'severity':severity,'stage':stage,'source_span_refs':list(refs),
       'affected_scope_refs':[scope] if scope else [],'reason':reason,
       'recovery_action':'Preserve raw evidence; resolve the reported scope before stronger claims.'}
    view['diagnostics'].append(d)
    return d


def spectre_code(text):
    """Strip only unquoted // comments from the syntax view, never raw evidence."""
    quote = None
    escape = False
    for i, ch in enumerate(text):
        if escape:
            escape = False
            continue
        if ch == '\\':
            escape = True
            continue
        if quote:
            if ch == quote:
                quote = None
        elif ch in ('"', "'"):
            quote = ch
        elif ch == '/' and text[i:i + 2] == '//':
            return text[:i]
    return text


def logical_lines(data, aid, dialect):
    """Every physical byte belongs to exactly one span, including blank/comment lines."""
    lines=data.splitlines(keepends=True); spans=[]; rows=[]; offset=0
    for line_no, raw in enumerate(lines,1):
        text=raw.decode('utf-8').rstrip('\r\n')
        if line_no==1: text=text.lstrip('\ufeff')
        fragment={'line':line_no,'byte_start':offset,'byte_end':offset+len(raw)};offset+=len(raw)
        stripped=text.strip()
        if dialect=='spectre':
            text=spectre_code(text)
            continuation=bool(rows and rows[-1]['pending'])
            if continuation and (not stripped or stripped.startswith('//')):
                rows[-1]['lexical_error']='continuation interrupted by blank/comment'
                rows[-1]['pending']=False;continuation=False
            trailing=bool(re.search(r'(?<!\\)\\\s*$',text)) and not stripped.startswith('//')
            piece=re.sub(r'\\\s*$','',text) if trailing else text
        else:
            continuation=stripped.startswith('+')
            trailing=False;piece=stripped[1:] if continuation else text
        if continuation and rows and rows[-1]['kind_hint'] not in ('blank','comment'):
            row=rows[-1];row['text']+=' '+piece.strip();row['raw']+=raw.decode('utf-8')
            spans[-1]['fragments'].append(fragment);row['pending']=trailing
        else:
            sid=f'{aid}:span:{line_no}'
            spans.append({'id':sid,'artifact_ref':aid,'coordinate_system':'utf8_bytes_half_open_lines_1based','fragments':[fragment]})
            hint='blank' if not stripped else 'comment' if stripped.startswith('//') or (dialect=='cdl' and stripped.startswith('*') and not stripped.startswith('*.')) else 'statement'
            rows.append({'id':f'{aid}:statement:{line_no}','span_ref':sid,'text':piece.strip(),'raw':raw.decode('utf-8'),'pending':trailing,'kind_hint':hint})
            if continuation: rows[-1]['lexical_error']='orphan continuation'
    if rows and rows[-1]['pending']: rows[-1]['lexical_error']='unterminated continuation'
    return rows,spans,len(lines)


def tokens(text):
    """Whitespace tokens with balanced parameter expressions and quoted strings."""
    result=[];buf=[];depth=0;quote=None;escape=False
    for ch in text:
        if escape: buf.append(ch);escape=False;continue
        if ch=='\\':buf.append(ch);escape=True;continue
        if quote:
            buf.append(ch)
            if ch==quote:quote=None
            continue
        if ch in ('"',"'"):quote=ch;buf.append(ch);continue
        if ch=='(':depth+=1
        if ch==')':
            depth-=1
            if depth<0:raise ValueError('unbalanced parentheses')
        if ch.isspace() and depth==0:
            if buf:result.append(''.join(buf));buf=[]
        else:buf.append(ch)
    if quote or depth or escape:raise ValueError('unterminated token')
    if buf:result.append(''.join(buf))
    # Allow key = value and key= value without rewriting raw source.
    joined=[];i=0
    while i<len(result):
        t=result[i]
        if i+2<len(result) and result[i+1]=='=':t+='='+result[i+2];i+=2
        elif t.endswith('=') and i+1<len(result):t+=result[i+1];i+=1
        joined.append(t);i+=1
    return joined


def parameters(parts, span, dialect):
    result=[]
    for token in parts:
        if '=' not in token:raise ValueError('unsupported positional parameter: '+token)
        key,expr=token.split('=',1)
        if not key or not expr:raise ValueError('empty parameter')
        norm=None
        try:norm={'decimal_string':decimal_text(scalar(expr,dialect)),'unit':None,'dimension':None}
        except NumericError:pass
        result.append({'raw_key':key,'canonical_key':key.lstrip('$').lower(),'raw_expr':expr,
                       'raw_span_refs':[span],'normalized_value':norm,'normalization_record_ref':None,
                       'semantic_status':'scalar_resolved' if norm else 'lexical_only',
                       'semantic_contract_ref':None,'unit_status':'unresolved'})
    return result


def parse(data, artifact_id, dialect):
    if dialect not in ('spectre','cdl'):raise ValueError('unsupported dialect')
    aid=artifact_id
    rows,spans,line_count=logical_lines(data,aid,dialect)
    v={'artifact_ref':aid,'dialect':dialect,'statements':rows,'source_spans':spans,'definitions':[],
       'instances':[],'nets':[],'dependencies':[],'diagnostics':[],'conditions':[],
       'dialect_contexts':[{'id':f'{aid}:context','dialect':dialect,'case_policy':'exact_preserved_unverified'}],
       'globals':[],'line_count':line_count,'status':'complete'}
    scope=None;defs={};netmap={};language_ok=True
    def net(name, sid, formal=False):
        cn=canonical(name,dialect)
        owner=f'{aid}:global' if cn in v['globals'] else scope['id'] if scope else f'{aid}:harness'
        nid=owner+':net:'+cn
        if nid not in netmap:
            item={'id':nid,'scope_ref':owner,'raw_name':name,'canonical_name':cn,'name_policy_ref':f'{aid}:context','declaration_refs':[sid],
                  'role':'global' if cn in v['globals'] else 'port' if formal else 'local'}
            netmap[nid]=item;v['nets'].append(item)
        elif sid not in netmap[nid]['declaration_refs']:netmap[nid]['declaration_refs'].append(sid)
        return nid
    for row in rows:
        sid=row['span_ref'];text=row['text'];row['scope_ref']=scope['id'] if scope else f'{aid}:harness'
        row['kind']=row.pop('kind_hint');row.pop('pending',None)
        if row.get('lexical_error'):
            diagnostic(v,'LEXICAL_UNSUPPORTED',row['lexical_error'],[sid],row['scope_ref']);row['kind']='unsupported';continue
        if row['kind'] in ('blank','comment'):continue
        try:
            t=tokens(text);first=t[0];lower=first.lower()
            if lower=='simulator':
                row['kind']='configuration'
                language_ok='lang=spectre' in text
                if not language_ok: diagnostic(v,'LEXICAL_UNSUPPORTED','language switch outside supported subset',[sid],row['scope_ref'])
                if 'insensitive=' in text:diagnostic(v,'NAME_POLICY_UNRESOLVED','case setting recorded; scope propagation unverified',[sid],row['scope_ref'],'warning')
                continue
            if not language_ok:raise ValueError('statement in unsupported language context')
            if dialect=='cdl' and first.startswith('*.'):
                row['kind']='annotation'
                if lower=='*.pininfo' and scope:
                    mapping=dict(x.rsplit(':',1) for x in t[1:] if ':' in x)
                    for p in scope['formal_ports']:
                        if p['raw_name'] in mapping:p['declared_direction']=mapping[p['raw_name']];p['direction_span_refs']=[sid]
                continue
            if lower in ('subckt','.subckt'):
                if scope:raise ValueError('nested definition outside subset')
                if len(t)<2:raise ValueError('missing definition name')
                name=t[1];cn=canonical(name,dialect)
                if cn in defs:raise ValueError('duplicate definition')
                split=next((i for i,x in enumerate(t[2:],2) if '=' in x or x.lower()=='params:'),len(t))
                ports=t[2:split]
                if ports and ports[0].startswith('('):ports=' '.join(ports)[1:-1].split()
                param_parts=[x for x in t[split:] if x.lower()!='params:']
                scope={'id':f'{aid}:def:{cn}','artifact_ref':aid,'raw_name':name,'canonical_name':cn,'dialect_context_ref':f'{aid}:context',
                       'formal_ports':[],'parameters':parameters(param_parts,sid,dialect),'instance_refs':[],'span_refs':[sid],'status':'complete'}
                defs[cn]=scope;v['definitions'].append(scope)
                for i,p in enumerate(ports):scope['formal_ports'].append({'ordinal':i+1,'raw_name':p,'canonical_name':canonical(p,dialect),'net_ref':net(p,sid,True),'declared_direction':None})
                if len({p['canonical_name'] for p in scope['formal_ports']})!=len(ports):raise ValueError('duplicate formal port')
                row['kind']='definition';row['scope_ref']=scope['id'];continue
            if lower in ('ends','.ends'):
                if not scope:raise ValueError('unmatched ends')
                if len(t)>1 and canonical(t[1],dialect)!=scope['canonical_name']:raise ValueError('ends name mismatch')
                scope['span_refs'].append(sid);row['kind']='end_definition';scope=None;continue
            if lower in ('parameters','.param'):
                row['kind']='parameters';ps=parameters(t[1:],sid,dialect)
                if scope:scope['parameters'].extend(ps)
                else:v.setdefault('global_parameters',[]).extend(ps)
                row['parameters']=ps;continue
            if lower in ('global','.global'):
                row['kind']='global'
                for p in t[1:]:v['globals'].append(canonical(p,dialect));net(p,sid)
                continue
            if lower in ('include','.include','.inc','.lib','ahdl_include'):
                row['kind']='dependency'
                if len(t)<2:raise ValueError('include path missing')
                section=next((x.split('=',1)[1] for x in t[2:] if x.lower().startswith('section=')),None)
                v['dependencies'].append({'id':f'{aid}:dependency:{len(v["dependencies"])}','from_ref':aid,'requested_path':t[1].strip('"\''),
                                           'requested_section':section,'local_candidate_ref':None,'resolution_state':'not_resolved','span_refs':[sid]})
                continue
            if len(t)>1 and t[1].lower() in ('options','info','dc','ac','tran','noise','stb','pss','pnoise'):
                row['kind']='configuration' if t[1].lower() in ('options','info') else 'analysis_request'
                ps=parameters(t[2:],sid,dialect)
                v['conditions'].append({'id':f'{aid}:condition:{len(v["conditions"])}','role':'declared_export_options','entries':ps,'source_refs':[sid], 'statement_name':first,'statement_type':t[1]})
                continue
            ext={};is_call=False;device_class='unknown'
            if dialect=='spectre':
                if len(t)<3 or not t[1].startswith('(') or not t[1].endswith(')'):raise ValueError('unsupported Spectre statement')
                pins=t[1][1:-1].split();master=t[2];ps=parameters(t[3:],sid,dialect)
            else:
                prefix=first[0].upper()
                if prefix=='M':
                    if len(t)<6:raise ValueError('MOS terminal/master missing')
                    pins=t[1:5];master=t[5];ps=parameters(t[6:],sid,dialect);device_class='mos_syntax'
                elif prefix in ('R','C'):
                    if len(t)<4:raise ValueError('passive record too short')
                    pins=t[1:3];master=None;param_tokens=[]
                    for x in t[3:]:
                        if x.startswith('$[') and x.endswith(']'):master=x[2:-1];ext['$master']=master
                        elif x.upper().startswith('$SUB='):ext['$SUB']=x.split('=',1)[1];pins.append(ext['$SUB'])
                        elif '=' in x:param_tokens.append(x)
                        else:raise ValueError('positional passive value outside subset')
                    if master is None:raise ValueError('passive master extension required in CDL subset')
                    ps=parameters(param_tokens,sid,dialect);device_class='passive_syntax'
                elif prefix=='X':
                    boundary=next((i for i,x in enumerate(t) if '=' in x),len(t));head=t[1:boundary]
                    if '/' in head:
                        slash=head.index('/')
                        if slash!=len(head)-2:raise ValueError('invalid slash/master')
                        pins=head[:slash];master=head[-1]
                    else:pins=head[:-1];master=head[-1]
                    ps=parameters(t[boundary:],sid,dialect);is_call=True
                else:raise ValueError('unsupported CDL statement')
            owner=scope['id'] if scope else f'{aid}:harness'
            iid=owner+':inst:'+first
            if any(i['id']==iid for i in v['instances']):raise ValueError('duplicate instance')
            item={'id':iid,'artifact_ref':aid,'definition_scope_ref':owner,'raw_name':first,'master_ref_or_name':canonical(master,dialect),
                  'ordered_terminals':[{'ordinal':i+1,'raw_name':p,'net_ref':net(p,sid),'canonical_name':canonical(p,dialect),'physical_role':None} for i,p in enumerate(pins)],
                  'parameters':ps,'span_refs':[sid],'device_class':device_class,'is_subckt_call':is_call,'resolution_status':'unresolved','extensions':ext}
            if len({p['canonical_key'] for p in ps})!=len(ps):diagnostic(v,'DUPLICATE_PARAMETER','duplicate parameter assignment',[sid],owner)
            v['instances'].append(item)
            if scope:scope['instance_refs'].append(iid)
            row['kind']='instance';row['instance_ref']=iid
        except (ValueError,IndexError) as exc:
            row['kind']='unsupported';diagnostic(v,'LEXICAL_UNSUPPORTED',str(exc),[sid],row['scope_ref'])
    if scope:diagnostic(v,'HIERARCHY_UNCLOSED','missing ends',scope['span_refs'],scope['id'])
    for i in v['instances']:
        if i['master_ref_or_name'] in defs:
            i['is_subckt_call']=True;i['resolution_status']='design_definition_found';i['master_definition_ref']=defs[i['master_ref_or_name']]['id']
    for d in v['definitions']:
        if any(x['severity']=='error' and d['id'] in x['affected_scope_refs'] for x in v['diagnostics']):d['status']='blocked'
    if any(d['severity']=='error' for d in v['diagnostics']):v['status']='partial'
    return v
