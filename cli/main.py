"""
GhostFix AI - CLI Interface
Production-grade command-line interface
"""
import sys
import os
import shutil
import tempfile
import json
import subprocess
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from typing import Optional, List

import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import print as rprint

APP_VERSION = "0.6.0"


app = typer.Typer(
    name="ghostfix",
    help="Promptless local-first runtime debugging. Watch logs, explain crashes, and apply only safety-gated deterministic fixes.",
    add_completion=False,
    no_args_is_help=True,
    rich_markup_mode="rich",
)
config_app = typer.Typer(help="Manage local GhostFix configuration.")
daemon_app = typer.Typer(help="Run GhostFix as a local foreground daemon.")
rollback_app = typer.Typer(help="Restore files from GhostFix rollback metadata.")
app.add_typer(config_app, name="config")
app.add_typer(daemon_app, name="daemon")
app.add_typer(rollback_app, name="rollback")

console = Console()
JSON_OUTPUT = False


BRAND = r"""
   GhostFix AI
   promptless runtime debugging
"""


def _brand_header(subtitle: str = "") -> None:
    console.print(BRAND.strip("\n"), style="bold cyan", markup=False, highlight=False)
    if subtitle:
        console.print(subtitle, style="white", markup=False, highlight=False)
    console.print("-" * 72, style="cyan", markup=False, highlight=False)


def _version_callback(value: bool):
    if value:
        console.print(f"GhostFix AI v{APP_VERSION}", markup=False, highlight=False, soft_wrap=True)
        raise typer.Exit()


def _print_local_only_message():
    from core.config import is_local_only_mode
    from utils.env import SUPABASE_KEY, SUPABASE_URL

    if is_local_only_mode(Path.cwd()) or not (SUPABASE_URL and SUPABASE_KEY):
        console.print("[yellow]Running in local-only mode.[/yellow]")


@app.callback()
def root(
    version: Optional[bool] = typer.Option(
        None,
        "--version",
        help="Show GhostFix version and exit.",
        callback=_version_callback,
        is_eager=True,
    ),
    no_color: bool = typer.Option(False, "--no-color", help="Disable colorized Rich output."),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON where supported by the command."),
):
    """GhostFix AI command-line interface."""
    global JSON_OUTPUT
    JSON_OUTPUT = json_output
    if no_color:
        os.environ["NO_COLOR"] = "1"
        console.no_color = True


