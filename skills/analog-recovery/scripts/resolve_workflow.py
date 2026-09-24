"""Resolve a bounded analog-recovery workflow configuration.

This module deliberately only parses configuration and emits a dispatch plan.
It never starts agents, schedules work, or runs a simulation.
"""

from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Mapping


class WorkflowConfigError(ValueError):
    """Raised when a workflow configuration does not satisfy its schema."""


class UnsupportedBehavioralError(WorkflowConfigError):
    """Raised for the unimplemented ``behavioral: on`` branch."""


_EFFORTS = {
    "lite": {
        "description": "最小可验收闭环，优先覆盖核心问题。",
        "coverage_strategy": "core_closed_loop",
    },
    "standard": {
        "description": "按默认任务顺序覆盖核心指标并保留独立复核。",
        "coverage_strategy": "default_core_and_review",
    },
    "intensive": {
        "description": "扩大适用条件与模式覆盖，并对关键缺口做定向复核。",
        "coverage_strategy": "expanded_conditions_and_targeted_review",
    },
    "exhaustive": {
        "description": "在声明资源内系统检查所有已登记问题，未覆盖项明确保留，不保证穷尽验证",
        "coverage_strategy": "systematic_declared_issue_review",
    },
}
# Recovery policies borrow the forward effort dimensions, not its specifications,
# sizing loop, convergence flags, or unlimited optimizer budget.
_POLICIES = {
    "lite": dict(analysis="core_paths_and_assumptions", pre_sim="structural_and_electrical_safety",
                 verification="declared_main_condition", reviewers=1, revision_limit=2,
                 remote_seconds=900, concurrency=1, review_calls=3, review_rounds=1,
                 archive=False, evolution=[], report="core_explanation_and_gaps"),
    "standard": dict(analysis="main_modes_bias_ratios_and_feedback", pre_sim="structural_estimate_and_fixture_semantics",
                     verification="main_condition_and_declared_boundary_cases", reviewers=1, revision_limit=3,
                     remote_seconds=3600, concurrency=2, review_calls=6, review_rounds=2,
                     archive=True, evolution=["lessons", "anti_patterns"], report="main_modes_and_metrics"),
    "intensive": dict(analysis="competing_explanations_and_cross_block_effects", pre_sim="all_applicable_checks",
                      verification="expanded_process_supply_temperature_and_diagnostics", reviewers=2, revision_limit=5,
                      remote_seconds=7200, concurrency=3, review_calls=12, review_rounds=3,
                      archive=True, evolution=["lessons", "anti_patterns", "strategies", "checklist_proposals"],
                      report="tradeoffs_boundaries_and_conflicts"),
    "exhaustive": dict(analysis="systematic_remaining_questions_and_sensitivity", pre_sim="all_applicable_checks_with_gate_record",
                       verification="declared_full_pvt_and_model_supported_mismatch", reviewers="all", revision_limit=8,
                       remote_seconds=14400, concurrency=4, review_calls=12, review_rounds=3,
                       archive=True, evolution=["lessons", "anti_patterns", "strategies", "checklist_proposals",
                                                "prompt_proposals", "retrospective"], report="full_declared_scope_and_retrospective"),
}
_ENUMS = {
    "workflow_effort": frozenset(_EFFORTS),
    "behavioral": frozenset({"auto", "on", "off"}),
    "module_scale": frozenset({"small", "large"}),
    "mode": frozenset({"replay", "live"}),
}
_ROOT_FIELDS = frozenset(
    {
        "workflow_effort",
        "behavioral",
        "module_scale",
        "mode",
        "resources",
        "simulation_authorized",
        "repository_root",
        "subagent_model",
        "reasoning_effort",
        "site_config",
        "external_review_authorized",
        "knowledge_write_policy",
        "single_agent",
    }
)
_RESOURCE_FIELDS = frozenset({"remote_seconds", "max_concurrent_runs"})


def _type_name(value: Any) -> str:
    return type(value).__name__


def _require_mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise WorkflowConfigError(f"{name} must be an object, got {_type_name(value)}")
    return value


def _require_bool(value: Any, name: str) -> bool:
    if type(value) is not bool:
        raise WorkflowConfigError(f"{name} must be a boolean, got {_type_name(value)}")
    return value


def _require_nonnegative_int(value: Any, name: str) -> int:
    # bool is an int subclass in Python, but it is not a valid budget value.
    if type(value) is not int:
        raise WorkflowConfigError(f"{name} must be a non-negative integer, got {_type_name(value)}")
    if value < 0:
        raise WorkflowConfigError(f"{name} must be a non-negative integer, got {value}")
    return value


