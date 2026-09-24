#!/usr/bin/env python3
"""Project continuation in the existing wiki, without forward-design convergence.

  .venv/Scripts/python.exe tools/recovery_wiki.py --repo . prepare request.json --out WORK_TASK/wiki-change
  .venv/Scripts/python.exe tools/recovery_wiki.py --repo . apply WORK_TASK/wiki-change
  .venv/Scripts/python.exe tools/recovery_wiki.py --repo . recover WORK_TASK/wiki-change
  .venv/Scripts/python.exe tools/recovery_wiki.py --repo . audit-index

Prepare produces only affected-file snapshots and a reviewable diff. Apply uses
optimistic hashes plus a recovery-writer lock. Original wiki tools do not honor
that lock: use a single writer, not concurrent editors. This is not an electrical
validator or a new knowledge store. All live paths are workspace-contained.
"""
import argparse
import copy
import difflib
import hashlib
import importlib.util
import json
import os
import re
import tempfile
from pathlib import Path

import yaml


class ContractError(ValueError):
    pass


def inside(root, path):
    root = Path(root).resolve()
    result = (root / path).resolve()
    if not result.is_relative_to(root):
        raise ContractError(f'path outside workspace: {path}')
    return result


def sha(data):
    return hashlib.sha256(data).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def dump_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def atomic_write(path, data):
    """Replace one file; a partial write only damages the disposable sibling."""
    fd, name = tempfile.mkstemp(prefix='.recovery-', suffix='.tmp', dir=path.parent)
    temp = Path(name)
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def load_ops(repo):
    path = inside(repo, 'tools/wiki_ops.py')
    spec = importlib.util.spec_from_file_location('recovery_original_wiki_ops', path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def validate_ref(repo, ref):
    if not isinstance(ref, dict) or not all(ref.get(k) for k in ('path', 'sha256')):
        raise ContractError('evidence reference requires path and sha256')
    path = inside(repo, ref['path'])
    if not path.is_file() or sha(path.read_bytes()) != ref['sha256']:
        raise ContractError(f'evidence missing or changed: {ref["path"]}')
    return path


def wiki_path(repo, path):
    relative = Path(path)
    if relative.anchor or '..' in relative.parts:
        raise ContractError('wiki paths must be relative and contain no parent traversal')
    root = inside(repo, 'wiki')
    result = inside(root, path)
    parts = result.relative_to(root).parts
    if not parts or parts[0] not in {
        'projects', 'topologies', 'strategies', 'corner-lessons', 'anti-patterns',
        'index.yml', 'edges.jsonl',
    }:
        raise ContractError(f'not an existing wiki location: {path}')
    return result


def audit_index(repo):
    ops = load_ops(repo)
    wiki_path(repo, 'index.yml')
    issues = []
    entries = ops.load_index(str(inside(repo, 'wiki')))
    for key, meta in entries.items():
        try:
            path = wiki_path(repo, meta['path'])
            if not path.is_file():
                issues.append({'id': key, 'issue': 'missing', 'path': meta['path']})
        except (ValueError, KeyError) as exc:
            issues.append({'id': key, 'issue': str(exc)})
    return {'entries': len(entries), 'issues': issues,
            'scope': 'index targets only; does not recursively certify historical evidence'}


def _validate_request(repo, request):
    allowed = {'project_id', 'create_project', 'update_id', 'date', 'block',
               'delivery_status', 'result', 'evidence_refs', 'iterations_ref',
               'narrative', 'entry_updates', 'new_entries', 'edges', 'edge_updates', 'bundle_ref',
               'project_index_summary'}
    if set(request) - allowed:
        raise ContractError(f'unknown request fields: {set(request) - allowed}')
    for key in ('update_id', 'block'):
        if not re.fullmatch(r'[A-Za-z0-9_-]+', request.get(key, '')):
            raise ContractError(f'invalid {key}')
    if request.get('delivery_status') not in {'partial', 'blocked', 'complete'}:
        raise ContractError('delivery_status must be partial, blocked or complete')
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', request.get('date', '')):
        raise ContractError('date must be YYYY-MM-DD')
    for key in ('result', 'narrative'):
        if not isinstance(request.get(key), str) or not request[key].strip():
            raise ContractError(f'{key} must be nonempty')
    if 'project_index_summary' in request:
        value = request['project_index_summary']
        if not isinstance(value, str) or not value.strip() or request.get('create_project'):
            raise ContractError('project_index_summary requires a nonempty string and an existing project')
    if not request.get('evidence_refs'):
        raise ContractError('evidence_refs must not be empty')
    for ref in request['evidence_refs']:
        validate_ref(repo, ref)
        if not ref.get('locator'):
            raise ContractError('evidence requires a locator')
    if request.get('bundle_ref'):
        validate_ref(repo, request['bundle_ref'])
    path = validate_ref(repo, request['iterations_ref'])
    rows = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]
    if not rows:
        raise ContractError('empty recovery iterations')
    keys = {'question_id', 'iteration', 'before', 'action', 'evidence_refs', 'after',
            'remaining', 'next_action', 'stop_reason'}
    known = {ref['path'] for ref in request['evidence_refs']}
    seen = set()
    for row in rows:
        if not keys <= row.keys() or not isinstance(row['question_id'], str) or not row['question_id']:
            raise ContractError('incomplete recovery iteration')
        if type(row['iteration']) is not int or row['iteration'] < 1:
            raise ContractError('iteration must be a positive integer')
        key = (row['question_id'], row['iteration'])
        if key in seen:
            raise ContractError('duplicate question iteration')
        seen.add(key)
        if not row['evidence_refs'] or any(ref not in known for ref in row['evidence_refs']):
            raise ContractError('iteration references must resolve to declared local evidence')
    return rows


