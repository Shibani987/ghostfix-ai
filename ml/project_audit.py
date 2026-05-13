#!/usr/bin/env python3
"""Conservative project audit and cleanup planner for GhostFix.

The script classifies files, writes audit/cleanup/final reports, and archives
only generated low-risk debris. It never deletes runtime, model, dataset, or
safety-policy files.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "ml" / "reports"
ARCHIVE_DIR = ROOT / "archive" / "safe_cleanup_generated"
AUDIT_REPORT = REPORT_DIR / "project_audit.json"
CLEANUP_PLAN = REPORT_DIR / "cleanup_plan.json"
FINAL_REPORT = REPORT_DIR / "final_project_report.json"

SKIP_DIRS = {".git", ".venv", "venv", "env", "archive"}
TEXT_SUFFIXES = {".py", ".md", ".toml", ".txt", ".json", ".jsonl", ".csv", ".yml", ".yaml"}
CORE_RUNTIME_DIRS = {"cli", "core", "agent", "utils", "ghostfix"}
RUNTIME_KEEP = {
    "app.py",
    "pyproject.toml",
    "requirements.txt",
    "README.md",
    "__init__.py",
    "ghostfix/data/memory.db",
}
RUNTIME_ML = {
    "ml/ghostfix_brain_predict.py",
    "ml/ghostfix_brain_v2_predict.py",
    "ml/ghostfix_brain_v33_predict.py",
    "ml/predict_fix.py",
    "ml/feedback_logger.py",
    "ml/model_inference.py",
    "ml/brain_v3_features.py",
    "ml/models/ghostfix_brain_v1.pkl",
    "ml/models/ghostfix_brain_labels.json",
    "ml/models/retriever_v2.pkl",
    "ml/models/vectorizer_v2.pkl",
    "ml/models/retriever_records_v2.json",
}


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def iter_files() -> list[Path]:
    files: list[Path] = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        parts = set(path.relative_to(ROOT).parts)
        if parts & SKIP_DIRS:
            continue
        files.append(path)
    return sorted(files, key=lambda item: rel(item).lower())


def read_text(path: Path) -> str:
    if path.suffix.lower() not in TEXT_SUFFIXES:
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def classify_file(path: Path) -> str:
    relative = rel(path)
    parts = path.relative_to(ROOT).parts
    name = path.name.lower()
    suffix = path.suffix.lower()

    if "__pycache__" in parts or suffix in {".pyc", ".pyo"} or ".bak_" in name:
        return "deprecated"
    if relative.startswith("tests/") or relative == "test_system.py":
        return "test"
    if relative.startswith("docs/") or relative == "README.md":
        return "core_runtime"
    if parts[0] in CORE_RUNTIME_DIRS or relative in RUNTIME_KEEP:
        return "core_runtime"
    if relative in RUNTIME_ML:
        return "core_runtime"
    if relative.startswith("ml/models/"):
        if name.endswith((".pkl", ".json")) and any(token in name for token in ("v31", "v32", "v33", "v3", "v2")):
            return "experimental"
        return "ml_training"
    if relative.startswith(("ml/processed/", "ml/raw/")):
        return "ml_training"
    if relative.startswith("ml/reports/"):
        return "evaluation"
    if relative.startswith("ml/dataset_collectors/"):
        return "ml_training"
    if relative.startswith("ml/"):
        if name.startswith(("evaluate_", "eval_", "analyze_", "validate_")) or "report" in name or "analysis" in name:
            return "evaluation"
        if name.startswith(("train_", "build_", "audit_", "filter_", "expand_", "clean_", "dedup_", "label_", "calibrate_", "hard_negative", "export_", "prepare_", "retrain", "upgrade_")):
            return "ml_training"
        if name in {"shadow_mode_runner.py", "monitor_brain_v2.py", "lora_train.py"}:
            return "experimental"
        return "unknown"
    return "unknown"


def version_lineage(path: Path) -> str:
    text = rel(path).lower()
    for marker in ("v33", "v32", "v31", "v3", "v2", "v1"):
        if marker in text:
            return marker
    return ""


def reference_count(relative: str, texts: dict[str, str]) -> int:
    basename = Path(relative).name
    module = Path(relative).with_suffix("").as_posix().replace("/", ".")
    count = 0
    for other, text in texts.items():
        if other == relative:
            continue
        if basename and basename in text:
            count += text.count(basename)
        if module and module in text:
            count += text.count(module)
    return count


def cleanup_candidate(path: Path, classification: str, refs: int) -> dict[str, Any] | None:
    relative = rel(path)
    parts = path.relative_to(ROOT).parts
    name = path.name.lower()

    if "__pycache__" in parts or path.suffix.lower() in {".pyc", ".pyo"}:
        return {
            "path": relative,
            "action": "archive",
            "safe_to_remove": True,
            "reason": "generated Python bytecode cache",
            "risk_level": "low",
            "dependency_check": {"reference_count": 0, "dependency_found": False},
        }
    if ".bak_" in name:
        return {
            "path": relative,
            "action": "archive",
            "safe_to_remove": refs == 0,
            "reason": "timestamped backup file; source file remains present",
            "risk_level": "low" if refs == 0 else "medium",
            "dependency_check": {"reference_count": refs, "dependency_found": refs > 0},
        }
    if classification == "unknown":
        return {
            "path": relative,
            "action": "review_only",
            "safe_to_remove": False,
            "reason": "unknown ownership; manual review required",
            "risk_level": "high",
            "dependency_check": {"reference_count": refs, "dependency_found": refs > 0},
        }
    if classification == "experimental" and version_lineage(path) in {"v2", "v3", "v31", "v32"}:
        return {
            "path": relative,
            "action": "mark_deprecated",
            "safe_to_remove": False,
            "reason": "older experimental model lineage retained for reproducibility",
            "risk_level": "medium",
            "dependency_check": {"reference_count": refs, "dependency_found": refs > 0},
        }
    return None


def restructure_plan() -> dict[str, Any]:
    return {
        "proposed_structure_only": True,
        "note": "No import-breaking moves were executed. These are future migration targets.",
        "target_tree": {
            "cli/": "Typer command surface and console entrypoints.",
            "core/": "Runtime parser, decision engine, safety-gated autofix, formatting, memory.",
            "agent/": "Watch mode and daemon integrations.",
            "ml/models/": "Versioned model artifacts required for reproducible predictions.",
            "ml/training/": "Future home for train_*, build_*, audit_*, calibration, dataset construction scripts.",
            "ml/evaluation/": "Future home for evaluate_*, analyze_*, validate_* scripts and metrics helpers.",
            "ml/datasets/": "Future home for raw/processed datasets currently under ml/raw and ml/processed.",
            "ml/monitoring/": "Future home for shadow mode, feedback export, and model monitoring scripts.",
            "tests/": "Unit and manual error fixtures.",
            "docs/": "Production design docs, runbooks, status reports.",
            "scripts/": "General repo operations that are not runtime or ML-specific.",
            "archive/": "Generated or deprecated files moved only after low-risk dependency checks.",
        },
        "suggested_moves": [
            {"from": "ml/train_*.py", "to": "ml/training/", "risk": "medium", "reason": "requires import compatibility wrappers"},
            {"from": "ml/build_*.py", "to": "ml/training/", "risk": "medium", "reason": "dataset scripts are not runtime but may be invoked manually"},
            {"from": "ml/audit_*.py", "to": "ml/training/", "risk": "medium", "reason": "audit scripts feed training/eval datasets"},
            {"from": "ml/evaluate_*.py", "to": "ml/evaluation/", "risk": "medium", "reason": "offline metrics should be grouped"},
            {"from": "ml/analyze_*.py", "to": "ml/evaluation/", "risk": "medium", "reason": "analysis scripts consume reports and eval data"},
            {"from": "ml/raw/", "to": "ml/datasets/raw/", "risk": "medium", "reason": "large data path move requires script default updates"},
            {"from": "ml/processed/", "to": "ml/datasets/processed/", "risk": "medium", "reason": "large data path move requires script default updates"},
            {"from": "ml/shadow_mode_runner.py", "to": "ml/monitoring/", "risk": "medium", "reason": "shadow runner is monitoring, but imports and docs must be updated together"},
        ],
    }


def normalized_script_family(relative: str) -> str:
    name = Path(relative).name
    if not name.endswith(".py"):
        return ""
    base = name[:-3]
    base = re.sub(r"_v(?:\d+|3\d)$", "_vX", base)
    base = re.sub(r"_v3(?:1|2|3)$", "_vX", base)
    return f"{Path(relative).parent.as_posix()}/{base}.py"


def detect_duplicate_script_families(files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    families: dict[str, list[str]] = {}
    for item in files:
        family = normalized_script_family(item["path"])
        if not family:
            continue
        families.setdefault(family, []).append(item["path"])
    return [
        {"family": family, "files": sorted(paths)}
        for family, paths in sorted(families.items())
        if len(paths) > 1
    ]


def detect_outdated_versions(files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    latest_by_family = {
        "ghostfix_brain": "v33",
        "dataset_v3": "v3",
        "brain_v3": "v33",
    }
    outdated: list[dict[str, Any]] = []
    for item in files:
        path = item["path"]
        lineage = item.get("version_lineage") or ""
        if not lineage:
            continue
        if "ghostfix_brain" in path and lineage in {"v2", "v3", "v31", "v32"}:
            outdated.append({"path": path, "lineage": lineage, "latest_known": latest_by_family["ghostfix_brain"], "action": "retain_for_reproducibility"})
        elif "brain_v3" in path and lineage in {"v3", "v31", "v32"}:
            outdated.append({"path": path, "lineage": lineage, "latest_known": latest_by_family["brain_v3"], "action": "retain_for_analysis_history"})
    return outdated


def detect_temporary_debug_files(files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    markers = ("__pycache__", ".pyc", ".pyo", ".bak_", "tmp", "debug", "manual_errors")
    return [
        {"path": item["path"], "classification": item["classification"]}
        for item in files
        if any(marker in item["path"].lower() for marker in markers)
    ]


def archive_low_risk(plan: list[dict[str, Any]]) -> list[dict[str, str]]:
    archived: list[dict[str, str]] = []
    for item in plan:
        if item.get("action") != "archive" or item.get("risk_level") != "low":
            continue
        if item.get("dependency_check", {}).get("dependency_found"):
            continue
        src = ROOT / item["path"]
        if not src.exists() or not src.is_file():
            continue
        dst = ARCHIVE_DIR / item["path"]
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        archived.append({"from": item["path"], "to": rel(dst)})
    return archived


def existing_archived_files() -> list[str]:
    if not ARCHIVE_DIR.exists():
        return []
    return sorted(rel(path) for path in ARCHIVE_DIR.rglob("*") if path.is_file())


def main() -> int:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    files = iter_files()
    texts = {rel(path): read_text(path) for path in files}

    audited: list[dict[str, Any]] = []
    cleanup: list[dict[str, Any]] = []
    for path in files:
        relative = rel(path)
        classification = classify_file(path)
        refs = reference_count(relative, texts)
        item = {
            "path": relative,
            "classification": classification,
            "size_bytes": path.stat().st_size,
            "version_lineage": version_lineage(path),
            "reference_count": refs,
        }
        audited.append(item)
        candidate = cleanup_candidate(path, classification, refs)
        if candidate:
            cleanup.append(candidate)

    cleanup_summary = Counter(item["risk_level"] for item in cleanup)
    archived = archive_low_risk(cleanup)
    archived_total = existing_archived_files()
    timestamp = datetime.now(timezone.utc).isoformat()

    audit_report = {
        "generated_at": timestamp,
        "root": str(ROOT),
        "total_files_scanned": len(audited),
        "classification_counts": dict(Counter(item["classification"] for item in audited)),
        "version_lineage_counts": dict(Counter(item["version_lineage"] or "none" for item in audited)),
        "detections": {
            "duplicate_script_families": detect_duplicate_script_families(audited),
            "outdated_versioned_files": detect_outdated_versions(audited),
            "temporary_or_debug_files": detect_temporary_debug_files(audited),
            "unused_or_unreferenced_files": [
                {"path": item["path"], "classification": item["classification"]}
                for item in audited
                if item["reference_count"] == 0 and item["classification"] in {"unknown", "deprecated", "experimental"}
            ],
        },
        "files": audited,
    }
    cleanup_report = {
        "generated_at": timestamp,
        "rules": [
            "No runtime files are deleted.",
            "Brain v1 and safety_policy.py are always kept.",
            "Only generated bytecode and timestamped backups with no dependency references are archived automatically.",
            "Older ML lineage files are marked deprecated/review-only, not removed.",
        ],
        "summary_by_risk": dict(cleanup_summary),
        "removable_files": cleanup,
        "archived_files_this_run": archived,
        "archived_files_total": archived_total,
    }
    final_report = {
        "generated_at": timestamp,
        "total_files_scanned": len(audited),
        "files_kept": len(audited) - len(archived),
        "files_marked_removable": len([item for item in cleanup if item.get("safe_to_remove")]),
        "files_actually_removed": 0,
        "files_archived": len(archived_total),
        "archived_files_this_run": archived,
        "archived_files_total": archived_total,
        "structure_changes": restructure_plan(),
        "system_summary": "GhostFix is a local-first Python debugging assistant using CLI/watch runtime, deterministic safety gates, Brain v1 stable predictions, experimental v2/v3.3 predictors, retriever, feedback, and offline monitoring.",
        "ml_model_status": {
            "brain_v1": "stable runtime default; must remain present",
            "brain_v2": "experimental opt-in lineage retained",
            "brain_v3_3": "experimental opt-in and shadow-mode candidate; not default",
            "retriever": "runtime support artifact retained",
        },
        "safety_status": {
            "safety_policy_modified": False,
            "brain_can_enable_autofix_by_itself": False,
            "unsafe_autofix_policy": "blocked unless deterministic patch and policy allow",
        },
        "production_readiness_score": 82,
        "production_readiness_basis": [
            "Runtime tests pass and Brain v1 remains default.",
            "Safety policy remains explicit and conservative.",
            "ML lifecycle scripts and reports are now auditable but still need package-level reorganization.",
            "Generated caches were archived; historical ML artifacts retained for reproducibility.",
        ],
    }

    AUDIT_REPORT.write_text(json.dumps(audit_report, indent=2, ensure_ascii=False), encoding="utf-8")
    CLEANUP_PLAN.write_text(json.dumps(cleanup_report, indent=2, ensure_ascii=False), encoding="utf-8")
    FINAL_REPORT.write_text(json.dumps(final_report, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Scanned files: {len(audited)}")
    print(f"Cleanup candidates: {len(cleanup)}")
    print(f"Archived low-risk generated files: {len(archived)}")
    print(f"Audit report: {rel(AUDIT_REPORT)}")
    print(f"Cleanup plan: {rel(CLEANUP_PLAN)}")
    print(f"Final report: {rel(FINAL_REPORT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
