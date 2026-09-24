"""Read an existing static IR into a scope-qualified local connection packet.

No raw-netlist parsing, model interpretation, or same-name net merging.
"""
import argparse
import hashlib
import json
from pathlib import Path


def one(rows, label):
    if len(rows) != 1:
        raise ValueError(f'{label}: expected one match, found {len(rows)}')
    return rows[0]


def complete_ancestry(ir, occurrence):
    """Do not export resolved identities through an incomplete ancestor."""
    seen = set()
    while occurrence is not None:
        if occurrence['id'] in seen or occurrence['status'] != 'complete':
            return False
        seen.add(occurrence['id'])
        parent = occurrence.get('parent_ref')
        if parent is None:
            return True
        matches = [o for o in ir['occurrences'] if o['id'] == parent]
        if len(matches) != 1:
            return False
        occurrence = matches[0]
    return False


def master_definition(ir, occ, inst, children):
    """Resolve a declaration within the instance's admitted source view.

    Comparison artifacts are separate namespaces, not include libraries. Check
    any elaborated child reference against the same source-qualified lookup;
    neither array order nor a foreign same-named definition breaks a tie.
    """
    master = inst.get('master_ref_or_name')
    if master is None:
        return None
    owner = one([d for d in ir['definitions'] if d['id'] == occ['definition_ref']],
                'instance owner definition')
    aid = inst.get('artifact_ref', owner.get('artifact_ref'))
    if aid is not None and owner.get('artifact_ref', aid) != aid:
        raise ValueError('instance and owner source mismatch')
    available = [d for d in ir['definitions'] if aid is None or d.get('artifact_ref') == aid]
    exact = [d for d in available if d['id'] == master]
    candidates = exact or [d for d in available if master in (d.get('raw_name'), d.get('canonical_name'))]
    definition = one(candidates, 'source-qualified master definition') if candidates else None
    if len(children) > 1:
        raise ValueError('instance occurrence: expected at most one child')
    if children and children[0].get('definition_ref') is not None:
        ref = children[0]['definition_ref']
        if definition is None or ref != definition['id']:
            raise ValueError('child definition reference disagrees with instance source/master')
    return definition


def named_terminals(ir, occ, inst, contracts, resolved_allowed):
    """Use declared subckt order or explicitly supplied device metadata only.

    Metadata references are provenance declarations, not model verification.
    Width semantics are intentionally outside this terminal-only contract.
    """
    master = inst.get('master_ref_or_name')
    children = [o for o in ir['occurrences'] if o.get('parent_ref') == occ['id'] and
                o.get('instance_ref') == inst['id']]
    definition = master_definition(ir, occ, inst, children)
    terms = inst['ordered_terminals']
    if definition is not None:
        names = [p['raw_name'] for p in definition['formal_ports']]
        refs = definition.get('span_refs', [])
        semantics = 'subckt_formal_order'
    elif master in contracts:
        metadata = contracts[master]
        if not isinstance(metadata, dict):
            raise ValueError('terminal contract must be an object')
        names = metadata.get('terminal_order')
        refs = metadata.get('source_refs')
        semantics = 'supplied_terminal_contract'
    else:
        return [], 'UNKNOWN', []
    if (not isinstance(names, list) or len(names) != len(terms) or
            any(not isinstance(n, str) or not n.strip() for n in names) or
            len(set(names)) != len(names)):
        raise ValueError('terminal contract order/arity invalid')
    if (not isinstance(refs, list) or not refs or
            any(not isinstance(r, str) or not r.strip() for r in refs)):
        raise ValueError('terminal contract needs source references')
    bindings = []
    if resolved_allowed and len(children) == 1:
        child = children[0]
        if child['status'] in ('complete', 'opaque_model'):
            bindings = child.get('port_bindings') or child.get('terminal_bindings', [])
    rows = []
    for name, term in zip(names, terms):
        matches = [b for b in bindings if b['ordinal'] == term['ordinal'] and
                   b.get('source_net_ref') == term['net_ref']]
        rows.append({'name': name, 'ordinal': term['ordinal'],
                     'actual_name': term.get('raw_name', term.get('canonical_name')),
                     'net_ref': term['net_ref'],
                     'resolved_net': matches[0]['resolved_net'] if len(matches) == 1 else None})
    return rows, semantics, refs


