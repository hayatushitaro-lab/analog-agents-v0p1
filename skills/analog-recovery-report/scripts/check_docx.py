"""Check template-native bullets and fixed labels using an explicit template profile.

Standard library only. Does not modify DOCX or replace visual rendering review.
"""
import argparse
import json
import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

NS={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
def tag(s):return '{'+NS['w']+'}'+s
def text(p):return ''.join(x.text or '' for x in p.iter(tag('t')))
def read(path):
    with zipfile.ZipFile(path) as z:
        body=ET.fromstring(z.read('word/document.xml')).find('w:body',NS)
        numbering=ET.fromstring(z.read('word/numbering.xml')) if 'word/numbering.xml' in z.namelist() else ET.Element('none')
    return body.findall('w:p',NS),numbering

def page_fields(path):
    """Count usable fields in their original header/footer location, not decoys."""
    result=[]
    def enabled(el):
        return el is not None and el.get(tag('val'),'true') not in ('0','false','off')
    with zipfile.ZipFile(path) as z:
        for name in z.namelist():
            if not name.startswith(('word/footer','word/header')) or not name.endswith('.xml'):continue
            tree=ET.fromstring(z.read(name));location='footer' if name.startswith('word/footer') else 'header'
            parents={c:p for p in tree.iter() for c in p}
            def hidden(el):
                while el is not None:
                    if any(enabled(el.find('w:rPr/w:'+v,NS)) for v in ('vanish','webHidden')):return True
                    el=parents.get(el)
                return False
            stack=[]
            for el in tree.iter():
                if el.tag==tag('fldSimple'):
                    instr=el.get(tag('instr'),'').strip().split()
                    if instr:result.append((location,instr[0],not enabled_field_lock(el) and not any(hidden(r) for r in el.iter(tag('r')))))
                elif el.tag==tag('fldChar'):
                    kind=el.get(tag('fldCharType'))
                    if kind=='begin':stack.append({'code':'','good':not enabled_field_lock(el) and not hidden(el)})
                    elif kind=='end' and stack:
                        f=stack.pop();parts=f['code'].strip().split()
                        if parts:result.append((location,parts[0],f['good']))
                elif stack and el.tag==tag('instrText'):
                    stack[-1]['code']+=el.text or '';stack[-1]['good'] &= not hidden(el)
                elif stack and el.tag==tag('t'):
                    stack[-1]['good'] &= not hidden(el)
    return result

def enabled_field_lock(el):
    return el.get(tag('fldLock'),'false') not in ('0','false','off')
def bullet(p,numbering):
    num=p.find('w:pPr/w:numPr/w:numId',NS);level=p.find('w:pPr/w:numPr/w:ilvl',NS)
    if num is None:return None
    n=next((n for n in numbering.findall('w:num',NS) if n.get(tag('numId'))==num.get(tag('val'))),None)
    if n is None:return None
    aid=n.find('w:abstractNumId',NS)
    if aid is None:return None
    abstract=next((n for n in numbering.findall('w:abstractNum',NS) if n.get(tag('abstractNumId'))==aid.get(tag('val'))),None)
    if abstract is None:return None
    depth=level.get(tag('val')) if level is not None else '0'
    override=next((x.find('w:lvl',NS) for x in n.findall('w:lvlOverride',NS) if x.get(tag('ilvl'))==depth and x.find('w:lvl',NS) is not None),None)
    lvl=override if override is not None else next((x for x in abstract.findall('w:lvl',NS) if x.get(tag('ilvl'))==depth),None)
    if lvl is None:return None
    fmt=lvl.find('w:numFmt',NS);symbol=lvl.find('w:lvlText',NS);font=lvl.find('w:rPr/w:rFonts',NS)
    if fmt is None or symbol is None:return None
    return (fmt.get(tag('val')),symbol.get(tag('val')),tuple(sorted(font.attrib.items())) if font is not None else ())

def validate(template_path,document_path,profile):
    errors=[]
    try:
        if not isinstance(profile,dict) or not (profile.get('bullet_sections') or profile.get('label_sections')):raise ValueError('empty template profile')
        tp,tn=read(template_path);ps,nn=read(document_path)
        def section(rule):
            starts=[i for i,p in enumerate(ps) if text(p).strip()==rule['start']]
            if len(starts)!=1:raise ValueError('section start missing or ambiguous: '+rule['start'])
            start=starts[0];end=next((i for i in range(start+1,len(ps)) if text(ps[i]).strip()==rule['end']),None)
            if end is None:raise ValueError('section end missing: '+rule['end'])
            return ps[start+1:end]
        for rule in profile.get('bullet_sections',[]):
            examples=[p for p in tp if text(p).strip()==rule['template_example']]
            if 'template_occurrence' in rule:
                occurrence=rule['template_occurrence']
                if type(occurrence) is not int or occurrence<0 or occurrence>=len(examples):raise ValueError('invalid template example occurrence')
                examples=[examples[occurrence]]
            if len(examples)!=1:raise ValueError('template example missing or ambiguous')
            expected=bullet(examples[0],tn)
            if not expected or expected[0]!='bullet':raise ValueError('template example is not a supported native bullet')
            checked=0
            for p in section(rule):
                s=text(p).strip()
                if not s or s in rule.get('skip',[]):continue
                checked+=1
                if re.match(r'^[*＊]',s) or bullet(p,nn)!=expected:errors.append('template bullet mismatch: '+s[:60])
            if not checked:errors.append('empty bullet section: '+rule['start'])
        for rule in profile.get('label_sections',[]):
            if not isinstance(rule['labels'],list) or not rule['labels'] or not all(isinstance(s,str) and s for s in rule['labels']):raise ValueError('empty/invalid fixed labels')
            groups=[section(rule)]
            if rule.get('per_subsection'):
                groups=[];current=[];started=False
                for p in section(rule):
                    style=p.find('w:pPr/w:pStyle',NS)
                    is_heading=style is not None and style.get(tag('val')) in rule['subsection_styles']
                    if is_heading:
                        if current:groups.append(current)
                        current=[];started=True
                    elif started:current.append(p)
                if current:groups.append(current)
                groups=[g for g in groups if any(text(p).strip() for p in g)]
                if not groups:errors.append('no verification subsections')
            for group in groups:
              found=set()
              for p in group:
                s=text(p).strip()
                for label in rule['labels']:
                    # Recognize ordinary manual numbering only; unrelated numbered prose remains allowed.
                    match=re.match(r'^(?P<prefix>(?:[（(]\d+[）)]|\d+[.、．)]|[①-⑳])\s*)?'+re.escape(label)+r'\s*[：:]',s)
                    if not match:continue
                    found.add(label)
                    if match['prefix'] or p.find('w:pPr/w:numPr',NS) is not None:errors.append('numbered fixed label: '+s[:60])
              for label in set(rule['labels'])-found:errors.append('required label missing in subsection: '+label)
        if profile.get('preserve_page_fields'):
            expected=page_fields(template_path);actual=page_fields(document_path)
            for location in ('header','footer'):
                for name in ('PAGE','NUMPAGES'):
                    if actual.count((location,name,True))<expected.count((location,name,True)):
                        errors.append('template field removed: '+name+' (visible, unlocked '+location+' required)')
    except (OSError,ValueError,KeyError,TypeError,AttributeError,ET.ParseError,zipfile.BadZipFile) as e:errors.append('cannot validate: '+str(e))
    return {'valid':not errors,'errors':errors,'limits':['Profile must be reviewed against the actual template. Inherited numbering/styles need explicit normalization; visual QA and content entailment remain separate.']}

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('template');ap.add_argument('document');ap.add_argument('profile',nargs='?',default=str(Path(__file__).resolve().parents[1]/'assets/fm-analog-v1/check-profile.json'));a=ap.parse_args()
    try:
        with open(a.profile,encoding='utf-8-sig') as f:profile=json.load(f)
        result=validate(a.template,a.document,profile)
    except (OSError,ValueError) as e:result={'valid':False,'errors':[str(e)]}
    print(json.dumps(result,ensure_ascii=False,indent=2));return 0 if result['valid'] else 1

if __name__=='__main__':raise SystemExit(main())
