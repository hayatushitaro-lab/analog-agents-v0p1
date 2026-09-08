---
name: analog-document-generator
description: Generate Chinese analog IC design documents from PDK model files, CDL/SCS netlists, design notes, and verification reports while preserving the supplied Word templates and separating confirmed facts from inference and missing inputs.
---

# Analog document generator

Use this skill when the user wants the supplied analog design Word templates filled from circuit artifacts such as PDK model files, CDL/SCS netlists, design rationale, simulation reports, or layout verification reports.

This skill is a document-generation workflow, not a circuit-design substitute. It may describe topology-derived behavior, but it must not invent system requirements, simulation results, layout results, or process data that are absent from the inputs.

## Inputs

At minimum, accept:

- the two retained Word templates: the startup/process template and the module design template;
- one CDL or Spectre SCS netlist;
- a PDK model file or model include reference.

Use optional evidence when available:

- `spec.yml`, architecture/rationale notes, verification plans;
- simulation logs, waveforms, PSF-derived summaries, Monte Carlo results;
- DRC/LVS/PEX reports and layout notes;
- user-provided system requirements and interface definitions.

If a normalized facts JSON already exists, validate it first with `scripts/validate_facts.py` and use it as the document input. Its field-result contract is documented in [template-schema.md](references/template-schema.md).

## Evidence states

Every material filled value must be classified internally as one of:

- `confirmed`: directly present in an input artifact;
- `confirmed_from_previous_run`: confirmed by an earlier run, but not rechecked in the current environment;
- `inferred`: derived from topology or model structure and clearly presented as an inference;
- `required_input`: cannot be determined from current inputs; write `待补充` and record a question;
- `not_applicable`: does not apply to this module, with a reason.

Do not turn `inferred` or `required_input` into a definitive numeric result. A model include path is not proof of metal stack, mask count, MIM/MOM density, or HR-poly sheet resistance unless those data are actually present.

## Workflow

1. Preserve the retained templates. Work on copies only.
2. Extract the netlist facts: subcircuit name, ordered pins, instances, model names, W/L/nf or equivalent parameters, passive values, supplies, and internal nodes.
3. Extract the PDK facts: model file path, available sections, device model names, and process parameters only where explicitly present.
4. Extract design and verification evidence. Keep specification targets separate from measured results.
5. Validate cross-artifact consistency: instance count, model names, pin order, compensation values, corner names, units, and reported result values.
6. Populate the two templates. Remove blue/italic instructional paragraphs from the final copies, preserve headings/table structure, and write `待补充` for unsupported fields.
7. Generate an evidence/mapping report alongside the documents. It must list unresolved fields and source paths.
8. Render both final `.docx` files to page PNGs and inspect every page. Iterate if text clips, tables overflow, instructions remain, or layout moves outside intended slots.

## Standard result

For a normal run, produce:

- a filled startup/process `.docx`;
- a filled module design `.docx`;
- a machine-readable facts/mapping JSON;
- a short mapping report with unresolved questions;
- render QA artifacts kept in the task work directory, not presented as the final documents unless requested.

Use `scripts/generate_documents.py` for deterministic filling of the current two templates. Use `scripts/validate_facts.py` before generation and after any change to the facts JSON.

## Important boundaries

- A CDL/SCS netlist can establish connectivity and device parameters; it normally cannot establish system application, requirements, CMRR/PSRR, mismatch, noise, settling, layout, or DRC/LVS results.
- A simulation report can establish only the analyses and corners it actually contains. Do not fill unperformed Monte Carlo, post-layout, or noise sections with typical values.
- For a single-ended OTA, do not label a unity-feedback output error as CMRR or output common-mode error unless the evidence defines that metric explicitly.
- Keep PDK paths and remote confirmation timestamps in the evidence report. If the remote VM is unavailable, retain the last known status as `confirmed_from_previous_run`.
