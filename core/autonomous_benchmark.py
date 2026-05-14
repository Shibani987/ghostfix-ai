from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

from core.autonomous_agent import repair_autonomously


@dataclass
class AutonomousBenchmarkReport:
    total_cases: int
    solved_cases: int
    regressed_cases: int
    validation_successes: int
    retry_successes: int
    unresolved_cases: int
    elapsed_ms: int

    @property
    def solve_rate(self) -> float:
        return _rate(self.solved_cases, self.total_cases)

    @property
    def regression_rate(self) -> float:
        return _rate(self.regressed_cases, self.total_cases)

    @property
    def validation_success_rate(self) -> float:
        return _rate(self.validation_successes, self.total_cases)

    @property
    def retry_success_rate(self) -> float:
        return _rate(self.retry_successes, self.total_cases)

    @property
    def unresolved_rate(self) -> float:
        return _rate(self.unresolved_cases, self.total_cases)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload.update(
            {
                "solve_rate": self.solve_rate,
                "regression_rate": self.regression_rate,
                "validation_success_rate": self.validation_success_rate,
                "retry_success_rate": self.retry_success_rate,
                "unresolved_rate": self.unresolved_rate,
            }
        )
        return payload


def run_autonomous_benchmark(cases: Iterable[dict[str, Any]], *, cwd: str | Path | None = None) -> AutonomousBenchmarkReport:
    start = time.perf_counter()
    rows = list(cases)
    solved = 0
    regressed = 0
    validation_successes = 0
    retry_successes = 0
    unresolved = 0
    for case in rows:
        result = repair_autonomously(
            case.get("diagnostic") or case,
            cwd=case.get("cwd") or cwd,
            command=case.get("command") or "",
            max_loops=int(case.get("max_loops") or 3),
        )
        if result.ok:
            solved += 1
        else:
            unresolved += 1
        telemetry = result.telemetry or {}
        if telemetry.get("regression_result") == "failed":
            regressed += 1
        if telemetry.get("convergence_result") == "converged":
            validation_successes += 1
        if result.ok and int(telemetry.get("retry_count") or 0) > 0:
            retry_successes += 1
    elapsed = int((time.perf_counter() - start) * 1000)
    return AutonomousBenchmarkReport(
        total_cases=len(rows),
        solved_cases=solved,
        regressed_cases=regressed,
        validation_successes=validation_successes,
        retry_successes=retry_successes,
        unresolved_cases=unresolved,
        elapsed_ms=elapsed,
    )


def _rate(value: int, total: int) -> float:
    return round(value / total, 4) if total else 0.0
