"""Read an analog-agents wiki selectively using its existing load functions.

Use the analog-agents repository Python environment. No archive/add/evolve writes.
Query reads index metadata only. --projects admits explicit project continuation;
documents and evidence are selected separately, never recursively loaded.
"""
import argparse
import hashlib
import importlib.util
import json
from itertools import islice
from pathlib import Path

DOMAIN_DIRS = {'topologies', 'strategies', 'corner-lessons', 'anti-patterns'}


def inside(root, path):
    candidate = (root / path).resolve()
    try:
        relative = candidate.relative_to(root.resolve())
    except ValueError:
        raise ValueError('path escapes workspace/wiki root')
    return candidate


def allowed_path(root, path, projects=False):
    candidate = inside(root, path)
    relative = candidate.relative_to(root.resolve())
    dirs = DOMAIN_DIRS | ({'projects'} if projects else set())
    if not relative.parts or relative.parts[0] not in dirs or candidate.suffix != '.yml':
        raise ValueError('only domain entries are admitted; project narratives require separate access')
    return candidate


def file_hash(path):
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(65536), b''):
            digest.update(block)
    return digest.hexdigest()


def excerpt(path, start=1, count=100, max_bytes=16384):
    if start < 1 or not 1 <= count <= 500:
        raise ValueError('start must be positive; line count must be 1..500')
    if not path.exists():
        return {'path': str(path), 'status': 'missing', 'content_loaded': False}
    with path.open(encoding='utf-8') as handle:
        lines = list(islice(handle, start - 1, start - 1 + count))
    text = ''.join(lines)
    if len(text.encode('utf-8')) > max_bytes:
        raise ValueError('excerpt exceeds budget; request fewer lines')
    return {'path': str(path), 'sha256': file_hash(path), 'start_line': start,
            'line_count': len(lines), 'text': text, 'status': 'available'}


def packet(repo, query=None, entry=None, excludes=(), limit=8, max_bytes=16384,
           projects=False, audit=False, document=None, start=1, count=100):
    repo = repo.resolve()
    root = inside(repo, 'wiki')
    spec = importlib.util.spec_from_file_location('recovery_external_wiki_ops', inside(repo, 'tools/wiki_ops.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    inside(root, 'index.yml')
    entries = module.load_index(str(root))
    def blocked(key, meta):
        text = key + ' ' + json.dumps(meta, ensure_ascii=False)
        return any(term.casefold() in text.casefold() for term in excludes)
    if entry is not None:
        if entry not in entries or blocked(entry, entries[entry]):
            raise ValueError('entry absent or excluded')
        meta = entries[entry]
        path = allowed_path(root, meta['path'], projects)
        if path.stat().st_size > max_bytes:
            raise ValueError('entry exceeds reading budget; inspect a bounded excerpt separately')
        data = module.load_entry(str(root), meta['path'])
        if any(term.casefold() in json.dumps(data, ensure_ascii=False, default=str).casefold() for term in excludes):
            raise ValueError('entry body/source matches exclusion; adapter inspected it but will not emit its content')
        if data.get('confidence') == 'deprecated' and not audit:
            raise ValueError('deprecated entry is not admitted as active knowledge')
        result = {'id': entry, 'path': str(path), 'sha256': file_hash(path),
                  'entry': data, 'use': 'Historical reference; check evidence, conditions and revision scope before inheriting.'}
        if document:
            legacy_project = (meta.get('type') == 'project' and path.name == 'summary.yml'
                              and data.get('proj-index') == entry
                              and ('id' not in data or data['id'] == entry)
                              and ('type' not in data or data['type'] == 'project'))
            canonical_project = (data.get('type') == 'project'
                                 and ('id' not in data or data['id'] == entry)
                                 and ('proj-index' not in data or data['proj-index'] == entry))
            if not projects or not (canonical_project or legacy_project) or document not in {'narrative', 'trajectory'}:
                raise ValueError('document requires an explicitly admitted project')
            docpath = inside(root, str(path.parent / (document + ('.md' if document == 'narrative' else '.yml'))))
            result['document'] = excerpt(docpath, start, count, max_bytes)
            if any(term.casefold() in result['document'].get('text', '').casefold() for term in excludes):
                raise ValueError('document matches exclusion; content withheld')
        links = []
        for key in ('derived_from', 'supersedes_context'):
            refs = data.get(key, [])
            for ref in ([refs] if isinstance(refs, str) else refs):
                links.append({'from': entry, 'to': ref, 'rel': key})
        edge_path = inside(root, 'edges.jsonl')
        if edge_path.exists():
            with edge_path.open(encoding='utf-8') as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    edge = json.loads(line)
                    if entry in (edge.get('from'), edge.get('to')):
                        links.append(edge)
        eligible = []
        for link in links:
            other = link['to'] if link['from'] == entry else link['from']
            if other not in entries or blocked(other, entries[other]):
                continue
            try:
                allowed_path(root, entries[other]['path'], projects)
            except ValueError:
                continue
            if link not in eligible:
                eligible.append(link)
        result['related'] = eligible[:limit]
        result['related_total'] = len(eligible)
        result['related_content_loaded'] = False
        result['warnings'] = []
        if data.get('confidence') not in (None, 'unverified', 'verified', 'deprecated'):
            result['warnings'].append('legacy confidence value; not promoted to verified')
        return result
    matches = []
    for key, meta in entries.items():
        if blocked(key, meta):
            continue
        try:
            allowed_path(root, meta['path'], projects)
        except ValueError:
            continue
        if query.casefold() in (key + ' ' + str(meta.get('summary', ''))).casefold():
            matches.append({'id': key, **meta})
    return {'matches': matches[:limit], 'total_matches': len(matches), 'content_loaded': False,
            'note': 'Index-only search; tags inside bodies not searched. Confidence/source require explicit entry read.'}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--repo', required=True, type=Path)
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument('--query')
    group.add_argument('--entry')
    ap.add_argument('--exclude', action='append', default=[])
    ap.add_argument('--projects', action='store_true', help='admit selected project and block-case YAML')
    ap.add_argument('--audit', action='store_true', help='include deprecated entry for revision audit only')
    ap.add_argument('--document', choices=['narrative', 'trajectory'])
    ap.add_argument('--start-line', type=int, default=1)
    ap.add_argument('--line-count', type=int, default=100)
    a = ap.parse_args()
    try:
        if a.document and not a.entry:
            raise ValueError('--document requires --entry')
        print(json.dumps(packet(a.repo, a.query, a.entry, a.exclude, projects=a.projects,
                                audit=a.audit, document=a.document, start=a.start_line,
                                count=a.line_count), ensure_ascii=False, indent=2, default=str))
        return 0
    except (OSError, ValueError, KeyError, TypeError, ImportError) as exc:
        print(json.dumps({'valid': False, 'error': str(exc)}, ensure_ascii=False))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