def make_packet(ir, occurrence, net, terminal_contracts=None):
    contracts = terminal_contracts if terminal_contracts is not None else {}
    if not isinstance(contracts, dict):
        raise ValueError('terminal contracts must be a master-name mapping')
    occ = one([o for o in ir['occurrences'] if occurrence in (o['id'], o['instance_path'])], 'occurrence')
    local_only = not complete_ancestry(ir, occ)
    definition = one([d for d in ir['definitions'] if d['id'] == occ['definition_ref']], 'definition')
    selected = one([n for n in ir['nets'] if n['scope_ref'] == definition['id'] and
                    net in (n['id'], n.get('raw_name'), n.get('canonical_name'))], 'scoped net')
    nr = selected['id']
    spans = {s['id']: s for s in ir.get('source_spans', [])}
    connections = []
    for inst in ir['instances']:
        if inst['definition_scope_ref'] != definition['id']:
            continue
        matched = [t['ordinal'] for t in inst['ordered_terminals'] if t['net_ref'] == nr]
        if not matched:
            continue
        named, semantics, semantic_refs = named_terminals(ir, occ, inst, contracts, not local_only)
        connections.append({
            'instance_ref': inst['id'],
            'instance_path': occ['instance_path'].rstrip('/') + '/' + inst['raw_name'],
            'master': inst.get('master_ref_or_name'),
            'selected_terminal_ordinals': matched,
            'ordered_terminals': inst['ordered_terminals'],
            'named_terminals': named, 'terminal_semantics': semantics,
            'terminal_source_refs': semantic_refs, 'width_semantics': 'UNKNOWN',
            'parameters': [{k: p.get(k) for k in ('raw_key', 'raw_expr', 'normalized_value', 'semantic_status')}
                           for p in inst.get('parameters', [])],
            'span_refs': inst.get('span_refs', []),
            'source_locations': [spans[s] for s in inst.get('span_refs', []) if s in spans],
        })
    boundaries = []
    for b in occ.get('port_bindings', []):
        if b.get('formal_net_ref') == nr:
            boundaries.append({'direction': 'parent_or_root', 'occurrence_ref': occ['id'], 'binding': b})
    for child in ir['occurrences']:
        if child.get('parent_ref') != occ['id']:
            continue
        for b in child.get('port_bindings', []):
            if b.get('source_net_ref') == nr:
                boundaries.append({'direction': 'child', 'occurrence_ref': child['id'],
                                   'status': child.get('status', 'UNKNOWN'), 'binding': b})
    other = []
    for n in ir['nets']:
        if n['id'] != nr and n.get('canonical_name') == selected.get('canonical_name'):
            other.append({'definition_ref': n['scope_ref'], 'net_ref': n['id'],
                          'note': 'Same spelling only; not an electrical connection.'})
    if local_only:
        boundaries = []
    return {
        'local_only': local_only, 'occurrence_status': occ['status'],
        'selected': {'occurrence_ref': occ['id'], 'instance_path': occ['instance_path'],
                     'definition_ref': definition['id'], 'net_ref': nr},
        'connections': connections, 'boundaries': boundaries, 'other_same_named_nets': other,
        'limits': ['Definition-scoped local view at the selected occurrence; not a flattened circuit.',
                   'Incomplete occurrence permits local facts only; boundary links are withheld.',
                   'Cross-hierarchy links require explicit binding records; child status may be incomplete.',
                   'Device role, effective parameters and operating-point validity require separate evidence.'],
    }


