#!/usr/bin/env python3
"""Feature helpers for GhostFix Brain v3 training artifacts."""

from __future__ import annotations

import re
from typing import Iterable

import numpy as np
from scipy import sparse
from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.pipeline import FeatureUnion, Pipeline
from sklearn.preprocessing import MaxAbsScaler


PYTHON_EXCEPTION_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*(?:Error|Exception|Warning))\b")
FILE_FRAME_RE = re.compile(r'File\s+"[^"]+",\s+line\s+\d+')
KEYWORDS = (
    "import",
    "json",
    "file",
    "open",
    "path",
    "index",
    "list",
    "dict",
    "key",
    "none",
    "str",
    "int",
    "float",
    "async",
    "await",
    "class",
    "def",
    "return",
    "permission",
    "install",
    "module",
    "attribute",
    "argument",
    "colon",
)
ERROR_TYPE_TEMPLATE_MAP = {
    "ModuleNotFoundError": "install_missing_module",
    "NameError": "define_or_correct_name",
    "FileNotFoundError": "verify_file_path",
    "KeyError": "check_key_or_get",
    "IndexError": "validate_index_bounds",
    "JSONDecodeError": "ensure_valid_json",
    "SyntaxError": "correct_syntax",
    "IndentationError": "correct_syntax",
    "TabError": "correct_syntax",
    "AttributeError": "check_attribute_or_type",
    "TypeError": "check_type_or_signature",
    "ValueError": "validate_value",
}


def normalize_text(value: object) -> str:
    return str(value or "").replace("\r\n", "\n").replace("\r", "\n")


def section(text: str, name: str) -> str:
    marker = f"{name}:"
    start = text.find(marker)
    if start < 0:
        return ""
    start += len(marker)
    next_markers = [
        index
        for index in (text.find("\nERROR:", start), text.find("\nMESSAGE:", start), text.find("\nCONTEXT:", start), text.find("\nFAILING_LINE:", start))
        if index >= 0
    ]
    end = min(next_markers) if next_markers else len(text)
    return text[start:end].strip()


def extract_exception_class(text: str) -> str:
    message = section(text, "MESSAGE") or section(text, "ERROR") or text
    matches = PYTHON_EXCEPTION_RE.findall(message)
    return matches[-1] if matches else "UnknownException"


def extract_failing_line(text: str) -> str:
    line = section(text, "FAILING_LINE")
    if line:
        return line
    lines = [item.strip() for item in text.splitlines() if item.strip()]
    for index, item in enumerate(lines):
        if PYTHON_EXCEPTION_RE.search(item) and index > 0:
            return lines[index - 1]
    return ""


def stack_depth(text: str) -> int:
    return len(FILE_FRAME_RE.findall(text))


def code_context(text: str) -> str:
    return "\n".join(
        part
        for part in (section(text, "CONTEXT"), extract_failing_line(text))
        if part
    )


def message_text(text: str) -> str:
    return section(text, "MESSAGE") or section(text, "ERROR") or text


class TextSectionExtractor(BaseEstimator, TransformerMixin):
    """Extract one logical part from Brain input text for TF-IDF."""

    def __init__(self, part: str) -> None:
        self.part = part

    def fit(self, X: Iterable[str], y: object = None) -> "TextSectionExtractor":
        return self

    def transform(self, X: Iterable[str]) -> list[str]:
        values = []
        for item in X:
            text = normalize_text(item)
            if self.part == "message":
                values.append(message_text(text))
            elif self.part == "exception":
                values.append(extract_exception_class(text))
            elif self.part == "failing_line":
                values.append(extract_failing_line(text))
            elif self.part == "code_context":
                values.append(code_context(text))
            else:
                values.append(text)
        return values


class StructuredDebugFeatures(BaseEstimator, TransformerMixin):
    """Compact numeric features that complement TF-IDF text signals."""

    def fit(self, X: Iterable[str], y: object = None) -> "StructuredDebugFeatures":
        return self

    def transform(self, X: Iterable[str]):
        rows: list[list[float]] = []
        for item in X:
            text = normalize_text(item)
            lower = text.lower()
            failing_line = extract_failing_line(text)
            message = message_text(text)
            exception = extract_exception_class(text)
            rows.append(
                [
                    float(stack_depth(text)),
                    float(len(message)),
                    float(len(failing_line)),
                    float(message.count("\n")),
                    float("traceback" in lower),
                    float("file " in lower and "line " in lower),
                    float(bool(re.search(r"\^\^+|\^\^\^\^+", text))),
                    float(exception == "UnknownException"),
                    *[float(keyword in lower) for keyword in KEYWORDS],
                ]
            )
        return sparse.csr_matrix(np.asarray(rows, dtype=np.float32))


