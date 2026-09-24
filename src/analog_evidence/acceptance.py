"""Primary-source static acceptance, separate from IR validity and auxiliary quality."""


def source_status(ir):
    result=[]
    for view in ir['views']:
        aid=view['artifact_ref']
        # IDs and provenance scopes are artifact-qualified by the parser.
        errors=[d for d in ir['diagnostics'] if d['severity']=='error' and
                (d['id'].startswith(aid+':') or any(
                    ref==aid or ref.startswith(aid+':')
                    for ref in d['affected_scope_refs']))]
        roots=[o for o in ir['occurrences'] if o['role']=='dut' and o['id'].startswith(aid+':')]
        syntax='partial' if view['status']!='complete' or any(d['stage']=='syntax' for d in errors) else 'complete'
        result.append({'artifact_ref':aid,'role':'primary' if aid==ir['scope']['structural_baseline_ref'] else 'auxiliary',
                       'syntax':syntax,'design_elaboration':'complete' if syntax=='complete' and roots and not errors else 'partial',
                       'error_diagnostic_refs':[d['id'] for d in errors]})
    return result


def comparison_coverage(ir):
    result=[]
    primary=ir['scope']['structural_baseline_ref']
    def design_instances(aid):
        return {i['id'] for i in ir['instances'] if i['artifact_ref']==aid and i['definition_scope_ref']!=aid+':harness'}
    for aid in ir['scope']['comparison_refs']:
        rows=[c for c in ir['comparisons'] if any(x.startswith(aid+':') for x in c['left_refs']+c['right_refs'])
              or c['id'].startswith('comparison:'+primary+':'+aid+':')]
        covered={x for c in rows if c['comparison_scope']=='instance_parameters' for x in c['left_refs']+c['right_refs']}
        result.append({'artifact_ref':aid,
                       'uncompared_primary_instance_refs':sorted(design_instances(primary)-covered),
                       'uncompared_auxiliary_instance_refs':sorted(design_instances(aid)-covered),
                       'unmatched_comparison_refs':[c['id'] for c in rows if c['status']=='unmatched'],
                       'meaning':'Record coverage of parsed design instances only; unsupported statements excluded; no electrical equivalence.'})
    return result


def policy_fields(ir):
    statuses=source_status(ir);primary=next(s for s in statuses if s['role']=='primary')
    coverage=comparison_coverage(ir)
    partial=any(s['design_elaboration']!='complete' for s in statuses if s['role']=='auxiliary') or any(
        c['uncompared_primary_instance_refs'] or c['uncompared_auxiliary_instance_refs'] or c['unmatched_comparison_refs'] for c in coverage)
    return {'source_policy':'primary_required_auxiliary_optional',
            'source_statuses':statuses,'comparison_coverage':coverage,
            'auxiliary_status':'not_requested' if not coverage else ('partial' if partial else 'available'),
            'stages':{'syntax':primary['syntax'],'design_elaboration':primary['design_elaboration'],
                      'model_binding':'partial','simulation':'not_run','report':'not_run'}}


def acceptance(ir, validation_errors):
    primary=next(s for s in source_status(ir) if s['role']=='primary')
    passed=not validation_errors and primary['syntax']=='complete' and primary['design_elaboration']=='complete'
    return {'status':'invalid_evidence' if validation_errors else ('passed_static' if passed else 'blocked_primary'),
            'accepted':passed,'scope':'primary_source_static_structure_only',
            'primary_artifact_ref':primary['artifact_ref'],
            'auxiliary_status':policy_fields(ir)['auxiliary_status'],
            'model_binding_verified':False,'electrical_performance_verified':False}