def compact_packet(packet):
    """Group identical connectivity/parameter records; preserve every member ID.

    Grouping is representational only, never an electrical multiplicity calculation.
    """
    groups = {}
    for row in packet['connections']:
        semantic = {k: row.get(k) for k in ('named_terminals', 'terminal_semantics',
                                           'terminal_source_refs', 'width_semantics')}
        signature = json.dumps([row['master'], row['ordered_terminals'], row['parameters'], semantic], sort_keys=True)
        if signature not in groups:
            groups[signature] = {
                'master': row['master'], 'ordered_terminals': row['ordered_terminals'],
                'parameters': row['parameters'], 'members': [],
                **semantic,
                'note': 'Identical local connectivity and raw parameter records; not effective electrical multiplier.',
            }
        groups[signature]['members'].append({
            'instance_ref': row['instance_ref'], 'instance_path': row['instance_path'],
            'span_refs': row['span_refs'],
            'source_locations': row.get('source_locations', []),
        })
    out = {k: v for k, v in packet.items() if k != 'connections'}
    out['connection_groups'] = list(groups.values())
    out['connection_count'] = len(packet['connections'])
    if 'target_context' in out:
        out['target_context'] = compact_packet(out['target_context'])
    return out


def make_target_packet(ir, occurrence, net, target_net, terminal_contracts=None):
    """Pair two local endpoint views; incidence is never a conductive edge.

    Reuse the existing qualified projection for both endpoints. This deliberately
    does not flatten hierarchy, traverse components or infer controllability.
    """
    packet = make_packet(ir, occurrence, net, terminal_contracts)
    target = make_packet(ir, occurrence, target_net, terminal_contracts)
    same = packet['selected']['net_ref'] == target['selected']['net_ref']
    left = {row['instance_ref'] for row in packet['connections']}
    right = {row['instance_ref'] for row in target['connections']}
    packet['target_context'] = target
    packet['connection_assessment'] = {
        'scope': 'selected_definition_at_occurrence',
        'direct_local_net': 'same' if same else 'distinct',
        # Same-node incidence would falsely look like a between-node component.
        'shared_component_refs': [] if same else sorted(left & right),
        'component_relation': 'terminal_incidence_only',
        'hierarchy_links_available': not packet['local_only'],
        'global_device_path': 'NOT_EVALUATED',
        'effective_control': 'NOT_EVALUATED',
        'limits': [
            'Distinct local nets do not prove absence of a device-mediated path.',
            'A shared component may be a source, subcircuit or unknown device; '
            'terminal incidence does not imply conduction, direction or control.',
            'No shared component does not exclude multi-component or hierarchical paths.',
            'Use endpoint named_terminals as the binding projection; follow source '
            'locations for component meaning and retain unresolved boundaries.',
        ],
    }
    return packet


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('ir', type=Path)
    ap.add_argument('--occurrence', required=True)
    ap.add_argument('--net', required=True)
    ap.add_argument('--target-net', help='pair a target net in the same definition; no device-path inference')
    ap.add_argument('--full', action='store_true', help='emit all individual records and source locations')
    ap.add_argument('--out', type=Path, help='write a new UTF-8 JSON file directly; never overwrite')
    ap.add_argument('--terminal-contracts', type=Path,
                    help='admitted master -> terminal_order/source_refs metadata; no width conversion')
    a = ap.parse_args()
    try:
        raw = a.ir.read_bytes()
        contract_raw = a.terminal_contracts.read_bytes() if a.terminal_contracts else None
        contracts = json.loads(contract_raw.decode('utf-8-sig')) if contract_raw is not None else None
        ir = json.loads(raw.decode('utf-8-sig'))
        packet = (make_target_packet(ir, a.occurrence, a.net, a.target_net, contracts)
                  if a.target_net is not None else make_packet(ir, a.occurrence, a.net, contracts))
        if not a.full:
            packet = compact_packet(packet)
        packet['source'] = {'path': str(a.ir.resolve()), 'sha256': hashlib.sha256(raw).hexdigest()}
        if contract_raw is not None:
            packet['terminal_contract_source'] = {'path': str(a.terminal_contracts.resolve()),
                                                  'sha256': hashlib.sha256(contract_raw).hexdigest()}
        if a.out is not None:
            with a.out.open('x', encoding='utf-8') as output:
                output.write(json.dumps(packet, ensure_ascii=False, indent=2) + '\n')
        # ASCII JSON is lossless even across mismatched native-process shell
        # encodings; consumers recover the original Unicode strings via JSON.
        print(json.dumps(packet, ensure_ascii=True, indent=2))
        return 0
    except (ValueError, KeyError, TypeError, OSError) as exc:
        print(json.dumps({'valid': False, 'error': str(exc)}, ensure_ascii=True))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
