# Release Candidate Checklist

Use this checklist before tagging the first public GitHub release.

## Required Verification

- [ ] Tests passing:
  ```powershell
  python -m unittest discover tests
  ```
  Expected latest verified result: 244 tests, OK.
- [ ] Local release gate passing:
  ```powershell
  ghostfix verify-release
  ```
- [ ] Production validation gate passing:
  ```powershell
  ghostfix validate-production
  ```
- [ ] Closed beta readiness gate passing:
  ```powershell
  ghostfix beta-check
  ```
- [ ] Watch mode demos working:
  ```powershell
  python -m cli.main watch "python demos/python_name_error.py"
  python -m cli.main watch "python demos/django_like/manage.py runserver"
  python -m cli.main watch "python demos/fastapi_like/main.py"
  python -m cli.main watch "npm run dev" --cwd demos/node_like
  ```
- [ ] Brain compatibility check passing or clearly explained as unavailable:
  ```powershell
  python ml/check_brain_v4_model.py
  ```
- [ ] Optional Brain base model download is documented and not committed:
  ```powershell
  python ml/download_base_model.py
  ```
- [ ] Watch benchmark command completes:
  ```powershell
  python ml/evaluate_watch_mode.py
  ```
  Expected latest verified result: language 100%, runtime 100%, error_type 100%, root_cause 100%, safety 100%.
- [ ] Brain routing benchmarks complete:
  ```powershell
  python ml/evaluate_runtime_brain_v4.py --dir tests/real_world_failures --brain-mode route-only
  python ml/evaluate_runtime_brain_v4.py --dir tests/brain_escalation_cases --brain-mode route-only
  ```
  Expected latest verified results:

  - Real-world deterministic route-only: 10 files, 7.492s total, 0.749s average deterministic runtime, 100% deterministic solve rate, 0% unresolved, Brain activations 0/10.
  - Brain escalation route-only: 12 files, 3.435s total, 0.283s average brain-assisted routing runtime, Brain activations 12/12, Brain escalations 12/12, 58.3% unresolved.
- [ ] Brain generate mode checked only as an experimental small-sample probe, not as a live demo:
  ```powershell
  python ml/evaluate_runtime_brain_v4.py --dir tests/brain_escalation_cases --limit 2 --brain-mode generate
  ```
  Expected latest verified result: 2 files, 111.337s total, 55.651s average brain-assisted runtime, 37.740s average Brain generation, 50% usable Brain output rate.

## Files Expected In Repo

- Source packages: `agent/`, `cli/`, `core/`, `ghostfix/`, `ml/`, `utils/`
- Tests and fixtures: `tests/`
- Local demos: `demos/`
- Public docs: `README.md`, `docs/`, `RELEASE_CANDIDATE_CHECKLIST.md`, `CONTRIBUTING.md`, `CHANGELOG.md`, `SECURITY.md`
- Packaging/config: `pyproject.toml`, `requirements.txt`, `.gitignore`
- License: `LICENSE`
- CI workflow: `.github/workflows/ci.yml`
- Lightweight required model/retriever metadata under `ml/models/`
- Heavy optional Brain/base model artifacts are downloaded locally and ignored
- Brain configuration under `ml/configs/`

## Files Intentionally Ignored

- Python caches: `__pycache__/`, `*.pyc`
- Test and tool caches: `.pytest_cache/`, `.mypy_cache/`, `.ruff_cache/`
- Local environments: `.venv/`, `venv/`, `.env`
- Auto-fix backups: `*.bak_*`
- Generated reports and debug generations: `ml/reports/`, `ml/reports/brain_debug/`
- Local runtime state: `.ghostfix/`, `.ml/`, `ghostfix/data/*.db`
- Heavy model artifacts: `*.safetensors`, `*.bin`, `*.pt`, `*.pth`, `*.ckpt`, `ml/models/base_model/`, `ml/models/**/checkpoint-*/`
- Build outputs: `dist/`, `build/`, `*.egg-info/`

## Known Limitations

- Python runtime diagnosis is the most mature path.
- JavaScript, TypeScript, and PHP are diagnosis-only.
- Auto-fix is limited to small deterministic Python fixes.
- Brain v4 is optional, local, advisory, and safety-gated.
- Brain v4 generation is experimental and slow on CPU; use `route-only` for public demos of escalation logic.
- Repo-aware multi-file fixes are not part of the current release.
- Daemon mode and incident memory are v1 local features.
- Reliability core v1 handles noisy, partial, repeated, unicode, and large local logs defensively.
- Repo-aware context is bounded and safe, but still needs real-user validation in larger repositories.

## Public GitHub Release Checklist

- [ ] `LICENSE`, `CONTRIBUTING.md`, `CHANGELOG.md`, and `SECURITY.md` are present.
- [ ] GitHub Actions CI is present and uses `python -m unittest discover tests`.
- [ ] Heavy local model files are ignored and absent from the public commit.
- [ ] No secrets, `.env` values, private reports, or generated local state are committed.
- [ ] Optional Brain setup explains how to download local model files.
- [ ] README describes the CLI as a local developer tool with safety limits.
- [ ] Release notes avoid unsupported claims.

## Closed Beta Checklist

- [ ] Tests pass:
  ```powershell
  python -m unittest discover tests
  ```
- [ ] Production validation passes:
  ```powershell
  python -m cli.main validate-production
  ```
- [ ] beta-check pass:
  ```powershell
  python -m cli.main beta-check
  ```
- [ ] dry-run tested:
  ```powershell
  ghostfix run tests/manual_errors/json_empty_v2.py --fix --dry-run
  ```
- [ ] rollback tested after one applied safe fix:
  ```powershell
  ghostfix rollback last
  ```
- [ ] audit tested:
  ```powershell
  ghostfix audit --last 10
  ```
- [ ] feedback tested:
  ```powershell
  ghostfix feedback --good
  ghostfix feedback --bad --note "wrong root cause"
  ```
- [ ] training-data export tested:
  ```powershell
  ghostfix stats
  ghostfix export-training-data
  ```
- [ ] Closed beta guide reviewed:
  ```powershell
  docs/CLOSED_BETA_GUIDE.md
  ```

## Release Notes Reminder

- Do not claim broad autonomous coding.
- Do not claim JavaScript/PHP auto-fix.
- Do not claim Brain v4 bypasses deterministic safety.
- Be explicit that generated reports are recreated by benchmark commands and are not committed.
