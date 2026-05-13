#!/usr/bin/env python3
"""Train GhostFix Brain v1 as a local classic ML model."""

import argparse
import json
import pickle
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Dict, List

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix
from sklearn.model_selection import StratifiedKFold, cross_val_score, train_test_split
from sklearn.pipeline import Pipeline


DEFAULT_DATA = Path("ml/processed/ghostfix_real_debug_dataset_final.jsonl")
DEFAULT_MODEL = Path("ml/models/ghostfix_brain_v1.pkl")
DEFAULT_LABELS = Path("ml/models/ghostfix_brain_labels.json")
DEFAULT_REPORT = Path("ml/reports/ghostfix_brain_v1_eval.json")
RANDOM_STATE = 42


FIX_TEMPLATES = {
    "install_missing_module": "Install the missing package in the active environment or correct the import path.",
    "define_or_correct_name": "Define the missing variable/function before use or correct the spelling.",
    "verify_file_path": "Verify the file path or create/provide the missing file.",
    "check_key_or_get": "Check that the key exists before access or use dict.get().",
    "validate_index_bounds": "Validate sequence length and index bounds before access.",
    "ensure_valid_json": "Ensure the input contains valid non-empty JSON before parsing.",
    "correct_syntax": "Correct the syntax near the failing line.",
    "check_attribute_or_type": "Check the object type and attribute name before access.",
    "check_type_or_signature": "Check expected types/signature and convert or call correctly.",
    "validate_value": "Validate the input value before conversion or operation.",
    "general_python_fix": "Inspect traceback and context, then apply the specific Python fix.",
}


def load_jsonl(path: Path) -> List[dict]:
    records = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                records.append(json.loads(line))
    return records


def build_input(record: dict) -> str:
    return "\n".join([
        f"ERROR: {record.get('error', '')}",
        f"MESSAGE: {record.get('message', '')}",
        f"CONTEXT: {record.get('context', '')}",
        f"FAILING_LINE: {record.get('failing_line', '')}",
    ]).strip()


def fix_template(record: dict) -> str:
    error_type = record.get("error_type", "")
    fix = (record.get("fix") or "").lower()
    cause = (record.get("cause") or "").lower()
    text = f"{fix}\n{cause}"

    if error_type == "ModuleNotFoundError":
        return "install_missing_module"
    if error_type == "NameError":
        return "define_or_correct_name"
    if error_type == "FileNotFoundError":
        return "verify_file_path"
    if error_type == "KeyError":
        return "check_key_or_get"
    if error_type == "IndexError":
        return "validate_index_bounds"
    if error_type == "JSONDecodeError":
        return "ensure_valid_json"
    if error_type in {"SyntaxError", "IndentationError", "TabError"}:
        return "correct_syntax"
    if error_type == "AttributeError":
        return "check_attribute_or_type"
    if error_type == "TypeError":
        return "check_type_or_signature"
    if error_type == "ValueError":
        return "validate_value"

    if re.search(r"\b(pip|conda|poetry|uv)\b.*\b(install|add)\b", text):
        return "install_missing_module"
    if any(token in text for token in ["define", "spelling", "rename", "not defined"]):
        return "define_or_correct_name"
    if any(token in text for token in ["path", "file", "directory", "exists"]):
        return "verify_file_path"
    if any(token in text for token in ["dict.get", ".get(", "key"]):
        return "check_key_or_get"
    if any(token in text for token in ["index", "length", "bounds", "range"]):
        return "validate_index_bounds"
    if "json" in text:
        return "ensure_valid_json"
    if any(token in text for token in ["syntax", "colon", "quote", "parenthesis", "bracket"]):
        return "correct_syntax"
    if any(token in text for token in ["attribute", "method", "object type"]):
        return "check_attribute_or_type"
    if any(token in text for token in ["type", "signature", "argument", "convert"]):
        return "check_type_or_signature"
    if any(token in text for token in ["value", "validate", "input"]):
        return "validate_value"
    return "general_python_fix"


def can_stratify(labels: List[str]) -> bool:
    counts = Counter(labels)
    return bool(counts) and min(counts.values()) >= 2


def make_classifier() -> Pipeline:
    return Pipeline([
        ("tfidf", TfidfVectorizer(
            lowercase=True,
            ngram_range=(1, 3),
            max_features=50000,
            min_df=1,
            sublinear_tf=True,
        )),
        ("clf", LogisticRegression(
            max_iter=2000,
            class_weight="balanced",
            solver="saga",
            random_state=RANDOM_STATE,
        )),
    ])


def matrix_report(y_true: List[str], y_pred: List[str]) -> dict:
    labels = sorted(set(y_true) | set(y_pred))
    matrix = confusion_matrix(y_true, y_pred, labels=labels)
    return {
        "labels": labels,
        "matrix": matrix.tolist(),
    }


def most_confused(y_true: List[str], y_pred: List[str], limit: int = 10) -> list[dict]:
    counts = Counter()
    for actual, predicted in zip(y_true, y_pred):
        if actual != predicted:
            counts[(actual, predicted)] += 1
    return [
        {"actual": actual, "predicted": predicted, "count": count}
        for (actual, predicted), count in counts.most_common(limit)
    ]


def cv_accuracy(texts: List[str], labels: List[str]) -> dict:
    if len(set(labels)) < 2 or not can_stratify(labels):
        return {"folds": 0, "scores": [], "mean": 0.0}
    min_class_count = min(Counter(labels).values())
    folds = min(5, min_class_count)
    if folds < 2:
        return {"folds": 0, "scores": [], "mean": 0.0}
    cv = StratifiedKFold(n_splits=folds, shuffle=True, random_state=RANDOM_STATE)
    scores = cross_val_score(make_classifier(), texts, labels, cv=cv, scoring="accuracy")
    return {
        "folds": folds,
        "scores": [round(float(score), 4) for score in scores],
        "mean": round(float(scores.mean()), 4),
    }