@app.command()
def run(
    file: str = typer.Argument(..., help="Python file to run and analyze"),
    fix: bool = typer.Option(False, "--fix", "-f", help="Apply safe auto-fix if available"),
    watch: bool = typer.Option(False, "--watch", "-w", help="Watch mode: re-run on file changes"),
    max_loops: int = typer.Option(3, "--max-loops", "-m", help="Maximum fix attempts"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
    auto_approve: bool = typer.Option(False, "--auto-approve", help="Apply validated deterministic fixes without prompting"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Diagnose and preview only; never modify files"),
):
    """
    Run a Python file and analyze errors.
    """
    if dry_run:
        print("DRY_RUN: enabled")
        print("No code will be modified")

    file_path = Path(file)
    
    if not file_path.exists():
        print("STATUS: blocked")
        print("ERROR: file not found")
        print("NEXT_STEP: run `ghostfix examples` or try an existing Python file")
        print("Next step: run `ghostfix examples` or try an existing Python file")
        print("No code was changed.")
        console.print(f"[red]Error: File not found: {file}[/red]")
        raise typer.Exit(1)
    
    if not file_path.suffix == ".py":
        console.print(f"[red]Error: Only Python files supported[/red]")
        raise typer.Exit(1)
    
    console.print("[cyan]GhostFix AI - Running[/cyan]")
    console.print(f"[cyan]{file_path.as_posix()}[/cyan]\n")
    print("STATUS: running")
    print(f"ERROR: pending for {file_path.as_posix()}")
    print("ROOT_CAUSE: pending")
    print("NEXT_STEP: GhostFix will run the file and diagnose any runtime error")
    print("Next step: GhostFix will run the file and diagnose any runtime error")
    print(f"AUTO_FIX: {'yes' if fix else 'no'}")
    print(f"Auto-fix available: {'yes' if fix else 'no'}")
    print("ROLLBACK_AVAILABLE: no")
    print("Rollback available: no")
    _print_local_only_message()

    from core.runner import run_command
    
    run_command(
        str(file_path),
        auto_fix=fix,
        max_loops=max_loops,
        verbose=verbose,
        auto_approve=auto_approve,
        dry_run=dry_run,
    )


@app.command()
def watch(
    command: str = typer.Argument(..., help='Command to run and watch, for example: "python app.py"'),
    fix: bool = typer.Option(False, "--fix", "-f", help="Allow existing deterministic safe Python auto-fix prompts"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show full GhostFix telemetry"),
    no_brain: bool = typer.Option(False, "--no-brain", help="Disable Brain routing/generation for this watch session"),
    brain_mode: str = typer.Option("auto", "--brain-mode", help="Brain mode: auto|off|route-only|generate"),
    cwd: Optional[str] = typer.Option(None, "--cwd", help="Working directory for the watched command"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Diagnose and preview only; never modify files"),
):
    """
    Run any command and watch terminal output for runtime errors.
    """
    from agent.terminal_watcher import watch_command
    _print_local_only_message()
    print("STATUS: watching")
    print(f"ERROR: pending for {command}")
    print("ROOT_CAUSE: pending")
    print("NEXT_STEP: reproduce the issue; GhostFix will diagnose the first runtime failure")
    print("Next step: reproduce the issue; GhostFix will diagnose the first runtime failure")
    print(f"AUTO_FIX: {'yes' if fix else 'no'}")
    print(f"Auto-fix available: {'yes' if fix else 'no'}")
    print("ROLLBACK_AVAILABLE: no")
    print("Rollback available: no")
    if dry_run:
        print("DRY_RUN: enabled")
        print("No code will be modified")

    if brain_mode not in {"auto", "off", "route-only", "generate"}:
        console.print("[red]Error: --brain-mode must be one of auto, off, route-only, generate[/red]")
        raise typer.Exit(1)

    old_brain_mode = os.environ.get("GHOSTFIX_BRAIN_MODE")
    if no_brain:
        os.environ["GHOSTFIX_BRAIN_MODE"] = "off"
    else:
        os.environ["GHOSTFIX_BRAIN_MODE"] = brain_mode

    try:
        watch_command(command, cwd=cwd, auto_fix=fix, verbose=verbose, dry_run=dry_run)
    except KeyboardInterrupt:
        console.print("\n[yellow]Watch stopped[/yellow]")
    except Exception as e:
        console.print(f"[red]Watch error: {e}[/red]")
        raise typer.Exit(1)
    finally:
        if old_brain_mode is None:
            os.environ.pop("GHOSTFIX_BRAIN_MODE", None)
        else:
            os.environ["GHOSTFIX_BRAIN_MODE"] = old_brain_mode


@app.command()
def context(
    path: str = typer.Argument(..., help="File or directory to inspect"),
    max_files: int = typer.Option(12, "--max-files", help="Maximum related files to read"),
    max_chars: int = typer.Option(40000, "--max-chars", help="Maximum total context characters"),
):
    """
    Show safe repo-aware context for a local file.
    """
    from core.project_context import scan_project_context

    ctx = scan_project_context(str(Path.cwd()), start_path=path, max_files=max_files, max_total_chars=max_chars)

    table = Table(title="GhostFix Project Context")
    table.add_column("Field", style="cyan")
    table.add_column("Value")
    table.add_row("project root", ctx.root)
    table.add_row("language", ctx.language)
    table.add_row("framework", ctx.framework)
    table.add_row("frameworks", ", ".join(ctx.frameworks) or "unknown")
    table.add_row("dependency files", ", ".join(ctx.dependency_files) or "none")
    table.add_row("related files", ", ".join(ctx.related_files) or "none")
    table.add_row("context files", ", ".join(sorted(ctx.files)) or "none")
    table.add_row("truncated", "yes" if ctx.truncated else "no")
    console.print(table)
    console.print(
    "dependency files: " + (", ".join(ctx.dependency_files) or "none"),
    markup=False,
    highlight=False,
)


@app.command("classify-log")
def classify_log(
    path: str = typer.Argument(..., help="Local log file to classify"),
):
    """
    Classify local production-like runtime signals without external integrations.
    """
    from core.event_classifier import classify_log_text

    log_path = Path(path)
    if not log_path.exists() or not log_path.is_file():
        console.print(f"[red]Error: Log file not found: {path}[/red]")
        raise typer.Exit(1)

    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        console.print(f"[red]Error: Could not read log file: {e}[/red]")
        raise typer.Exit(1)

    result = classify_log_text(text)
    table = Table(title="GhostFix Log Classification")
    table.add_column("Field", style="cyan")
    table.add_column("Value")
    table.add_row("category", result.category)
    table.add_row("severity", result.severity)
    table.add_row("brain escalation needed", "yes" if result.brain_escalation_needed else "no")
    table.add_row("expected behavior", "yes" if result.expected_behavior else "no")
    table.add_row("likely bug", "yes" if result.likely_bug else "no")
    table.add_row("reason", result.reason)
    table.add_row("anomalies", ", ".join(result.anomalies) or "none")
    table.add_row("evidence", " | ".join(_clip(line, 80) for line in result.evidence) or "none")
    console.print(table)
    console.print(
    f"brain escalation needed: {'yes' if result.brain_escalation_needed else 'no'}",
    markup=False,
    highlight=False,
)


@app.command("verify-release")
def verify_release(
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
):
    """
    Run local release verification checks.
    """
    from core.release_verifier import run_release_verification

    steps = run_release_verification(cwd=Path.cwd())
    effective_json = JSON_OUTPUT or json_output
    if effective_json:
        rows = [step.__dict__ for step in steps]
        print(json.dumps({"status": "fail" if any(not step.passed for step in steps) else "pass", "steps": rows}, indent=2))
        if any(not step.passed for step in steps):
            raise typer.Exit(1)
        return
    table = Table(title="GhostFix Release Verification")
    table.add_column("Check", style="cyan")
    table.add_column("Result")
    table.add_column("Command")
    for step in steps:
        result_label = "[green]PASS[/green]" if step.passed else "[red]FAIL[/red]"
        if step.passed and "Optional release tool" in step.output:
            result_label = "[yellow]WARN[/yellow]"
        table.add_row(step.name, result_label, " ".join(step.command))
    console.print(table)
    failed = [step for step in steps if not step.passed]
    warnings = [step for step in steps if step.passed and "Optional release tool" in step.output]
    if warnings:
        console.print("\n[yellow]Optional release tooling warnings:[/yellow]")
        for step in warnings:
            console.print(f"- {step.name}: {step.output}")
    if failed:
        console.print("\n[red]Hard release blockers:[/red]")
        for step in failed:
            console.print(f"- {step.name} failed with exit code {step.returncode}")
            if step.output:
                console.print(step.output[-2000:])
        raise typer.Exit(1)
    print("All required local release verification checks passed")


@app.command("validate-production")
def validate_production(
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
):
    """
    Run production validation and write local reports.
    """
    from core.production_validator import run_production_validation

    report = run_production_validation(cwd=Path.cwd())
    if JSON_OUTPUT or json_output:
        print(json.dumps(report, indent=2))
        if report["release_blockers"]:
            raise typer.Exit(1)
        return
    table = Table(title="GhostFix Local Release Validation")
    table.add_column("Check", style="cyan")
    table.add_column("Result")
    for step in report["steps"]:
        table.add_row(step["name"], "[green]PASS[/green]" if step["passed"] else "[red]FAIL[/red]")
    console.print(table)
    console.print(f"Tests passed: {'yes' if report['tests_passed'] else 'no'}")
    console.print(f"CLI commands passed: {'yes' if report['cli_commands_passed'] else 'no'}")
    console.print(f"Unresolved rate: {report.get('unresolved_rate')}")
    console.print(f"Unsafe fix rate: {report.get('unsafe_fix_rate')}")
    console.print("Reports:")
    console.print(f"  {report['reports']['json']}")
    console.print(f"  {report['reports']['markdown']}")
    if report["release_blockers"]:
        console.print("[red]Release blockers found:[/red]")
        for blocker in report["release_blockers"]:
            console.print(f"- {blocker}")
        raise typer.Exit(1)
    console.print("[green]Local release validation passed.[/green]")


@app.command()
def analyze(
    file: str = typer.Argument(..., help="Python file to analyze"),
    line: Optional[int] = typer.Option(None, "--line", "-l", help="Specific line to analyze"),
):
    """
    Analyze a Python file for potential issues.
    """
    from core.context import extract_context
    from core.detector import detect_error
    
    file_path = Path(file)
    
    if not file_path.exists():
        console.print(f"[red]Error: File not found: {file}[/red]")
        raise typer.Exit(1)
    
    # Read file and check for issues
    content = file_path.read_text(encoding="utf-8")
    lines = content.splitlines()
    
    table = Table(title=f"Analysis: {file_path.name}")
    table.add_column("Line", style="cyan")
    table.add_column("Content", style="white")
    table.add_column("Issue", style="yellow")
    
    # Simple static analysis
    for i, line in enumerate(lines, 1):
        issue = None
        
        # Check for common issues
        if "except:" in line and ":" in line:
            issue = "Bare except clause"
        elif "print(" in line and "python" in str(file_path).lower():
            pass  # print is fine
        elif "import *" in line:
            issue = "Wildcard import"
        
        if issue:
            table.add_row(str(i), line[:60], issue)
    
    console.print(table)


@app.command()
def quickstart():
    """
    Show the two-minute local GhostFix onboarding path.
    """
    _brand_header("Install in 30 seconds. Debug the first crash in the next 30.")
    print("GhostFix quickstart")
    print("Install verification:")
    print("  ghostfix --version")
    print("  ghostfix doctor")
    print("Zero-config start:")
    print("  ghostfix setup")
    print("  ghostfix run app.py")
    print('  ghostfix watch "python manage.py runserver"')
    print("First safe demos:")
    print("  ghostfix run tests/manual_errors/name_error.py --dry-run")
    print("  ghostfix run tests/manual_errors/json_empty_v2.py --fix")
    print("  ghostfix demo")
    print("Watch examples:")
    print('  ghostfix watch "python demos/python_name_error.py" --dry-run')
    print('  ghostfix watch "python demos/django_like/manage.py runserver"')
    print('  ghostfix watch "python demos/fastapi_like/main.py"')
    print('  ghostfix watch "npm run dev" --cwd demos/node_like')
    print("Trust commands:")
    print("  ghostfix audit")
    print("  ghostfix rollback last")
    print("  ghostfix incidents --last 10")
    print("Local storage:")
    print("  incidents: .ghostfix/incidents.jsonl")
    print("  feedback: .ghostfix/feedback.jsonl")
    print("  reports: .ghostfix/reports/")
    print("  fix audit: .ghostfix/fix_audit.jsonl")
    print("Safety:")
    print("  Local-first by default. No API key required. Brain is optional. Auto-fix is narrow and safety-gated.")


@app.command()
def examples():
    """
    Show categorized local GhostFix command examples.
    """
    _brand_header("Copy-paste friendly command examples.")
    print("GhostFix examples")
    print("Python script:")
    print("  ghostfix run tests/manual_errors/name_error.py")
    print("  ghostfix run tests/manual_errors/json_empty_v2.py --fix")
    print("Django:")
    print('  ghostfix watch "python manage.py runserver"')
    print('  ghostfix watch "python demos/django_like/manage.py runserver"')
    print("FastAPI:")
    print('  ghostfix watch "uvicorn main:app --reload"')
    print('  ghostfix watch "python demos/fastapi_like/main.py"')
    print("Flask:")
    print('  ghostfix watch "python app.py"')
    print('  ghostfix watch "flask run"')
    print("Node:")
    print('  ghostfix watch "npm run dev"')
    print('  ghostfix watch "npm run dev" --cwd demos/node_like')
    print("Rollback:")
    print("  ghostfix rollback last")
    print("Audit:")
    print("  ghostfix audit")
    print("  ghostfix audit --last 10")
    print("Feedback:")
    print("  ghostfix feedback --good")
    print('  ghostfix feedback --bad --note "wrong root cause"')


@app.command()
def setup(
    brain_mode: str = typer.Option("off", "--brain-mode", help="Default Brain mode: off|route-only|generate"),
    force: bool = typer.Option(False, "--force", help="Overwrite existing .ghostfix/config.json"),
):
    """
    Create a clean local-first GhostFix config and explain the privacy defaults.
    """
    from core.config import default_config, init_config, load_config, validate_config

    if brain_mode not in {"off", "route-only", "generate"}:
        console.print("[red]Error: --brain-mode must be one of off, route-only, generate[/red]")
        raise typer.Exit(1)

    _brand_header("Welcome. No API key required. No code leaves your machine.")
    path, created = init_config(Path.cwd(), overwrite=force)
    config = load_config(Path.cwd())
    if created or force:
        config.update(default_config())
        config["brain_mode"] = brain_mode
        config["brain_v4_enabled"] = brain_mode != "off"
    errors = validate_config(config)
    if errors:
        for error in errors:
            console.print(f"[red]BLOCKED:[/red] {error}")
        raise typer.Exit(1)

    if created or force:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")

    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Field", style="cyan")
    table.add_column("Value")
    table.add_row("Mode", "local-only")
    table.add_row("Cloud APIs", "not required")
    table.add_row("Telemetry", "disabled")
    table.add_row("Auto-fix default", "disabled")
    table.add_row("Brain mode", str(config.get("brain_mode", "off")))
    table.add_row("Config", str(path))
    console.print(table)
    print("STATUS: setup complete")
    print("LOCAL_FIRST: yes")
    print("NO_API_KEY_REQUIRED: yes")
    print("TELEMETRY: disabled")
    print("AUTO_FIX_DEFAULT: disabled")
    print(f"BRAIN_MODE: {config.get('brain_mode', 'off')}")
    print(f"CONFIG_SAVED: {path}")
    console.print("[green]GhostFix is ready.[/green]" if created else "[yellow]Config updated safely.[/yellow]")


@app.command()
def demo(
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON report."),
):
    """
    Run a short reproducible demo that shows diagnosis, safety, and auditability.
    """
    from core.autofix import build_patch_plan
    from core.context import extract_context
    from core.decision_engine import apply_safety_policy, decide_fix
    from core.parser import parse_error
    from core.runner import run_command

    with tempfile.TemporaryDirectory(prefix="ghostfix_demo_") as temp_dir:
        root = Path(temp_dir)
        crash = root / "app.py"
        crash.write_text("def boot()\n    print('starting GhostFix demo')\n\nboot()\n", encoding="utf-8")
        process = subprocess.run(
            [sys.executable, str(crash)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10,
        )
        parsed = parse_error(process.stderr) or {}
        context = extract_context(str(crash), process.stderr)
        decision = decide_fix(parsed, context)
        plan = build_patch_plan(str(crash), parsed, decision.to_dict())
        decision = apply_safety_policy(
            decision,
            patch_available=plan.available,
            patch_valid=plan.available,
            fix_kind=plan.fix_kind,
            validation=plan.validation,
            changed_line_count=plan.changed_line_count,
            deterministic_validator_result=plan.deterministic_validator_result,
            compile_validation_result=plan.compile_validation_result,
        )
        report = {
            "status": "ready",
            "scenario": "deterministic Python syntax crash",
            "command": f"ghostfix run {crash} --fix --dry-run",
            "error_type": parsed.get("type", ""),
            "root_cause": decision.cause,
            "auto_fix_available": decision.auto_fix_available,
            "safety_reason": decision.safety_policy_reason,
            "dry_run": True,
            "rollback_available": False,
            "code_modified": False,
        }
        if JSON_OUTPUT or json_output:
            print(json.dumps(report, indent=2))
            return

        _brand_header("A 60-second local demo: crash, diagnosis, safety gate, patch preview.")
        console.print(Panel(
            "1. Create a tiny crashing Python app\n"
            "2. Detect the runtime failure\n"
            "3. Explain the likely root cause\n"
            "4. Preview a deterministic safe patch\n"
            "5. Keep dry-run on so no file is modified",
            title="Demo Flow",
            border_style="cyan",
        ))
        print(f"DEMO_COMMAND: {report['command']}")
        print("DEMO_EXPECTATION: dry-run patch preview; no file writes")
        print("DRY_RUN: enabled")
        print("No code will be modified")
        console.print("[cyan]Running demo command...[/cyan]")
        run_command(str(crash), auto_fix=True, max_loops=1, auto_approve=False, dry_run=True)
        console.print(Panel(
            "No code was modified.\n"
            "Use `ghostfix audit` after real fixes.\n"
            "Use `ghostfix rollback last` after an applied fix creates backup metadata.",
            title="Trust Loop",
            border_style="green",
        ))
        print("STATUS: demo complete")
        print("NO_CODE_MODIFIED: yes")
        print('NEXT_STEP: try `ghostfix watch "python demos/python_name_error.py" --dry-run`')


@app.command("beta-check")
def beta_check(
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
):
    """
    Verify local closed-beta readiness without changing user project files.
    """
    checks = _beta_checks(Path.cwd())
    blockers = [check for check in checks if not check["ok"]]
    if JSON_OUTPUT or json_output:
        print(json.dumps({"status": "fail" if blockers else "pass", "checks": checks}, indent=2))
        if blockers:
            raise typer.Exit(1)
        return

    for check in checks:
        status = "PASS" if check["ok"] else "BLOCKER"
        print(f"{status}: {check['name']} - {check['detail']}")

    if blockers:
        print("GhostFix is not ready for closed beta trial.")
        print("Blockers:")
        for blocker in blockers:
            print(f"- {blocker['name']}: {blocker['detail']}")
        raise typer.Exit(1)

    print("GhostFix is ready for closed beta trial.")


def _beta_checks(root: Path) -> list[dict]:
    checks = []
    checks.append(_beta_doctor_check(root))
    checks.append(_beta_callable_check("quickstart", quickstart))
    checks.append(_beta_callable_check("examples", examples))
    checks.append(_beta_callable_check("setup", setup))
    checks.append(_beta_callable_check("demo", demo))
    checks.append(_beta_dry_run_check())
    checks.append(_beta_audit_check(root))
    checks.append(_beta_callable_check("rollback command", rollback_last))
    checks.append(_beta_feedback_check())
    checks.append(_beta_reports_writable_check(root))
    return checks


def _beta_doctor_check(root: Path) -> dict:
    from core.doctor import run_doctor

    try:
        failed = [check for check in run_doctor(root) if check.get("status") == "FAIL"]
    except Exception as exc:
        return _beta_check("doctor", False, f"doctor raised {exc}")
    if failed:
        return _beta_check("doctor", False, failed[0].get("details", "doctor reported a failure"))
    return _beta_check("doctor", True, "required local checks passed")


def _beta_callable_check(name: str, value) -> dict:
    return _beta_check(name, callable(value), "available" if callable(value) else "missing")


def _beta_dry_run_check() -> dict:
    from core.runner import run_command

    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            path = root / "dry_run_case.py"
            original = "if True\n    print('safe')\n"
            path.write_text(original, encoding="utf-8")
            old_cwd = Path.cwd()
            os.chdir(root)
            try:
                with redirect_stdout(StringIO()):
                    run_command(str(path), auto_fix=True, max_loops=1, dry_run=True)
                unchanged = path.read_text(encoding="utf-8") == original
            finally:
                os.chdir(old_cwd)
    except Exception as exc:
        return _beta_check("dry-run", False, f"dry-run check raised {exc}")
    return _beta_check("dry-run", unchanged, "diagnosed without modifying files" if unchanged else "file changed")


def _beta_audit_check(root: Path) -> dict:
    from core.fix_audit import load_fix_audits

    try:
        load_fix_audits(root, last=10)
    except Exception as exc:
        return _beta_check("audit command", False, f"audit read failed: {exc}")
    return _beta_check("audit command", True, "local audit history readable")


def _beta_feedback_check() -> dict:
    from core.feedback import save_feedback

    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            save_feedback("good", note="beta-check", root=Path(temp_dir))
    except Exception as exc:
        return _beta_check("feedback command", False, f"feedback write failed: {exc}")
    return _beta_check("feedback command", True, "local feedback write works")


def _beta_reports_writable_check(root: Path) -> dict:
    reports = root / ".ghostfix" / "reports"
    try:
        reports.mkdir(parents=True, exist_ok=True)
        probe = reports / ".beta_check"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except Exception as exc:
        return _beta_check("local reports path", False, f"not writable: {exc}")
    return _beta_check("local reports path", True, str(reports))


def _beta_check(name: str, ok: bool, detail: str) -> dict:
    return {"name": name, "ok": bool(ok), "detail": detail}


@app.command()
def incidents(
    last: Optional[int] = typer.Option(None, "--last", "-n", help="Show only the last N incidents"),
):
    """
    Show local debugging incident history.
    """
    from core.incidents import incidents_path, load_incidents

    rows = load_incidents(Path.cwd(), last=last)
    path = incidents_path(Path.cwd())
    if not rows:
        console.print(f"[yellow]No incidents recorded yet.[/yellow] ({path})")
        return

    table = Table(title=f"GhostFix Incidents ({path})")
    table.add_column("Time", style="cyan")
    table.add_column("Runtime")
    table.add_column("Error", style="red")
    table.add_column("File")
    table.add_column("Cause")
    table.add_column("Fix")
    table.add_column("Conf", justify="right")
    table.add_column("Auto-fix")
    table.add_column("Resolved")

    for row in rows:
        table.add_row(
            str(row.get("timestamp", "")),
            str(row.get("runtime", "")),
            str(row.get("error_type", "")),
            _clip(str(row.get("file", "")), 28),
            _clip(str(row.get("cause", "")), 42),
            _clip(str(row.get("fix", "")), 42),
            f"{row.get('confidence', 0)}%",
            "yes" if row.get("auto_fix_available") else "no",
            "yes" if row.get("resolved_after_fix") else "no",
        )

    console.print(table)
    for row in rows:
        console.print(
        f"incident error: {row.get('error_type', '')}",
        markup=False,
        highlight=False,)


@app.command()
def audit(
    last: Optional[int] = typer.Option(None, "--last", "-n", help="Show only the last N audit rows"),
):
    """
    Show local auto-fix audit history.
    """
    from core.fix_audit import fix_audit_path, load_fix_audits

    rows = load_fix_audits(Path.cwd(), last=last)
    path = fix_audit_path(Path.cwd())
    if not rows:
        console.print(f"[yellow]No fix audit records yet.[/yellow] ({path})")
        return

    table = Table(title=f"GhostFix Fix Audit ({path})")
    table.add_column("Time", style="cyan")
    table.add_column("Target")
    table.add_column("Confirmed")
    table.add_column("Rollback")
    table.add_column("Validator")
    table.add_column("Patch")
    for row in rows:
        table.add_row(
            str(row.get("timestamp", "")),
            _clip(str(row.get("target_file", "")), 32),
            "yes" if row.get("user_confirmed") else "no",
            "yes" if row.get("rollback_available") else "no",
            _clip(str(row.get("validator_result", "")), 32),
            _clip(str(row.get("patch_summary", "")), 48),
        )
    console.print(table)
    for row in rows:
        print(f"AUDIT_TARGET: {row.get('target_file', '')}")
        print(f"USER_CONFIRMED: {'yes' if row.get('user_confirmed') else 'no'}")
        print(f"ROLLBACK_AVAILABLE: {'yes' if row.get('rollback_available') else 'no'}")


@app.command()
def stats():
    """
    Show local GhostFix usage summary from local JSONL files.
    """
    from core.training_export import build_stats

    summary = build_stats(Path.cwd())
    print(f"TOTAL_INCIDENTS: {summary['total_incidents']}")
    print(f"TOTAL_SUCCESSFUL_DIAGNOSES: {summary['total_successful_diagnoses']}")
    print(f"TOTAL_AUTO_FIX_ATTEMPTS: {summary['total_auto_fix_attempts']}")
    print(f"TOTAL_ROLLBACK_EVENTS: {summary['total_rollback_events']}")
    print(f"FEEDBACK_GOOD: {summary['feedback_good']}")
    print(f"FEEDBACK_BAD: {summary['feedback_bad']}")
    print(f"DRY_RUN_USAGE_COUNT: {summary['dry_run_usage_count']}")

    table = Table(title="GhostFix Local Stats")
    table.add_column("Metric", style="cyan")
    table.add_column("Value")
    table.add_row("total incidents", str(summary["total_incidents"]))
    table.add_row("total successful diagnoses", str(summary["total_successful_diagnoses"]))
    table.add_row("total auto-fix attempts", str(summary["total_auto_fix_attempts"]))
    table.add_row("total rollback events", str(summary["total_rollback_events"]))
    table.add_row("feedback good", str(summary["feedback_good"]))
    table.add_row("feedback bad", str(summary["feedback_bad"]))
    table.add_row("dry-run usage count", str(summary["dry_run_usage_count"]))
    table.add_row("most common error types", _format_common(summary["most_common_error_types"]))
    table.add_row("most common frameworks", _format_common(summary["most_common_frameworks"]))
    console.print(table)


@app.command("export-training-data")
def export_training_data_command(
    include_snippets: bool = typer.Option(
        False,
        "--include-snippets",
        help="Include short sanitized snippets. Review before sharing.",
    ),
):
    """
    Create a local, redacted training-data export for user-reviewed sharing.
    """
    from core.training_export import export_training_data

    if include_snippets:
        print("Snippets may contain project code. Review before sharing.")
    path, count = export_training_data(Path.cwd(), include_snippets=include_snippets)
    print("Export created locally.")
    print("No data was uploaded.")
    print("Review before sharing.")
    print(f"EXPORT_PATH: {path}")
    print(f"EXPORT_ROWS: {count}")


@app.command()
def feedback(
    good: bool = typer.Option(False, "--good", help="Mark the latest GhostFix result as good"),
    bad: bool = typer.Option(False, "--bad", help="Mark the latest GhostFix result as bad"),
    note: str = typer.Option("", "--note", help="Optional local feedback note"),
):
    """
    Save local feedback for the latest GhostFix incident.
    """
    from core.feedback import save_feedback

    if good == bad:
        console.print("[red]Error: choose exactly one of --good or --bad[/red]")
        raise typer.Exit(1)

    save_feedback("good" if good else "bad", note=note, root=Path.cwd())
    print("STATUS: feedback saved")
    print("NEXT_STEP: keep using GhostFix; local feedback will help review diagnosis quality")
    print("Next step: keep using GhostFix; local feedback will help review diagnosis quality")
    console.print("Feedback saved locally.")


@rollback_app.command("last")
def rollback_last():
    """
    Restore the latest incident backup to its original file.
    """
    from core.incidents import load_incidents

    rows = load_incidents(Path.cwd(), last=1)
    latest = rows[0] if rows else None
    metadata = (latest or {}).get("rollback_metadata") or {}
    backup = metadata.get("backup")
    target = metadata.get("target") or (latest or {}).get("file")

    if not latest or not backup or not target:
        print("STATUS: no rollback")
        print("ROLLBACK_AVAILABLE: no")
        print("Rollback available: no")
        print("NEXT_STEP: run GhostFix with an applied safe fix before using rollback")
        print("Next step: run GhostFix with an applied safe fix before using rollback")
        console.print("No rollback available for the latest incident.")
        return

    backup_path = _incident_path(backup)
    target_path = _incident_path(target)

    if not target_path.exists():
        print("STATUS: rollback failed")
        print("ROLLBACK_AVAILABLE: no")
        print("Rollback available: no")
        print("NEXT_STEP: verify the original file path still exists")
        print("Next step: verify the original file path still exists")
        console.print(f"[red]Rollback failed: original file is missing: {target_path}[/red]")
        raise typer.Exit(1)
    if not backup_path.exists():
        print("STATUS: rollback failed")
        print("ROLLBACK_AVAILABLE: no")
        print("Rollback available: no")
        print("NEXT_STEP: verify the backup file path still exists")
        print("Next step: verify the backup file path still exists")
        console.print(f"[red]Rollback failed: backup file is missing: {backup_path}[/red]")
        raise typer.Exit(1)

    print("STATUS: rollback ready")
    print("ROLLBACK_AVAILABLE: yes")
    print("Rollback available: yes")
    print(f"NEXT_STEP: confirm restore to {target_path}")
    print(f"Next step: confirm restore to {target_path}")
    confirmed = input(f"Restore backup to {target_path}? [y/n] ").strip().lower() == "y"
    if not confirmed:
        print("STATUS: rollback cancelled")
        print("No code was changed")
        console.print("Rollback cancelled.")
        return

    shutil.copyfile(backup_path, target_path)
    print("STATUS: rollback completed")
    print("NEXT_STEP: rerun your command to verify the restored file")
    print("Next step: rerun your command to verify the restored file")
    console.print("Rollback completed.")

    from core.fix_audit import record_fix_audit

    record_fix_audit(
        target_file=str(target_path),
        backup_path=str(backup_path),
        patch="rollback restore",
        validator_result="rollback completed",
        rollback_available=True,
        user_confirmed=True,
        root=Path.cwd(),
    )


def _incident_path(value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return Path.cwd() / path


def _clip(value: str, length: int) -> str:
    if len(value) <= length:
        return value
    return value[: max(0, length - 3)] + "..."


def _format_common(rows: list[dict]) -> str:
    if not rows:
        return "none"
    return ", ".join(f"{row['value']} ({row['count']})" for row in rows)


def _is_optional_doctor_check(name: str) -> bool:
    return str(name).startswith("Optional package") or str(name).startswith("Brain v4")


@app.command()
def memory(
    action: str = typer.Argument(..., help="Action: stats, top, export"),
    limit: int = typer.Option(10, "--limit", "-n", help="Number of results"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Output file for export"),
):
    """
    Manage error memory.
    """
    from core.memory import get_memory

    memory = get_memory()
    if getattr(memory, "mode", "") == "local-only":
        console.print("[yellow]Running in local-only mode.[/yellow]")
    
    if action == "stats":
        stats = memory.get_statistics()
        
        console.print(Panel(
            f"[bold]Total Records:[/bold] {stats['total_records']}\n"
            f"[bold]Successful Fixes:[/bold] {stats['successful_fixes']}\n"
            f"[bold]Success Rate:[/bold] {stats['success_rate']}%",
            title="Memory Statistics"
        ))
        
        if stats['top_error_types']:
            console.print("\n[bold]Top Error Types:[/bold]")
            for item in stats['top_error_types']:
                console.print(f"  - {item['type']}: {item['count']} occurrences")
    
    elif action == "top":
        top_errors = memory.get_top_errors(limit)
        
        table = Table(title=f"Top {limit} Errors")
        table.add_column("Type", style="cyan")
        table.add_column("Error", style="white")
        table.add_column("Fix", style="green")
        table.add_column("Uses", style="yellow")
        
        for error in top_errors:
            table.add_row(
                error['error_type'],
                error['error_message'][:50],
                error['fix'][:40],
                str(error['use_count'])
            )
        
        console.print(table)
    
    elif action == "export":
        if not output:
            console.print("[red]Error: --output required for export[/red]")
            raise typer.Exit(1)
        
        output_path = Path(output)
        count = memory.export_training_data(output_path)
        console.print(f"[green]✓ Exported {count} records to {output}[/green]")
    
    else:
        console.print(f"[red]Unknown action: {action}[/red]")
        raise typer.Exit(1)


@daemon_app.command("start")
def daemon_start(
    command: str = typer.Argument(..., help='Command to monitor, for example: "python app.py"'),
    fix: bool = typer.Option(False, "--fix", "-f", help="Allow existing deterministic safe Python auto-fix prompts"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show full GhostFix telemetry"),
    cwd: Optional[str] = typer.Option(None, "--cwd", help="Working directory for the monitored command"),
    restart_delay: float = typer.Option(1.0, "--restart-delay", help="Seconds to wait before restarting a completed command"),
    max_runs: Optional[int] = typer.Option(None, "--max-runs", hidden=True),
):
    """
    Start a foreground GhostFix daemon around watch mode.
    """
    from agent.daemon_runtime import start_daemon

    console.print("[cyan]GhostFix daemon starting in foreground.[/cyan]")
    console.print("[yellow]Press Ctrl+C for graceful shutdown.[/yellow]\n")
    _print_local_only_message()

    try:
        start_daemon(
            command,
            cwd=cwd,
            auto_fix=fix,
            verbose=verbose,
            restart_delay=restart_delay,
            max_runs=max_runs,
        )
    except Exception as e:
        console.print(f"[red]Daemon error: {e}[/red]")
        raise typer.Exit(1)
    finally:
        console.print("[yellow]GhostFix daemon stopped.[/yellow]")


@daemon_app.command("status")
def daemon_status():
    """
    Show local GhostFix daemon status.
    """
    from agent.daemon_runtime import read_daemon_status

    status = read_daemon_status(Path.cwd())
    table = Table(title="GhostFix Daemon Status")
    table.add_column("Field", style="cyan")
    table.add_column("Value")
    for key in ["status", "pid", "command", "cwd", "runs", "updated_at", "stopped_at", "last_returncode"]:
        if key in status:
            table.add_row(key, str(status[key]))
    console.print(table)


@daemon_app.command("stop")
def daemon_stop():
    """
    Request a foreground GhostFix daemon to stop.
    """
    from agent.daemon_runtime import request_daemon_stop

    path = request_daemon_stop(Path.cwd())
    console.print(f"[yellow]Stop requested.[/yellow] ({path})")


@app.command()
def demo_report():
    """
    Run product-readiness demo scenarios and write JSON/Markdown reports.
    """
    from core.demo_report import REPORT_JSON, REPORT_MD, run_demo_report

    rows = run_demo_report(Path.cwd())

    table = Table(title="GhostFix Demo Readiness Report")
    table.add_column("Scenario", style="cyan")
    table.add_column("Error")
    table.add_column("Framework")
    table.add_column("Root Cause")
    table.add_column("Confidence", justify="right")
    table.add_column("Auto-fix")
    table.add_column("Result")

    for row in rows:
        table.add_row(
            row["scenario_name"],
            row["detected_error_type"],
            row["detected_framework"],
            row["root_cause"],
            f"{row['confidence']}%",
            "yes" if row["auto_fix_available"] else "no",
            "SKIPPED" if row.get("skipped") else ("PASS" if row["pass"] else "FAIL"),
        )

    console.print(table)
    passed = sum(1 for row in rows if row["pass"] and not row.get("skipped"))
    total = sum(1 for row in rows if not row.get("skipped"))
    skipped = sum(1 for row in rows if row.get("skipped"))
    console.print(f"\nSaved JSON report: {REPORT_JSON}")
    console.print(f"Saved Markdown report: {REPORT_MD}")
    console.print(f"Passed: {passed}/{total}; Skipped: {skipped}")


@app.command()
def doctor(
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
):
    """
    Check local GhostFix environment health.
    """
    from core.doctor import run_doctor

    checks = run_doctor(Path.cwd())
    failed = [check for check in checks if check["status"] == "FAIL"]
    warned = [check for check in checks if check["status"] == "WARN"]
    summary_status = "fail" if failed else ("warn" if warned else "ok")
    if JSON_OUTPUT or json_output:
        print(json.dumps({"status": summary_status, "checks": checks}, indent=2))
        if failed:
            raise typer.Exit(1)
        return
    next_step = (
        "fix failed checks before relying on GhostFix"
        if failed
        else ("review warnings; GhostFix can still run locally" if warned else "GhostFix is ready for local diagnosis")
    )
    print(f"STATUS: {summary_status}")
    print("ERROR: none" if not failed else f"ERROR: {failed[0]['check']}")
    print("ROOT_CAUSE: environment check")
    print(f"NEXT_STEP: {next_step}")
    print(f"Next step: {next_step}")
    print("AUTO_FIX: no")
    print("Auto-fix available: no")
    print("ROLLBACK_AVAILABLE: no")
    print("Rollback available: no")
    print("ONBOARDING:")
    print("  local-only mode: default unless you explicitly configure cloud memory")
    print("  Brain optionality: Brain v4 is optional local reasoning and can be disabled")
    print("  safety policy: auto-fix is narrow, deterministic, validated, and final-gated")
    print("  rollback support: applied safe fixes record backup metadata for `ghostfix rollback last`")
    print("  incidents stored: .ghostfix/incidents.jsonl")
    print("  feedback stored: .ghostfix/feedback.jsonl")
    print("  reports stored: .ghostfix/reports/")
    print("  next: run `ghostfix quickstart` or `ghostfix examples`")
    print("REQUIRED CHECKS:")
    for check in checks:
        if check["status"] == "FAIL":
            print(f"  FAIL: {check['check']} - {check['details']}")
    if not failed:
        print("  OK: required checks passed")
    print("OPTIONAL CHECKS:")
    optional_checks = [check for check in checks if _is_optional_doctor_check(check["check"])]
    for check in optional_checks:
        label = "optional warning" if check["status"] == "WARN" else "optional ok"
        print(f"  {label}: {check['check']} - {check['details']}")
    print("Optional warnings do not block local Python diagnosis.")
    print("Brain v4 is optional and not required for daily local use.")

    table = Table(title="GhostFix Doctor")
    table.add_column("CHECK", style="cyan")
    table.add_column("STATUS")
    table.add_column("DETAILS")

    styles = {"OK": "green", "WARN": "yellow", "FAIL": "red"}
    for check in checks:
        status = check["status"]
        table.add_row(
            check["check"],
            f"[{styles.get(status, 'white')}]{status}[/{styles.get(status, 'white')}]",
            check["details"],
        )

    console.print(table)


@config_app.command("init")
def config_init(
    force: bool = typer.Option(False, "--force", help="Overwrite existing .ghostfix/config.json"),
):
    """Create a local .ghostfix/config.json file."""
    from core.config import init_config

    path, created = init_config(Path.cwd(), overwrite=force)
    if created:
        console.print(f"[green]Created local config: {path}[/green]")
    else:
        console.print(f"[yellow]Config already exists: {path}[/yellow]")
    console.print("[yellow]Running in local-only mode.[/yellow]")


@config_app.command("show")
def config_show(
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
):
    """Show effective local GhostFix configuration."""
    from core.config import config_path, load_config, validate_config
    from utils.env import SUPABASE_KEY, SUPABASE_URL

    path = config_path(Path.cwd())
    config = load_config(Path.cwd())
    errors = validate_config(config)
    if JSON_OUTPUT or json_output:
        print(json.dumps({"path": str(path), "exists": path.exists(), "config": config, "errors": errors}, indent=2))
        if errors:
            raise typer.Exit(1)
        return
    console.print(f"CONFIG_PATH: {path}")
    console.print(f"CONFIG_EXISTS: {'yes' if path.exists() else 'no'}")
    console.print("CONFIG:")
    console.print(json.dumps(config, indent=2))
    if errors:
        console.print("[red]Invalid config:[/red]")
        for error in errors:
            console.print(f"- {error}")
        raise typer.Exit(1)
    if config.get("memory_mode") == "local-only" or not (SUPABASE_URL and SUPABASE_KEY):
        console.print("[yellow]Running in local-only mode.[/yellow]")
    else:
        console.print("[green]Cloud memory configured.[/green]")


@app.command()
def version():
    """Show GhostFix version."""
    console.print(f"GhostFix AI v{APP_VERSION}", markup=False, highlight=False)
    console.print("GhostFix Brain v1: stable")
    console.print("GhostFix Brain v2: experimental (set GHOSTFIX_BRAIN_V2=1)")


def main():
    """Main entry point"""
    app()


if __name__ == "__main__":
    main()