def _require_enum(value: Any, name: str) -> str:
    if not isinstance(value, str):
        raise WorkflowConfigError(f"{name} must be a string, got {_type_name(value)}")
    allowed = _ENUMS[name]
    if value not in allowed:
        allowed_text = ", ".join(sorted(allowed))
        raise WorkflowConfigError(f"{name} must be one of {allowed_text}, got {value!r}")
    return value


def _unknown_fields(mapping: Mapping[Any, Any], allowed: frozenset[str]) -> list[Any]:
    return sorted((key for key in mapping if key not in allowed), key=repr)


def _parse_config(config: Mapping[str, Any]) -> dict[str, Any]:
    unknown = _unknown_fields(config, _ROOT_FIELDS)
    if unknown:
        names = ", ".join(repr(key) for key in unknown)
        raise WorkflowConfigError(f"unknown configuration field(s): {names}")

    effective: dict[str, Any] = {
        "workflow_effort": _require_enum(config.get("workflow_effort", "standard"), "workflow_effort"),
        "behavioral": _require_enum(config.get("behavioral", "auto"), "behavioral"),
        "module_scale": _require_enum(config.get("module_scale", "small"), "module_scale"),
        "mode": _require_enum(config.get("mode", "replay"), "mode"),
        "resources": {"remote_seconds": 0, "max_concurrent_runs": 0},
        "simulation_authorized": _require_bool(
            config.get("simulation_authorized", False), "simulation_authorized"
        ),
    }

    if "resources" in config:
        resources = _require_mapping(config["resources"], "resources")
        unknown_resources = _unknown_fields(resources, _RESOURCE_FIELDS)
        if unknown_resources:
            names = ", ".join(repr(key) for key in unknown_resources)
            raise WorkflowConfigError(
                f"unknown resources field(s): {names}"
            )
        effective["resources"] = {
            "remote_seconds": _require_nonnegative_int(
                resources.get("remote_seconds", 0), "resources.remote_seconds"
            ),
            "max_concurrent_runs": _require_nonnegative_int(
                resources.get("max_concurrent_runs", 0), "resources.max_concurrent_runs"
            ),
        }

    for key in ("external_review_authorized", "single_agent"):
        if key in config:
            effective[key] = _require_bool(config[key], key)
    if "knowledge_write_policy" in config:
        value = config["knowledge_write_policy"]
        if not isinstance(value, str) or value not in ("approval", "authorized", "read_only"):
            raise WorkflowConfigError("knowledge_write_policy must be approval, authorized, or read_only")
        effective["knowledge_write_policy"] = value

    if "repository_root" in config:
        repository_root = config["repository_root"]
        if not isinstance(repository_root, str):
            raise WorkflowConfigError(
                f"repository_root must be a string, got {_type_name(repository_root)}"
            )
        effective["repository_root"] = repository_root

    for key in ('subagent_model', 'reasoning_effort', 'site_config'):
        if key in config:
            if not isinstance(config[key], str) or not config[key].strip():
                raise WorkflowConfigError(f'{key} must be a nonempty string')
            effective[key] = config[key]
    if 'site_config' in effective:
        if 'repository_root' not in effective:
            raise WorkflowConfigError('site_config requires repository_root')
        repo = Path(effective['repository_root']).resolve()
        site = (repo / effective['site_config']).resolve()
        if not site.is_relative_to(repo):
            raise WorkflowConfigError('site_config must remain inside repository_root')
        effective['site_config'] = str(site)
    return effective


def _role_routing(module_scale: str) -> dict[str, list[str]]:
    routing = {
        "ANALYST": ["analog-learn", "analog-audit"],
        "REVIEWER": ["analog-review"],
        "VERIFIER": ["analog-verify", "spectre"],
        "EDITOR": ["analog-recovery-report"],
    }
    if module_scale == "large":
        routing["ARCHITECT"] = ["analog-decompose", "analog-integrate"]
    return routing


def _execution_plan(effective: Mapping[str, Any]) -> dict[str, Any]:
    mode = effective["mode"]
    resources = effective["resources"]
    if mode == "replay":
        return {
            "remote_execution_allowed": False,
            "reason": "replay_mode_forbids_remote_execution",
        }
    if not effective["simulation_authorized"]:
        return {
            "remote_execution_allowed": False,
            "reason": "simulation_not_authorized",
        }
    if resources["remote_seconds"] <= 0 or resources["max_concurrent_runs"] <= 0:
        return {
            "remote_execution_allowed": False,
            "reason": "positive_remote_seconds_and_max_concurrent_runs_required",
        }
    return {
        "remote_execution_allowed": True,
        "reason": "live_mode_authorized_with_positive_resources",
    }


