from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Iterable


EXPECTED_USER_ERROR = "expected_user_error"
APP_BUG = "app_bug"
INFRASTRUCTURE_ERROR = "infrastructure_error"
DEPENDENCY_ERROR = "dependency_error"
AUTH_ANOMALY = "auth_anomaly"
REPEATED_FAILURE = "repeated_failure"
UNKNOWN = "unknown"

SEVERITY_INFO = "info"
SEVERITY_WARNING = "warning"
SEVERITY_ERROR = "error"
SEVERITY_CRITICAL = "critical"

AUTH_SPIKE_THRESHOLD = 5
REPEATED_FAILURE_THRESHOLD = 3


@dataclass
class ClassifiedEvent:
    category: str
    severity: str
    reason: str
    brain_escalation_needed: bool
    expected_behavior: bool
    likely_bug: bool
    anomalies: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)


def classify_log_text(text: object) -> ClassifiedEvent:
    """Classify user-provided runtime logs without external calls or Brain generation."""
    if not isinstance(text, str):
        return _unknown("Log input was not text.")

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    lower = text.lower()
    endpoints = _endpoint_counts(lines)
    status_counts = _status_counts(text)
    auth_count = status_counts.get(401, 0) + status_counts.get(403, 0)
    server_error_count = sum(count for code, count in status_counts.items() if 500 <= code <= 599)
    timeout_count = len(re.findall(r"\b(timeout|timed out|connection refused|econnreset|etimedout)\b", lower))
    deploy_marker = bool(re.search(r"\b(deploy|deployment|release|restart|restarted|started|boot)\b", lower))
    invalid_credentials = bool(re.search(r"\b(invalid password|wrong password|bad credentials|invalid credentials|login failed)\b", lower))
    dependency_error = bool(
        re.search(
            r"\b(ModuleNotFoundError|ImportError|No module named|Cannot find module|missing package|package not found)\b",
            text,
        )
    )
    db_timeout = bool(re.search(r"\b(database|postgres|postgresql|mysql|sqlite|redis|db)\b", lower)) and timeout_count > 0
    repeated_traceback = _same_traceback_repeated(text)

    anomalies = _anomalies(
        endpoints=endpoints,
        auth_count=auth_count,
        server_error_count=server_error_count,
        timeout_count=timeout_count,
        repeated_traceback=repeated_traceback,
        deploy_marker=deploy_marker,
    )

    if auth_count >= AUTH_SPIKE_THRESHOLD:
        severity = SEVERITY_CRITICAL if deploy_marker else SEVERITY_WARNING
        return ClassifiedEvent(
            category=AUTH_ANOMALY,
            severity=severity,
            reason="Repeated 401/403 responses suggest an authentication anomaly.",
            brain_escalation_needed=False,
            expected_behavior=False,
            likely_bug=True,
            anomalies=anomalies,
            evidence=_sample(lines, ["401", "403", "deploy", "restart"]),
        )

    if repeated_traceback:
        return ClassifiedEvent(
            category=REPEATED_FAILURE,
            severity=SEVERITY_ERROR,
            reason="The same traceback or exception appears repeatedly.",
            brain_escalation_needed=True,
            expected_behavior=False,
            likely_bug=True,
            anomalies=anomalies,
            evidence=_sample(lines, ["Traceback", "Error", "Exception"]),
        )

    if db_timeout or timeout_count >= REPEATED_FAILURE_THRESHOLD:
        return ClassifiedEvent(
            category=INFRASTRUCTURE_ERROR,
            severity=SEVERITY_CRITICAL if timeout_count >= REPEATED_FAILURE_THRESHOLD else SEVERITY_ERROR,
            reason="Database, network, or service timeout signals point to infrastructure trouble.",
            brain_escalation_needed=True,
            expected_behavior=False,
            likely_bug=False,
            anomalies=anomalies,
            evidence=_sample(lines, ["timeout", "timed out", "database", "db", "redis"]),
        )

    if dependency_error:
        return ClassifiedEvent(
            category=DEPENDENCY_ERROR,
            severity=SEVERITY_ERROR,
            reason="The log contains missing import or missing package signals.",
            brain_escalation_needed=False,
            expected_behavior=False,
            likely_bug=True,
            anomalies=anomalies,
            evidence=_sample(lines, ["ModuleNotFoundError", "ImportError", "No module named", "Cannot find module"]),
        )

    if server_error_count > 0:
        return ClassifiedEvent(
            category=APP_BUG,
            severity=SEVERITY_CRITICAL if server_error_count >= REPEATED_FAILURE_THRESHOLD else SEVERITY_ERROR,
            reason="HTTP 5xx responses usually indicate an application bug or failing server dependency.",
            brain_escalation_needed=True,
            expected_behavior=False,
            likely_bug=True,
            anomalies=anomalies,
            evidence=_sample(lines, ["500", "501", "502", "503", "504"]),
        )

    if auth_count == 1 and invalid_credentials:
        return ClassifiedEvent(
            category=EXPECTED_USER_ERROR,
            severity=SEVERITY_INFO,
            reason="A single invalid-credential 401/403 is expected user behavior.",
            brain_escalation_needed=False,
            expected_behavior=True,
            likely_bug=False,
            anomalies=anomalies,
            evidence=_sample(lines, ["401", "403", "invalid password", "wrong password"]),
        )

    if _has_repeated_endpoint_failure(endpoints):
        return ClassifiedEvent(
            category=REPEATED_FAILURE,
            severity=SEVERITY_WARNING,
            reason="The same endpoint failed repeatedly.",
            brain_escalation_needed=True,
            expected_behavior=False,
            likely_bug=True,
            anomalies=anomalies,
            evidence=_sample(lines, ["/", "GET", "POST", "PUT", "DELETE"]),
        )

    return _unknown("No strong production-like runtime signal matched.", anomalies=anomalies, evidence=lines[:3])


