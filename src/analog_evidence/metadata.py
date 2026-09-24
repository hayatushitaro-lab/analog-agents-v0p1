"""Filtered declaration index; deliberately not a physical model interpreter."""
import re


def scan_metadata(data,aid,needed):
    result={'artifact_ref':aid,'sections':[],'declarations':[],'includes':[],'settings':[],'source_spans':[],
            'active_binding_verified':False,'uncertainty':['Lexical declaration index only; model equations and branch semantics are not interpreted.']}
    section=None;library=None;offset=0;block_comment=False
    for n,raw in enumerate(data.splitlines(keepends=True),1):
        s=raw.decode('utf8').strip();start=offset;offset+=len(raw)
        # Conservatively skip complete block comment regions.
        if block_comment:
            if '*/' in s:block_comment=False
            continue
        if s.startswith('/*'):
            block_comment='*/' not in s;continue
        if not s or s.startswith('//'):continue
        sid=f'{aid}:metadata_span:{n}';item=None
        if m:=re.match(r'library\s+(\S+)',s,re.I):library=m[1]
        elif m:=re.match(r'section\s+(\S+)',s,re.I):
            section=m[1];item={'name':section,'library':library,'span_refs':[sid]};result['sections'].append(item)
        elif re.match(r'endsection\b',s,re.I):section=None
        elif re.match(r'endlibrary\b',s,re.I):library=None
        elif m:=re.match(r'(?:include|ahdl_include)\s+["\']([^"\']+)["\'](?:\s+section=(\S+))?',s,re.I):
            item={'id':f'{aid}:metadata_dependency:{n}','requested_path':m[1],'requested_section':m[2],'from_section':section,'library':library,
                  'kind':'behavior' if s.lower().startswith('ahdl') else 'include','span_refs':[sid]};result['includes'].append(item)
        elif m:=re.match(r'(model|subckt)\s+(\S+)\s*(.*)',s,re.I):
            if m[2] not in needed:continue
            tail=m[3];ports=[]
            if m[1].lower()=='subckt':
                pm=re.match(r'\(([^)]*)\)',tail)
                if pm:ports=pm[1].split()
            item={'id':f'{aid}:declaration:{n}','name':m[2],'declaration_type':m[1].lower(),'model_type':tail.split()[0] if m[1].lower()=='model' and tail.split() else None,
                  'formal_ports':ports,'section':section,'library':library,'span_refs':[sid]};result['declarations'].append(item)
        elif re.match(r'simulator\b',s,re.I):
            item={'declaration':s,'span_refs':[sid]};result['settings'].append(item)
        if item is not None:result['source_spans'].append({'id':sid,'artifact_ref':aid,'coordinate_system':'utf8_bytes_half_open_lines_1based','fragments':[{'line':n,'byte_start':start,'byte_end':offset}]})
    return result


def section_closure(index,aid,section,resolver,max_nodes=10000):
    result={'nodes':[],'cycles':[],'unresolved':[],'behavior_refs':[],'active_binding_verified':False};seen=set()
    def visit(a,s,stack):
        node=(a,s)
        if node in stack:result['cycles'].append([list(x) for x in stack+[node]]);return
        if node in seen:return
        if len(seen)>=max_nodes:result['unresolved'].append({'reason':'dependency_budget','node':list(node)});return
        seen.add(node);result['nodes'].append(list(node))
        m=index.get(a)
        if not m:result['unresolved'].append({'reason':'not_admitted','node':list(node)});return
        if s is not None and s not in {x['name'] for x in m['sections']}:
            result['unresolved'].append({'reason':'section_not_found','node':list(node)});return
        for dep in m['includes']:
            if dep['from_section'] not in (None,s):continue
            if dep['kind']=='behavior':result['behavior_refs'].append(dep);continue
            target=resolver(a,dep['requested_path'])
            if target is None:result['unresolved'].append({'reason':'not_admitted','dependency_ref':dep['id']});continue
            visit(target,dep['requested_section'],stack+[node])
    visit(aid,section,[])
    return result