def _behavioral_plan(behavioral: str) -> dict[str, Any]:
    if behavioral == "on":
        raise UnsupportedBehavioralError(
            "behavioral='on' is unsupported: Verilog-A behavioral execution is not implemented in this round"
        )
    if behavioral == "off":
        return {
            "state": "disabled",
            "selected": False,
            "executes_va": False,
            "message": "behavioral execution is disabled",
        }
    return {
        "state": "deferred",
        "selected": False,
        "executes_va": False,
        "message": "behavioral execution is deferred/not_selected; this round does not execute Verilog-A",
    }


def resolve(config: Mapping[str, Any]) -> dict[str, Any]:
    """Validate *config* and return a deterministic, frozen workflow plan.

    The returned ``effective_config`` contains defaults and never increases the
    supplied resource budget.  ``behavioral='on'`` is rejected because that
    branch is intentionally not implemented yet.
    """

    if not isinstance(config, Mapping):
        raise WorkflowConfigError(f"configuration must be an object, got {_type_name(config)}")
    effective = _parse_config(config)
    effort = effective["workflow_effort"]
    policy = copy.deepcopy(_POLICIES[effort])
    return {
        "effective_config": effective,
        "effort": {
            "level": effort,
            "description": _EFFORTS[effort]["description"],
            "coverage_strategy": _EFFORTS[effort]["coverage_strategy"],
            "evidence_standard": "fixed_for_all_efforts",
            "budget_policy": "use_declared_resources_only",
        },
        "role_routing": _role_routing(effective["module_scale"]),
        "role_policy": {
            "ANALYST": {"depth": policy["analysis"], "revision_limit": policy["revision_limit"], "dut_fixed": True},
            "VERIFIER": {"pre_sim": policy["pre_sim"], "coverage": policy["verification"],
                         "conditions_from": "admitted_project_conditions_not_forward_defaults"},
            "REVIEWER": {"configured_reviewers_requested": policy["reviewers"],
                         "stages": ["pre", "post", "report"], "critical_review_required": True},
            "EDITOR": {"depth": policy["report"], "all_template_requirements_accounted_for": True,
                       "render_and_trace_required": True,
                       "reader_review_required": True},
        },
        "coverage_closeout": {
            "required": True,
            "owner": "root",
            "reference": "skills/analog-recovery/references/coverage-closeout.md",
            "inputs": ["report_requirements", "coverage", "recovery-iterations", "resource_accounting"],
            "status": "pending",
            "execution": "agent_review_not_automatic_validation",
        },
        "closeout": {
            "case_archive_required": policy["archive"],
            "evolution": policy["evolution"],
            "evolution_execution": {
                "required": bool(policy["evolution"]),
                "skill": "analog-evolve",
                "skill_path": "skills/analog-evolve/SKILL.md",
                "mode": "recovery",
                "owner": "root",
                "status": "pending" if policy["evolution"] else "not_required_by_effort",
                "engine_execution": "not_run",
                "reason": "Preparation only; recovery review runs in the skill, not the forward engine.",
            },
            "write_policy": effective.get("knowledge_write_policy", "approval"),
            "adapter": "tools/recovery_wiki.py",
            "preserve_existing_convergence": True,
            "new_project_convergence": False,
            "case_files": ["summary.yml", "trajectory.yml", "narrative.md"] if policy["archive"] else [],
            "status": "pending" if policy["archive"] else "not_required_by_effort",
        },
        "review_transport": {
            "adapter": "scripts/recovery_review.py",
            "site_config": effective.get('site_config'),
            "protocol": "references/external-review.md",
            "external_models": "resolved from site reviewers.yml, not subagent_model",
            "starts_api_calls": False,
            "authorized": effective.get("external_review_authorized", False),
        },
        "behavioral": _behavioral_plan(effective["behavioral"]),
        "execution": _execution_plan(effective),
        "subagent_model": effective.get('subagent_model'),
        "reasoning_effort": effective.get('reasoning_effort'),
        "dispatch": {
            "starts_agents": False,
            "scheduler": False,
            "description": "configuration parser and dispatch plan only",
            "single_agent": effective.get("single_agent", False),
        },
    }


