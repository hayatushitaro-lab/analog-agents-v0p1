# Fixed-DUT recovery review

This is the recovery execution branch of analog-evolve. The root agent can execute
it directly; reading this file or resolving a plan alone is not execution. Do not
start agents, simulations or external reviews just to call this skill.

## When and what to read

Run at recovery S7 after evidence, review decisions and report checks are stable.
Partial delivery and failed diagnostics are useful inputs; design convergence is
not required. A later correction reopens only affected proposals.

Consume `workflow.resolved.json.closeout.evolution`: standard covers lessons and
anti-patterns, intensive adds strategies/checklist proposals, exhaustive adds prompt
proposals and retrospective. Lite has no automatic requirement; an explicit user
request still triggers the requested review. Do not inherit forward sizing/specs.

Read the current run's recovery-iterations, coverage/stop decision, evidence manifest,
review findings, actual run/resource summaries, report QA and user feedback as needed.
Follow specific evidence references for errors, corrections and unresolved conflicts.
Consult related entries through the existing wiki interface and same-circuit project
identity; do not load the whole historical workspace. Missing inputs limit the review
and must be recorded, not reported as “zero useful lessons”.

## Do the review

1. Identify events that changed an explanation, invalidated evidence, repaired a
   measurement or exposed a reporting/coverage failure. Separate circuit facts from
   process lessons. Report completion alone does not validate the circuit.
2. For each useful event, state the previous belief, supporting/refuting evidence,
   corrected conclusion, applicability and remaining uncertainty. Locate sources by
   existing artifact IDs/paths and positions; reuse the manifest's version/hash.
3. Compare with related wiki entries: new, duplicate/supporting, narrower, or
   contradicting. Record the consulted IDs and why to retain, revise or omit a
   candidate. A single failed attempt does not establish a universal rule.
4. Produce `evolution-proposals.md` with the review scope and decisions. Each retained
   candidate carries its evidence, applicability, existing-entry relationship and
   actual review status. If no candidates remain, explain the events considered and
   deduplication outcome. Missing review evidence is a limitation, not approval.
5. Return candidates to the root for the existing recovery wiki prepare/diff/apply/
   readback sequence. Prepare the same-project case even when there is no generalized
   knowledge. Checklist/skill/prompt changes remain separate proposals unless the
   user has explicitly authorized those edits.

## Execution record and backend boundary

Use the existing `delivery-status.json` (or current closeout record) for a small
`evolution` object. The following is its minimal convention, not an engine command:

```json
{
  "skill": "analog-evolve",
  "mode": "recovery",
  "status": "completed",
  "engine_execution": "not_run",
  "reason": "Recovery review executed by the agent; the forward engine does not consume native recovery inputs.",
  "inputs": ["relative/path/to/recovery-iterations.jsonl"],
  "output": "relative/path/to/evolution-proposals.md",
  "candidate_count": 0,
  "limitations": []
}
```

Replace example paths and values with actual records. `status` is pending,
completed, partial, blocked or not_required_by_effort. Completed means the declared
review was performed, not that candidates were accepted or written. If the run has
an existing manifest, reference it in inputs; record the actually read skill path
and version/hash in the proposal or existing method record. Do not fabricate an
independent reviewer. Candidate approval/application stays in the wiki change plan
and receipt, separate from this skill status and report delivery.

`tools/evolve_engine.py` currently consumes forward artifacts. Do not fabricate
sizing iterations, rename recovery JSONL to iteration-log, or feed a verifier's
incidental forward-shaped log as the recovery trajectory. Execute this review in
the agent and record `engine_execution=not_run`; no engine rewrite is required.

## Same wiki and reversible conclusions

Use [recovery wiki writeback](../../analog-recovery/references/wiki-writeback.md).
Keep the original index and project identity; preserve historical convergence and
old conclusions with their evidence. New or revised knowledge remains unverified
unless separately justified and authorized. Repeated runs of the same project or
agreement between agents are not independent project validation. All wiki mutations,
including confidence changes, obey the current write policy; the forward automatic
confidence exception does not apply here. A contradiction needs a scoped revision
or retraction, not just an additional favorable entry.
