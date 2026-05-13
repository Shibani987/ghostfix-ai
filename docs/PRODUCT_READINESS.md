# Product Readiness

## Current Status

GhostFix is demo-ready as a local-first debugging assistant. Python is the mature support path. Django, Flask, and FastAPI/Uvicorn runtime diagnosis are supported. JavaScript/Node.js and PHP are supported in detection-only mode.

GhostFix requires no cloud inference. It uses deterministic rules, memory, a TF-IDF retriever, optional local embeddings, optional local LLM reasoning, and local Brain artifacts.

## Supported Scenarios

Python:

- CLI tracebacks
- SyntaxError missing colon safe patch preview
- JSONDecodeError empty-input safe patch preview
- Conservative confirmed auto-fix with backup and validation

Python frameworks:

- Flask missing template
- Flask app context/import issues
- Django missing app / bad `INSTALLED_APPS`
- Django settings already configured
- Django configuration errors
- FastAPI/Uvicorn bad import
- FastAPI app object not found

Detection-only:

- JavaScript/Node ReferenceError
- JavaScript module not found
- PHP undefined variable
- PHP parse error
- Broader terminal errors can be diagnosed by an optional local Hugging Face code model when configured.

## Test Summary

Current suite:

```text
python -m unittest discover tests
Ran 46 tests ... OK
```

Coverage includes:

- Python confidence and safety behavior
- Patch preview formatting
- Server traceback parsing
- Framework detection isolation
- Human-readable framework explanations
- JS/PHP detection-only diagnostics
- Optional retriever fallback behavior
- Optional local LLM fallback and safety behavior
- Demo report generation
- Doctor command health checks

## Demo Proof Summary

Run:

```powershell
python -m cli.main demo-report
```

Generated files:

- `ml/reports/demo_report.json`
- `ml/reports/demo_report.md`

Current proof:

```text
Passed: 8/8
Skipped: 2
```

Skipped scenarios are allowed when optional runtimes such as PHP are not installed.

## Known Limitations

- Python is mature; JavaScript and PHP are detection-only.
- Framework auto-fix is blocked by design.
- JavaScript/PHP auto-fix is disabled.
- Optional embeddings require `sentence-transformers` and a local model already on disk.
- Optional local LLM reasoning requires `transformers` and a local causal/instruct code model already on disk.
- Local LLM output is advisory and never enables auto-fix by itself.
- Brain v3.3 remains experimental/shadow-oriented.
- GhostFix does not replace tests, type checking, or security review.

## Next Roadmap

- Add more Python framework fixtures and real-world examples.
- Build optional local embedding index tooling.
- Add more evaluation fixtures for local LLM diagnosis across React/Vite/Next.js, Node, Java, and PHP.
- Expand JavaScript/Node and PHP parsers.
- Add richer project-context evidence while preserving secret safety.
- Improve demo/report formatting for public submissions.
- Continue Brain v3.3 evaluation before any default promotion.