def prepare_run(repo: Path, run: Path, overrides: Mapping[str, Any] | None = None,
                *, intent: str = "report", block: str | None = None) -> dict[str, Any]:
    """Freeze a production plan; never send, simulate, dispatch, or write wiki.

    The caller applies the current task's restrictions through overrides. Shared
    site report_defaults represent the project's previously established policy.
    The low-level resolve({}) replay behavior remains backward compatible.
    """
    import yaml
    repo = repo.resolve(strict=True)
    run = run.resolve()
    if not run.is_relative_to(repo) or run == repo:
        raise WorkflowConfigError("run directory must be a child of repository_root")
    if intent not in ("report", "replay", "static"):
        raise WorkflowConfigError("intent must be report, replay, or static")
    overrides = dict(overrides or {})
    _parse_config(overrides)  # reject misspelled restrictions before writing anything
    site_path = repo / "skills/analog-recovery/_local/site.json"
    review_path = Path(__file__).resolve().with_name("recovery_review.py")
    spec = importlib.util.spec_from_file_location("recovery_prepare_review", review_path)
    review = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(review)
    site = review.local_site(site_path)
    if Path(site["repository_root"]) != repo or Path(site["project_root"]) != repo:
        raise WorkflowConfigError("shared site must bind this workspace as evidence root, not an old WORK directory")
    python = Path(site["python"]).resolve(strict=True)
    if not python.is_relative_to(repo):
        raise WorkflowConfigError("site python must remain within repository_root")
    defaults = dict(site.get("report_defaults", {}))
    _parse_config(defaults)
    effort_path = repo / "config/effort.yml"
    shared_effort = yaml.safe_load(effort_path.read_text(encoding="utf-8-sig")) if effort_path.exists() else {}
    shared_effort = _require_mapping(shared_effort or {}, "effort config")
    block_overrides = _require_mapping(shared_effort.get("overrides") or {}, "effort overrides")
    tier = overrides.get("workflow_effort", block_overrides.get(block, shared_effort.get("default_effort", "standard")))
    _require_enum(tier, "workflow_effort")
    policy = _POLICIES[tier]
    config = {**defaults, "workflow_effort": tier}
    if intent != "report":
        if overrides.get("mode") == "live" or overrides.get("simulation_authorized") is True:
            raise WorkflowConfigError("replay/static intent conflicts with a live override")
        config.update(mode="replay", simulation_authorized=False)
    config.update(overrides)
    for key, expected in (("repository_root", str(repo)), ("site_config", str(run / "site.json"))):
        if key in overrides and Path(overrides[key]).resolve() != Path(expected):
            raise WorkflowConfigError(f"{key} cannot redirect the prepared run")
        config[key] = expected
    resources = {"remote_seconds": 0, "max_concurrent_runs": 0}
    if config.get("mode") == "live" and config.get("simulation_authorized") is True:
        resources = {"remote_seconds": policy["remote_seconds"], "max_concurrent_runs": policy["concurrency"]}
    resources.update(defaults.get("resources", {}))
    resources.update(overrides.get("resources", {}))
    config["resources"] = resources
    plan = resolve(config)
    runtime_site = copy.deepcopy(site)
    runtime_site.pop("report_defaults", None)
    runtime_site["python"] = str(python)
    runtime_site["run_dir"] = str(run)
    for key, limit in (("max_calls_per_run", policy["review_calls"]), ("max_rounds", policy["review_rounds"])):
        configured = _require_nonnegative_int(site.get(key, limit), key)
        runtime_site[key] = min(configured, limit)
    transport = plan["review_transport"]
    if not transport["authorized"]:
        runtime_site.update(max_calls_per_run=0, max_rounds=0)
    transport.update(status="disabled_by_task", reviewers=[], reviewer_batches=[], issues=[],
                     max_calls_per_run=runtime_site["max_calls_per_run"], max_rounds=runtime_site["max_rounds"])
    if transport["authorized"]:
        # Reuse the actual bridge loader (including environment substitution), but never its transport.
        bridge_spec = importlib.util.spec_from_file_location("recovery_prepare_bridge", repo / "tools/review_bridge.py")
        bridge = importlib.util.module_from_spec(bridge_spec)
        try:
            bridge_spec.loader.exec_module(bridge)
            cfg = bridge.load_config(site["reviewers_config"])
            available = [k for k, v in cfg.get("reviewers", {}).items() if v.get("enabled", True)]
            requested = policy["reviewers"]
            selected = available if requested == "all" else available[:requested]
            if not selected:
                raise WorkflowConfigError("no enabled reviewer")
            batches = [selected[i:i + 2] for i in range(0, len(selected), 2)]
            models = []
            for batch in batches:
                models.extend({"name": name, "model": item["model"]}
                              for name, item in review.select_reviewers(cfg, batch).items())
            transport.update(reviewers=models, reviewer_batches=batches, status="configured_not_executed")
            if isinstance(requested, int) and len(selected) < requested:
                transport["issues"].append("fewer_configured_reviewers_than_effort_requests")
            if not runtime_site["max_calls_per_run"] or not runtime_site["max_rounds"]:
                transport.update(status="blocked_configuration")
                transport["issues"].append("zero_review_budget")
            elif len(selected) * 3 > runtime_site["max_calls_per_run"]:
                transport["issues"].append("review_budget_cannot_cover_all_three_stages_for_all_reviewers")
        except Exception:
            # Config/SDK errors can contain credentials. Persist only a fixed diagnostic.
            transport.update(status="blocked_configuration", issues=["reviewer_configuration_unavailable_or_incomplete"])
    runtime_site["reviewer_batches"] = transport["reviewer_batches"]
    plan["preparation"] = {"intent": intent, "effort_source": "task_override" if "workflow_effort" in overrides else
                           "block_override" if block in block_overrides else "config/effort.yml" if effort_path.exists() else "standard_default",
                           "budget_source": "recovery_tier_defaults_with_site_and_task_overrides",
                           "source_root": str(repo), "run_dir": str(run),
                           "external_requests_sent": 0, "simulations_run": 0, "wiki_written": False}
    if intent == "report" and not plan["execution"]["remote_execution_allowed"]:
        plan["preparation"]["simulation_limitation"] = plan["execution"]["reason"]
    outputs = {"workflow.json": config, "workflow.resolved.json": plan, "site.json": runtime_site}
    for name in outputs:
        if (run / name).exists():
            raise WorkflowConfigError(f"refusing to overwrite existing output: {run / name}")
    run.mkdir(parents=True, exist_ok=True)
    for name, value in outputs.items():
        with (run / name).open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
    return plan


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Resolve an analog-recovery workflow configuration without dispatching work."
    )
    parser.add_argument("config", nargs="?", type=Path, help="JSON configuration; task overrides in preparation mode")
    parser.add_argument("--out", type=Path, help="new JSON output file (low-level resolution only)")
    parser.add_argument("--repo", type=Path, help="prepare a production run in this workspace")
    parser.add_argument("--run-dir", type=Path)
    parser.add_argument("--intent", choices=("report", "replay", "static"), default="report")
    parser.add_argument("--effort", choices=tuple(_EFFORTS))
    parser.add_argument("--block", help="key in config/effort.yml overrides")
    parser.add_argument("--read-only", action="store_true", help="prepare with simulation/API/wiki mutation disabled")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.repo is not None:
        if args.run_dir is None or args.out is not None:
            print("error: preparation requires --run-dir and does not accept --out", file=sys.stderr)
            return 2
        try:
            config = json.loads(args.config.read_text(encoding="utf-8-sig")) if args.config else {}
            config = dict(_require_mapping(config, "configuration"))
            if args.effort:
                config["workflow_effort"] = args.effort
            if args.read_only:
                config.update(mode="replay", simulation_authorized=False, external_review_authorized=False,
                              knowledge_write_policy="read_only")
            run = args.run_dir if args.run_dir.is_absolute() else args.repo / args.run_dir
            plan = prepare_run(args.repo, run, config, intent=args.intent, block=args.block)
            print(json.dumps({"prepared": str(run.resolve()), "effort": plan["effort"]["level"],
                              "execution": plan["execution"], "review": plan["review_transport"]["status"],
                              "archive_required": plan["closeout"]["case_archive_required"],
                              "executed": False}, ensure_ascii=False))
            return 0
        except (OSError, ValueError, KeyError, TypeError):
            print("error: cannot prepare run; check paths, task overrides and workspace site/effort configuration", file=sys.stderr)
            return 2
    if args.config is None or args.out is None or args.run_dir or args.effort or args.block or args.read_only or args.intent != "report":
        print("error: use config --out, or --repo with --run-dir", file=sys.stderr)
        return 2
    if args.out.exists():
        print(f"error: refusing to overwrite existing output: {args.out}", file=sys.stderr)
        return 2
    try:
        with args.config.open("r", encoding="utf-8") as handle:
            config = json.load(handle)
        plan = resolve(config)
        # Exclusive creation is the final overwrite guard, including races
        # between the initial existence check and writing the result.
        with args.out.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(plan, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
    except FileExistsError:
        print(f"error: refusing to overwrite existing output: {args.out}", file=sys.stderr)
        return 2
    except (OSError, json.JSONDecodeError, WorkflowConfigError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