def make_feature_union(max_features: int = 70000) -> FeatureUnion:
    return FeatureUnion(
        [
            (
                "full_text_tfidf",
                TfidfVectorizer(
                    lowercase=True,
                    ngram_range=(1, 3),
                    max_features=max_features,
                    min_df=1,
                    sublinear_tf=True,
                ),
            ),
            (
                "message_tfidf",
                Pipeline(
                    [
                        ("extract", TextSectionExtractor("message")),
                        ("tfidf", TfidfVectorizer(lowercase=True, ngram_range=(1, 3), max_features=20000, min_df=1, sublinear_tf=True)),
                    ]
                ),
            ),
            (
                "exception_tfidf",
                Pipeline(
                    [
                        ("extract", TextSectionExtractor("exception")),
                        ("tfidf", TfidfVectorizer(lowercase=False, ngram_range=(1, 1), min_df=1)),
                    ]
                ),
            ),
            (
                "failing_line_tfidf",
                Pipeline(
                    [
                        ("extract", TextSectionExtractor("failing_line")),
                        ("tfidf", TfidfVectorizer(lowercase=True, token_pattern=r"(?u)\b\w+\b|==|!=|<=|>=|\(|\)|\[|\]|\{|\}|\.|,", ngram_range=(1, 3), max_features=15000, min_df=1)),
                    ]
                ),
            ),
            (
                "code_context_tfidf",
                Pipeline(
                    [
                        ("extract", TextSectionExtractor("code_context")),
                        ("tfidf", TfidfVectorizer(lowercase=True, token_pattern=r"(?u)\b\w+\b|==|!=|<=|>=|\(|\)|\[|\]|\{|\}|\.|,", ngram_range=(1, 3), max_features=20000, min_df=1)),
                    ]
                ),
            ),
            (
                "structured",
                Pipeline(
                    [
                        ("features", StructuredDebugFeatures()),
                        ("scale", MaxAbsScaler()),
                    ]
                ),
            ),
        ],
        n_jobs=None,
    )


class RuleOverrideClassifier(BaseEstimator):
    """Conservative post-prediction overrides for obvious traceback facts."""

    def __init__(self, estimator: object, task: str) -> None:
        self.estimator = estimator
        self.task = task

    @property
    def classes_(self):
        return self.estimator.classes_

    def predict(self, X: Iterable[str]):
        predictions = list(self.estimator.predict(X))
        classes = set(str(item) for item in self.classes_)
        overridden = []
        for text, prediction in zip(X, predictions):
            value = str(prediction)
            exception = extract_exception_class(normalize_text(text))
            if self.task == "error_type" and exception in classes:
                value = exception
            elif self.task == "fix_template":
                template = ERROR_TYPE_TEMPLATE_MAP.get(exception)
                if template in classes:
                    value = template
            elif self.task == "auto_fix_safety":
                normalized = normalize_text(text).lower()
                if (
                    "requires_project_context: true" in normalized
                    or "complexity_class: unsafe_to_autofix" in normalized
                    or exception in {"FileNotFoundError", "PermissionError", "RuntimeError"}
                ) and "not_safe" in classes:
                    value = "not_safe"
            overridden.append(value)
        return np.asarray(overridden, dtype=object)

    def predict_proba(self, X: Iterable[str]):
        return self.estimator.predict_proba(X)


class ConfidenceCappedClassifier(BaseEstimator):
    """Cap maximum probability for heads where labels are inherently noisy."""

    def __init__(self, estimator: object, max_confidence: float = 0.84) -> None:
        self.estimator = estimator
        self.max_confidence = max_confidence

    @property
    def classes_(self):
        return self.estimator.classes_

    def predict(self, X: Iterable[str]):
        return self.estimator.predict(X)

    def predict_proba(self, X: Iterable[str]):
        probabilities = np.asarray(self.estimator.predict_proba(X), dtype=np.float64)
        if probabilities.shape[1] <= 1:
            return probabilities
        capped = probabilities.copy()
        for row in capped:
            max_index = int(np.argmax(row))
            max_value = float(row[max_index])
            if max_value <= self.max_confidence:
                continue
            excess = max_value - self.max_confidence
            row[max_index] = self.max_confidence
            other_indexes = [index for index in range(len(row)) if index != max_index]
            other_total = float(sum(row[index] for index in other_indexes))
            if other_total <= 0:
                share = excess / len(other_indexes)
                for index in other_indexes:
                    row[index] += share
            else:
                for index in other_indexes:
                    row[index] += excess * (row[index] / other_total)
        return capped


class UnsafePatternComplexityClassifier(BaseEstimator):
    """Allow unsafe_to_autofix only when text has concrete unsafe cues."""

    def __init__(self, estimator: object, fallback_label: str = "needs_context_reasoning") -> None:
        self.estimator = estimator
        self.fallback_label = fallback_label

    @property
    def classes_(self):
        return self.estimator.classes_

    def _has_unsafe_signal(self, text: str) -> bool:
        lower = normalize_text(text).lower()
        patterns = (
            r"\b(delete|remove|unlink|rmtree|rm\s+-rf|shutil\.rmtree|os\.remove|truncate)\b",
            r"\b(write|overwrite|open\(.+['\"]w|replace|rename|move|copyfile)\b",
            r"\b(drop\s+table|delete\s+from|update\s+\w+\s+set|insert\s+into|alter\s+table|cursor\.execute|commit\(\))\b",
            r"\b(subprocess|shell=true|os\.system|popen|run_sh|rm\s+-rf|del\s+/|powershell|cmd\.exe)\b",
            r"\b(os\.environ|dotenv|config|settings|env|token|secret|api[_-]?key|network|request|http|url)\b",
            r"\b(side effect|destructive|mutation|mutate|unsafe|drop|overwrite)\b",
            r"\b(systemexit\(main\)|get_output_data|thread_cleanup|invocation\.execute|issuecontext|buildopencore)\b",
        )
        return any(re.search(pattern, lower) for pattern in patterns)

    def predict(self, X: Iterable[str]):
        predictions = list(self.estimator.predict(X))
        classes = set(str(item) for item in self.classes_)
        fallback = self.fallback_label if self.fallback_label in classes else str(predictions[0] if predictions else "")
        adjusted = []
        for text, prediction in zip(X, predictions):
            value = str(prediction)
            if value == "unsafe_to_autofix" and not self._has_unsafe_signal(text):
                value = fallback
            adjusted.append(value)
        return np.asarray(adjusted, dtype=object)

    def predict_proba(self, X: Iterable[str]):
        return self.estimator.predict_proba(X)