def _unknown(reason: str, *, anomalies: list[str] | None = None, evidence: list[str] | None = None) -> ClassifiedEvent:
    return ClassifiedEvent(
        category=UNKNOWN,
        severity=SEVERITY_WARNING,
        reason=reason,
        brain_escalation_needed=True,
        expected_behavior=False,
        likely_bug=False,
        anomalies=anomalies or [],
        evidence=evidence or [],
    )


def _status_counts(text: str) -> Counter[int]:
    counts: Counter[int] = Counter()
    for match in re.finditer(r"(?<!\d)([1-5]\d\d)(?!\d)", text):
        counts[int(match.group(1))] += 1
    return counts


def _endpoint_counts(lines: Iterable[str]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for line in lines:
        match = re.search(r"\b(GET|POST|PUT|PATCH|DELETE|OPTIONS|HEAD)\s+(/[^\s?\"']*)", line, re.IGNORECASE)
        if match:
            counts[match.group(2)] += 1
            continue
        match = re.search(r"\b(/[A-Za-z0-9_\-./]+)\b.*\b([4-5]\d\d)\b", line)
        if match:
            counts[match.group(1)] += 1
    return counts


def _same_traceback_repeated(text: str) -> bool:
    traceback_count = text.count("Traceback (most recent call last):")
    if traceback_count >= REPEATED_FAILURE_THRESHOLD:
        return True
    exception_lines = re.findall(r"^\s*([A-Za-z_][A-Za-z0-9_.]*(?:Error|Exception): .+)$", text, re.MULTILINE)
    return any(count >= REPEATED_FAILURE_THRESHOLD for count in Counter(exception_lines).values())


def _has_repeated_endpoint_failure(endpoints: Counter[str]) -> bool:
    return any(count >= REPEATED_FAILURE_THRESHOLD for count in endpoints.values())


def _anomalies(
    *,
    endpoints: Counter[str],
    auth_count: int,
    server_error_count: int,
    timeout_count: int,
    repeated_traceback: bool,
    deploy_marker: bool,
) -> list[str]:
    anomalies: list[str] = []
    if _has_repeated_endpoint_failure(endpoints):
        anomalies.append("repeated_same_endpoint_failures")
    if auth_count >= AUTH_SPIKE_THRESHOLD:
        anomalies.append("repeated_401_403_spike")
    if server_error_count >= REPEATED_FAILURE_THRESHOLD:
        anomalies.append("repeated_500_errors")
    if timeout_count >= REPEATED_FAILURE_THRESHOLD:
        anomalies.append("timeout_cluster")
    if repeated_traceback:
        anomalies.append("same_traceback_repeated")
    if deploy_marker and (auth_count or server_error_count or timeout_count or repeated_traceback):
        anomalies.append("failure_after_restart_or_deploy_marker")
    return anomalies


def _sample(lines: list[str], needles: list[str]) -> list[str]:
    lowered = [(line, line.lower()) for line in lines]
    hits = []
    for line, lower in lowered:
        if any(needle.lower() in lower for needle in needles):
            hits.append(line)
        if len(hits) >= 3:
            break
    return hits or lines[:3]
