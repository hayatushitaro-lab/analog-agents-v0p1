"""Prepare bounded method dispatch cards; verify recorded handoffs, never launch agents."""
import argparse
import hashlib
import json
from pathlib import Path

METHODS={
 'ANALYST':{'analog-learn':['Study Existing Netlist','Topology Explainer'],'analog-audit':['checklists']},
 'VERIFIER':{'analog-verify':['pre-simulation','verification'],'spectre':['simulation']},
 'REVIEWER':{'analog-review':['Independence','Divergence']},
 'EDITOR':{'analog-recovery-report':['内容','交付门禁']},
 'ARCHITECT':{'analog-decompose':['interface'],'analog-integrate':['verification']}}

def record(path):
    p=Path(path).resolve(strict=True)
    return dict(path=str(p),sha256=hashlib.sha256(p.read_bytes()).hexdigest())

def prepare(role, question, repo, installed):
    methods=[];missing=[]
    for skill,topics in METHODS[role].items():
        choices=[Path(repo)/'skills'/skill/'SKILL.md',Path(installed)/skill/'SKILL.md']
        selected=next((p for p in choices if p.is_file()),None)
        if selected:methods.append(dict(skill=skill,topics=topics,**record(selected)))
        else:missing.append(skill)
    return dict(version='1',role=role,question=question,methods=methods,missing_methods=missing,
        inputs=[],outputs=[],acceptance=[],method_results=[],status='prepared',
        scope=dict(occurrence_paths=[],interfaces=[],chapters=[]),confirmed_conditions=[],unknowns=[],
        permissions=dict(write_roots=[],dut_write=False,simulation=False,external_send=False),
        resource_allocation=dict(remote_seconds=0,max_concurrent_runs=0),
        agent=dict(id=None,model=None,effort=None,model_selection_supported=None,delegated=False),
        author_id=None,requires_independent=False,limitations=[],closure=None)

def validate(card):
    errors=[]
    def fail(s):errors.append(s)
    try:
        if card['role'] not in METHODS or not card['question'].strip():fail('role/question')
        for item in card['methods']+card['inputs']+card['outputs']:
            if record(item['path'])['sha256']!=item['sha256']:fail('changed artifact: '+item['path'])
        if card['status']!='completed':fail('task not completed')
        if not card['inputs'] or not card['outputs'] or not card['acceptance']:fail('missing handoff/acceptance')
        roots=[Path(p).resolve() for p in card['permissions']['write_roots']]
        for output in card['outputs']:
            if not any(Path(output['path']).resolve().is_relative_to(root) for root in roots):fail('output outside task write roots')
        if {r['path'] for r in card['inputs']}&{r['path'] for r in card['outputs']}:fail('output aliases read-only input')
        if card['permissions']['dut_write']:fail('recovery never changes DUT')
        applied={r['skill'] for r in card['method_results'] if r.get('observation') and r.get('output_refs')}
        if {r['skill'] for r in card['methods']}-applied:fail('method read is not method result')
        outputs={r['path'] for r in card['outputs']}
        for result in card['method_results']:
            if not set(result.get('output_refs',[]))<=outputs:fail('method result cites absent output')
        if card['missing_methods'] and not card['limitations']:fail('missing method without limitation')
        agent=card['agent']
        if not agent['id'] or not agent['model'] or agent['model_selection_supported'] is None:fail('actual agent capability missing')
        requested=card.get('requested_agent', {})
        if any(requested.get(k) and requested[k]!=agent.get(k) for k in ('model','effort')):
            if not card.get('model_override_authorization'):fail('unapproved model override')
        if not agent['model_selection_supported'] and not card['limitations']:fail('unsupported selection must be disclosed')
        if card['requires_independent'] and (not card['author_id'] or card['author_id']==agent['id']):fail('independence missing')
        if not card['closure'] or not card['closure'].get('evidence_refs') or not card['closure'].get('reviewer_id'):fail('closure evidence missing')
        elif not set(card['closure']['evidence_refs'])<=outputs:fail('closure evidence absent')
    except (KeyError,TypeError,ValueError,OSError) as exc:fail('malformed handoff: '+str(exc))
    return dict(valid=not errors,errors=errors,limitation='Records are auditable declarations, not proof of agent identity or correct reasoning.')

def main():
    ap=argparse.ArgumentParser(description=__doc__);sub=ap.add_subparsers(dest='action',required=True)
    p=sub.add_parser('prepare');p.add_argument('--role',choices=METHODS,required=True);p.add_argument('--question',required=True)
    p.add_argument('--repo',required=True);p.add_argument('--installed',required=True);p.add_argument('--out',required=True)
    c=sub.add_parser('check');c.add_argument('card');a=ap.parse_args()
    if a.action=='prepare':
        card=prepare(a.role,a.question,a.repo,a.installed)
        card['permissions']['write_roots']=[str(Path(a.out).resolve().parent)]
        with open(a.out,'x',encoding='utf-8') as f:json.dump(card,f,ensure_ascii=False,indent=2)
        return 0
    result=validate(json.loads(Path(a.card).read_text(encoding='utf-8-sig')))
    print(json.dumps(result,ensure_ascii=False,indent=2));return 0 if result['valid'] else 1
if __name__=='__main__':raise SystemExit(main())