def train(data_path: Path, model_path: Path, labels_path: Path, report_path: Path = DEFAULT_REPORT) -> Dict:
    records = [
        record for record in load_jsonl(data_path)
        if record.get("error") and record.get("context") and record.get("error_type") and record.get("fix")
    ]
    if len(records) < 10:
        raise RuntimeError(f"Need at least 10 usable records, got {len(records)}")

    texts = [build_input(record) for record in records]
    error_labels = [record["error_type"] for record in records]
    template_labels = [fix_template(record) for record in records]

    stratify = error_labels if can_stratify(error_labels) else None
    train_idx, test_idx = train_test_split(
        list(range(len(records))),
        test_size=0.2,
        random_state=RANDOM_STATE,
        stratify=stratify,
    )

    X_train = [texts[i] for i in train_idx]
    X_test = [texts[i] for i in test_idx]
    y_error_train = [error_labels[i] for i in train_idx]
    y_error_test = [error_labels[i] for i in test_idx]
    y_template_train = [template_labels[i] for i in train_idx]
    y_template_test = [template_labels[i] for i in test_idx]

    error_type_model = make_classifier()
    fix_template_model = make_classifier()

    error_type_model.fit(X_train, y_error_train)
    fix_template_model.fit(X_train, y_template_train)

    error_train_pred = error_type_model.predict(X_train)
    error_pred = error_type_model.predict(X_test)
    template_train_pred = fix_template_model.predict(X_train)
    template_pred = fix_template_model.predict(X_test)

    error_train_accuracy = accuracy_score(y_error_train, error_train_pred)
    error_test_accuracy = accuracy_score(y_error_test, error_pred)
    template_train_accuracy = accuracy_score(y_template_train, template_train_pred)
    template_test_accuracy = accuracy_score(y_template_test, template_pred)

    print("===== GhostFix Brain v1: Error Type Classifier =====")
    print(classification_report(y_error_test, error_pred, zero_division=0))
    print(f"Train accuracy: {error_train_accuracy:.4f}")
    print(f"Test accuracy: {error_test_accuracy:.4f}")
    print("===== GhostFix Brain v1: Fix Template Classifier =====")
    print(classification_report(y_template_test, template_pred, zero_division=0))
    print(f"Train accuracy: {template_train_accuracy:.4f}")
    print(f"Test accuracy: {template_test_accuracy:.4f}")

    error_cv = cv_accuracy(texts, error_labels)
    template_cv = cv_accuracy(texts, template_labels)
    print("===== 5-Fold Cross-Validation Accuracy =====")
    print(f"Error type CV mean: {error_cv['mean']:.4f} scores={error_cv['scores']}")
    print(f"Fix template CV mean: {template_cv['mean']:.4f} scores={template_cv['scores']}")

    error_report = classification_report(y_error_test, error_pred, output_dict=True, zero_division=0)
    template_report = classification_report(y_template_test, template_pred, output_dict=True, zero_division=0)
    eval_report = {
        "version": "ghostfix_brain_v1",
        "data_path": str(data_path),
        "records": len(records),
        "train_records": len(train_idx),
        "test_records": len(test_idx),
        "error_type_classifier": {
            "train_accuracy": round(float(error_train_accuracy), 4),
            "test_accuracy": round(float(error_test_accuracy), 4),
            "cross_validation_accuracy": error_cv,
            "classification_report": error_report,
            "confusion_matrix": matrix_report(y_error_test, list(error_pred)),
            "most_confused": most_confused(y_error_test, list(error_pred)),
        },
        "fix_template_classifier": {
            "train_accuracy": round(float(template_train_accuracy), 4),
            "test_accuracy": round(float(template_test_accuracy), 4),
            "cross_validation_accuracy": template_cv,
            "classification_report": template_report,
            "confusion_matrix": matrix_report(y_template_test, list(template_pred)),
            "most_confused": most_confused(y_template_test, list(template_pred)),
        },
    }

    artifact = {
        "version": "ghostfix_brain_v1",
        "error_type_model": error_type_model,
        "fix_template_model": fix_template_model,
        "fix_templates": FIX_TEMPLATES,
        "train_records": len(train_idx),
        "test_records": len(test_idx),
        "data_path": str(data_path),
    }

    model_path.parent.mkdir(parents=True, exist_ok=True)
    with model_path.open("wb") as handle:
        pickle.dump(artifact, handle)

    labels = {
        "version": "ghostfix_brain_v1",
        "error_types": sorted(set(error_labels)),
        "fix_templates": FIX_TEMPLATES,
        "fix_template_counts": dict(Counter(template_labels)),
        "error_type_counts": dict(Counter(error_labels)),
    }
    labels_path.parent.mkdir(parents=True, exist_ok=True)
    labels_path.write_text(json.dumps(labels, indent=2, ensure_ascii=False), encoding="utf-8")

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(eval_report, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Saved model: {model_path}")
    print(f"Saved labels: {labels_path}")
    print(f"Saved eval report: {report_path}")
    return labels


def main() -> int:
    parser = argparse.ArgumentParser(description="Train GhostFix Brain v1 classic ML model")
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--labels", type=Path, default=DEFAULT_LABELS)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()

    train(args.data, args.model, args.labels, args.report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