def bundle_snapshot(repo, request):
    if not request.get('bundle_ref'):
        return {}
    manifest = validate_ref(repo, request['bundle_ref'])
    if manifest.name != 'manifest.json':
        raise ContractError('bundle_ref must select manifest.json')
    snapshot = {}
    for name in ('manifest', 'design_evidence', 'report_requirements', 'metrics', 'coverage', 'review'):
        path = inside(repo, manifest.parent / (name + '.json'))
        snapshot[path.relative_to(Path(repo).resolve()).as_posix()] = sha(path.read_bytes())
    return snapshot


def prepare(repo, request, out):
    repo = Path(repo).resolve()
    out = inside(repo, out)
    if out.is_relative_to(inside(repo, 'wiki')):
        raise ContractError('drafts must be outside the live wiki')
    rows = _validate_request(repo, request)
    ops = load_ops(repo)
    wiki_path(repo, 'index.yml')
    entries = ops.load_index(str(inside(repo, 'wiki')))
    project_id = request.get('project_id')
    create = request.get('create_project')
    if bool(project_id) == bool(create):
        raise ContractError('select one existing project_id or create_project')
    if create:
        if set(create) - {'name', 'path', 'tags', 'architecture'}:
            raise ContractError('invalid create_project fields')
        project_id = ops.next_id(entries, 'proj')
        rel = create['path']
        parts = Path(rel).parts
        if len(parts) != 3 or parts[0] != 'projects' or parts[-1] != 'summary.yml':
            raise ContractError('new project path must be projects/<case>/summary.yml')
        if wiki_path(repo, rel).exists() or any(m['path'] == rel for m in entries.values()):
            raise ContractError('project path already in use; continue its existing ID')
        entries[project_id] = {'path': rel, 'type': 'project', 'summary': create['name']}
        summary = dict(id=project_id, type='project', name=create['name'], tags=create.get('tags', []),
                       architecture=create.get('architecture', 'unknown'), convergence=False,
                       total_blocks=1, total_iterations=len(rows), created=request['date'])
    else:
        if project_id not in entries or entries[project_id]['type'] != 'project':
            raise ContractError('project ID not found')
        rel = entries[project_id]['path']
        wiki_path(repo, rel)
        summary = ops.load_entry(str(inside(repo, 'wiki')), rel)
        canonical_identity = summary.get('id') == project_id and summary.get('type') == 'project'
        legacy_identity = (summary.get('proj-index') == project_id
                           and ('id' not in summary or summary['id'] == project_id)
                           and ('type' not in summary or summary['type'] == 'project'))
        conflicting_legacy = 'proj-index' in summary and summary['proj-index'] != project_id
        if (not (canonical_identity or legacy_identity) or conflicting_legacy
                or Path(rel).name != 'summary.yml'):
            raise ContractError('selected project requires canonical identity or matching legacy proj-index in summary.yml')
    out.mkdir(parents=True, exist_ok=False)
    stage = out / 'candidate'
    stage.mkdir()
    originals = {}

    def snapshot(relative):
        live = wiki_path(repo, relative)
        if relative not in originals:
            data = live.read_bytes() if live.exists() else None
            originals[relative] = data
            target = stage / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            if data is not None:
                target.write_bytes(data)
        return stage / relative

    def write_yaml(relative, value):
        snapshot(relative).write_text(yaml.safe_dump(value, sort_keys=False, allow_unicode=True), encoding='utf-8')

    # Only affected files are copied. Never call archive_project.
    snapshot('index.yml')
    snapshot('edges.jsonl')
    if 'project_index_summary' in request:
        summary.setdefault('index_revisions', []).append(dict(
            date=request['date'], update_id=request['update_id'], reason=request['result'],
            previous_index_entry=copy.deepcopy(entries[project_id]), evidence_refs=request['evidence_refs']))
        entries[project_id]['summary'] = request['project_index_summary']
    case = Path(rel).parent.as_posix()
    trajectory_path = f'{case}/trajectory.yml'
    narrative_path = f'{case}/narrative.md'
    trajectory_file = snapshot(trajectory_path)
    trajectory = yaml.safe_load(trajectory_file.read_text(encoding='utf-8')) if trajectory_file.exists() else {}
    trajectory = trajectory or {}
    history = trajectory.setdefault(request['block'], {}).setdefault('recovery_iterations', [])
    for line, row in enumerate(rows, 1):
        record = dict(row, source=dict(request['iterations_ref'], locator=f'JSONL record {line}'))
        prior = next((r for r in history if (r['question_id'], r['iteration']) == (row['question_id'], row['iteration'])), None)
        if prior and prior != record:
            raise ContractError('cannot overwrite a prior question iteration; append a new iteration')
        if not prior:
            history.append(record)
    write_yaml(trajectory_path, trajectory)
    old_recovery = summary.get('recovery', {})
    if old_recovery.get('update_id') == request['update_id']:
        raise ContractError('update_id already applied; re-apply the original prepared change for a no-op')
    summary['updated'] = request['date']
    summary['recovery'] = dict(update_id=request['update_id'], delivery_status=request['delivery_status'],
                               result=request['result'], evidence_refs=request['evidence_refs'],
                               iterations_ref=request['iterations_ref'], question_iterations=len(history),
                               design_convergence_claimed=False)
    if request.get('bundle_ref'):
        summary['recovery']['bundle_ref'] = request['bundle_ref']
    # Existing result and convergence remain historical, unchanged.
    write_yaml(rel, summary)
    narrative_file = snapshot(narrative_path)
    narrative = narrative_file.read_text(encoding='utf-8') if narrative_file.exists() else f'# Case narrative — {summary["name"]}\n'
    if f' / {request["update_id"]}\n' in narrative:
        raise ContractError('update_id already exists in project history')
    narrative += f'\n## Recovery {request["date"]} / {request["update_id"]}\n\n{request["narrative"].strip()}\n'
    narrative_file.write_text(narrative, encoding='utf-8')
    updated_entries = set()
    for update in request.get('entry_updates', []):
        if set(update) - {'id', 'content_patch', 'metadata_patch', 'index_summary', 'reason', 'deprecate'}:
            raise ContractError('unknown entry update field')
        key = update['id']
        if key in updated_entries:
            raise ContractError('duplicate entry update')
        updated_entries.add(key)
        if key not in entries or entries[key]['type'] not in {'topology', 'strategy', 'corner-lesson', 'anti-pattern'}:
            raise ContractError('entry update must select an existing domain entry')
        if not update.get('reason'):
            raise ContractError('revision requires a reason')
        metadata = update.get('metadata_patch', {})
        if not isinstance(metadata, dict) or set(metadata) - {'name', 'source', 'confidence_note'}:
            raise ContractError('metadata_patch only supports name, source and confidence_note')
        if any(not isinstance(v, str) or not v.strip() for v in metadata.values()):
            raise ContractError('metadata values must be nonempty strings')
        if 'index_summary' in update and (not isinstance(update['index_summary'], str) or not update['index_summary'].strip()):
            raise ContractError('index_summary must be nonempty')
        if 'name' in metadata and 'index_summary' not in update:
            raise ContractError('name revision requires an explicit index_summary')
        path = entries[key]['path']
        snapshot(path)
        data = ops.load_entry(str(stage), path)
        previous = copy.deepcopy(data.get('content', {}))
        data.setdefault('content', {}).update(update.get('content_patch', {}))
        revision = dict(date=request['date'], update_id=request['update_id'],
            reason=update['reason'], previous_content=previous, previous_confidence=data.get('confidence'),
            evidence_refs=request['evidence_refs'], project_ref=project_id)
        if metadata:
            revision['previous_metadata'] = {k: copy.deepcopy(data[k]) for k in metadata if k in data}
            revision['previous_metadata_absent'] = [k for k in metadata if k not in data]
            data.update(metadata)
        if 'index_summary' in update:
            revision['previous_index_entry'] = copy.deepcopy(entries[key])
            entries[key]['summary'] = update['index_summary']
        data.setdefault('revisions', []).append(revision)
        data['updated'] = request['date']
        data['confidence'] = 'deprecated' if data.get('confidence') == 'deprecated' else 'unverified'
        if project_id not in data.setdefault('derived_from', []):
            data['derived_from'].append(project_id)
        write_yaml(path, data)
        if update.get('deprecate'):
            ops.deprecate(str(stage), key)
    for new in request.get('new_entries', []):
        if set(new) - {'type', 'name', 'tags', 'content'} or new.get('type') not in {'topology', 'strategy', 'corner-lesson', 'anti-pattern'}:
            raise ContractError('new_entries only supports domain entries')
        if not new.get('name') or any(c in new['name'] for c in '\\:< >"|?*'.replace(' ', '')):
            raise ContractError('new domain name contains invalid filename characters')
        filename = new['name'].lower().replace(' ', '-').replace('/', '-') + '.yml'
        path = f'{ops.TYPE_TO_DIR[new["type"]]}/{filename}'
        if wiki_path(repo, path).exists() or any(m['path'] == path for m in entries.values()):
            raise ContractError('domain path already exists; use entry_updates')
        snapshot(path)
        ops.save_index(str(stage), entries)
        key = ops.add_entry(str(stage), new['type'], new['name'], new.get('tags', []), new.get('content'))
        entries = ops.load_index(str(stage))
        data = ops.load_entry(str(stage), path)
        data.update(derived_from=[project_id], source=request['evidence_refs'],
                    created=request['date'], updated=request['date'])
        write_yaml(path, data)
    # Keep every untouched index field. No rewrite if the semantic index is identical.
    original_index = ops.load_index(str(inside(repo, 'wiki')))
    if entries != original_index:
        ops.save_index(str(stage), entries)
    existing_edges = [json.loads(line) for line in (stage / 'edges.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()] if (stage / 'edges.jsonl').exists() else []
    updated_edges = set()
    for update in request.get('edge_updates', []):
        required = {'from', 'to', 'rel', 'expected_note', 'note', 'reason'}
        if set(update) != required or any(not isinstance(update[k], str) for k in required):
            raise ContractError('edge update requires endpoints, rel, expected_note, note and reason')
        identity = tuple(update[k] for k in ('from', 'to', 'rel'))
        if identity in updated_edges or not update['note'].strip() or not update['reason'].strip():
            raise ContractError('duplicate or empty edge revision')
        updated_edges.add(identity)
        matches = [e for e in existing_edges if tuple(e[k] for k in ('from', 'to', 'rel')) == identity]
        if len(matches) != 1 or update['from'] not in entries or update['to'] not in entries:
            raise ContractError('edge revision requires exactly one existing edge and indexed endpoints')
        edge = matches[0]
        if edge.get('note', '') != update['expected_note'] or update['note'] == update['expected_note']:
            raise ContractError('edge note changed or revision is a no-op')
        previous_edge = copy.deepcopy({k: v for k, v in edge.items() if k != 'revisions'})
        edge.setdefault('revisions', []).append(dict(date=request['date'], update_id=request['update_id'],
            reason=update['reason'], previous_edge=previous_edge,
            evidence_refs=request['evidence_refs'], project_ref=project_id))
        edge['note'] = update['note']
        edge['status'] = 'historical_revised'
    if updated_edges:
        # Preserve unrelated lines, including historical relation spellings and formatting.
        edge_file = stage / 'edges.jsonl'
        lines = edge_file.read_text(encoding='utf-8').splitlines(keepends=True)
        replacements = {tuple(e[k] for k in ('from', 'to', 'rel')): e for e in existing_edges
                        if tuple(e[k] for k in ('from', 'to', 'rel')) in updated_edges}
        for i, line in enumerate(lines):
            if line.strip():
                edge = json.loads(line)
                identity = tuple(edge[k] for k in ('from', 'to', 'rel'))
                if identity in replacements:
                    lines[i] = json.dumps(replacements[identity], ensure_ascii=False) + '\n'
        edge_file.write_text(''.join(lines), encoding='utf-8')
    for edge in request.get('edges', []):
        if set(edge) - {'from', 'to', 'rel', 'note'} or edge.get('rel') not in ops.VALID_RELATIONS:
            raise ContractError('edge must use the original relation contract')
        if edge.get('from') not in entries or edge.get('to') not in entries:
            raise ContractError('edge endpoint missing from original index')
        prior = next((e for e in existing_edges if all(e[k] == edge[k] for k in ('from', 'to', 'rel'))), None)
        if prior:
            if prior.get('note', '') != edge.get('note', ''):
                raise ContractError('edge already exists with another note; preserve or explicitly revise separately')
            continue
        ops.add_edge(str(stage), edge['from'], edge['rel'], edge['to'], edge.get('note', ''))
        existing_edges.append(edge)
    changes = []
    diff = []
    for i, (path, before) in enumerate(originals.items()):
        candidate = stage / path
        after = candidate.read_bytes() if candidate.exists() else None
        if before == after:
            continue
        backup = out / 'before' / str(i)
        backup.parent.mkdir(exist_ok=True)
        if before is not None:
            backup.write_bytes(before)
        changes.append(dict(path=path, before=sha(before) if before is not None else None,
                            after=sha(after), backup=backup.relative_to(out).as_posix()))
        diff.extend(difflib.unified_diff((before or b'').decode('utf-8').replace('\r\n', '\n').splitlines(True),
                                        after.decode('utf-8').replace('\r\n', '\n').splitlines(True), fromfile=path, tofile=path))
    dump_json(out / 'request.json', request)
    plan = dict(version=1, project_id=project_id, request_sha256=sha((out / 'request.json').read_bytes()),
                changes=changes, guards={p: sha(v) if v is not None else None for p, v in originals.items()},
                bundle_snapshot=bundle_snapshot(repo, request))
    dump_json(out / 'plan.json', plan)
    (out / 'changes.diff').write_text(''.join(diff), encoding='utf-8')
    return {'project_id': project_id, 'changed_files': len(changes), 'plan': str(out / 'plan.json')}


def _load_plan(repo, out):
    repo = Path(repo).resolve()
    out = inside(repo, out)
    if out.is_relative_to(inside(repo, 'wiki')):
        raise ContractError('plan must be outside wiki')
    plan = read_json(out / 'plan.json')
    if sha((out / 'request.json').read_bytes()) != plan['request_sha256']:
        raise ContractError('prepared request changed')
    for item in plan['changes']:
        wiki_path(repo, item['path'])
        if sha(inside(out / 'candidate', item['path']).read_bytes()) != item['after']:
            raise ContractError('prepared candidate changed')
        if item['before'] is not None and sha(inside(out, item['backup']).read_bytes()) != item['before']:
            raise ContractError('backup changed')
    return repo, out, plan


def _current(repo, path):
    p = wiki_path(repo, path)
    return sha(p.read_bytes()) if p.exists() else None


def recover(repo, out):
    """Restore only this transaction's files; refuse to undo another editor's work."""
    repo, out, plan = _load_plan(repo, out)
    lock = inside(repo, 'wiki/.recovery-write.lock')
    if not lock.exists() or Path(read_json(lock)['plan']).resolve() != out:
        raise ContractError('no matching unfinished transaction')
    for item in plan['changes']:
        if _current(repo, item['path']) not in (item['before'], item['after']):
            raise ContractError('concurrent change detected; manual recovery required')
    for item in reversed(plan['changes']):
        live = wiki_path(repo, item['path'])
        if item['before'] is None:
            live.unlink(missing_ok=True)
        else:
            atomic_write(live, inside(out, item['backup']).read_bytes())
    dump_json(out / 'receipt.json', {'status': 'rolled_back'})
    lock.unlink()
    return {'status': 'rolled_back'}


def apply(repo, out):
    repo, out, plan = _load_plan(repo, out)
    _validate_request(repo, read_json(out / 'request.json'))
    if bundle_snapshot(repo, read_json(out / 'request.json')) != plan['bundle_snapshot']:
        raise ContractError('evidence bundle changed after prepare; review the new version')
    lock = inside(repo, 'wiki/.recovery-write.lock')
    if lock.exists():
        raise ContractError('unfinished/concurrent recovery write; inspect then recover the recorded plan')
    after = {item['path']: item['after'] for item in plan['changes']}
    if all(_current(repo, p) == after.get(p, h) for p, h in plan['guards'].items()):
        return {'status': 'no-op', 'project_id': plan['project_id']}
    with lock.open('x', encoding='utf-8') as handle:
        json.dump({'plan': str(out)}, handle)
    started = False
    try:
        if any(_current(repo, p) != h for p, h in plan['guards'].items()):
            raise ContractError('wiki changed since prepare; prepare a new diff')
        started = True
        # Data before metadata. A hard interruption leaves the recovery lock.
        order = sorted(plan['changes'], key=lambda i: i['path'] in {'index.yml', 'edges.jsonl'})
        for item in order:
            live = wiki_path(repo, item['path'])
            live.parent.mkdir(parents=True, exist_ok=True)
            atomic_write(live, inside(out / 'candidate', item['path']).read_bytes())
        if any(_current(repo, p) != h for p, h in after.items()):
            raise ContractError('post-write hash mismatch')
        dump_json(out / 'receipt.json', {'status': 'applied', 'project_id': plan['project_id'], 'files': after})
    except BaseException:
        if started:
            recover(repo, out)
        else:
            lock.unlink()
        raise
    lock.unlink()
    return {'status': 'applied', 'project_id': plan['project_id'], 'changed_files': len(after)}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--repo', required=True, type=Path)
    sub = ap.add_subparsers(dest='command', required=True)
    prep = sub.add_parser('prepare')
    prep.add_argument('request', type=Path)
    prep.add_argument('--out', required=True, type=Path)
    for name in ('apply', 'recover'):
        sub.add_parser(name).add_argument('plan_dir', type=Path)
    sub.add_parser('audit-index')
    args = ap.parse_args()
    try:
        if args.command == 'prepare':
            result = prepare(args.repo, read_json(inside(args.repo, args.request)), args.out)
        elif args.command == 'audit-index':
            result = audit_index(args.repo)
        else:
            result = globals()[args.command](args.repo, args.plan_dir)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({'valid': False, 'error': str(exc)}, ensure_ascii=False))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
