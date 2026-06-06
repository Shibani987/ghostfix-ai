"""
Renderer
All terminal output goes through here using Rich.
"""
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text
from rich import box


class Renderer:
    def __init__(self, console: Console, verbose: bool = False):
        self.console = console
        self.verbose = verbose

    # ── Basic log lines ──────────────────────────────────────────────
    def print_log(self, line: str):
        """Print raw process output."""
        self.console.print(f"[dim]│[/dim] {line}")

    def print_step(self, msg: str):
        self.console.print(f"\n[bold cyan]  {msg}[/bold cyan]")

    def print_info(self, msg: str):
        self.console.print(f"[blue]  ℹ  {msg}[/blue]")

    def print_success(self, msg: str):
        self.console.print(f"[bold green]  ✅  {msg}[/bold green]")

    def print_warning(self, msg: str):
        self.console.print(f"[yellow]  ⚠  {msg}[/yellow]")

    def print_error(self, msg: str):
        self.console.print(f"[bold red]  ❌  {msg}[/bold red]")

    # ── Error summary ────────────────────────────────────────────────
    def show_error_summary(self, parsed):
        self.console.print()
        location = ""
        if parsed.file_path:
            location = f"  ·  [dim]{parsed.file_path}"
            if parsed.line_number:
                location += f":{parsed.line_number}"
            location += "[/dim]"

        self.console.rule(
            f"[bold red]  ❌ {parsed.error_type}{location}",
            style="red",
        )
        self.console.print(
            f"\n  [red]{parsed.error_message or parsed.raw.splitlines()[-1][:120]}[/red]\n"
        )

    # ── AI result display ────────────────────────────────────────────
    def show_ai_result(self, result: dict):
        confidence = result.get("confidence", 0)
        conf_color = "green" if confidence > 0.8 else "yellow" if confidence > 0.5 else "red"
        conf_str = f"[{conf_color}]{int(confidence * 100)}%[/{conf_color}] confidence"

        self.console.rule("[bold cyan]  🤖 GhostFix Analysis", style="cyan")

        # Root cause
        self.console.print(
            Panel(
                f"[white]{result.get('root_cause', 'N/A')}[/white]",
                title="[bold yellow]📍 Root Cause[/bold yellow]",
                border_style="yellow",
                padding=(1, 2),
            )
        )

        # Fix suggestion
        if result.get("fix_suggestion"):
            self.console.print(
                Panel(
                    f"[white]{result['fix_suggestion']}[/white]",
                    title="[bold blue]💡 Fix Suggestion[/bold blue]",
                    border_style="blue",
                    padding=(1, 2),
                )
            )

        # Patch diff
        if result.get("patch", "").strip():
            self.console.print()
            self.console.print(
                Panel(
                    Syntax(
                        result["patch"],
                        "diff",
                        theme="monokai",
                        line_numbers=False,
                    ),
                    title=f"[bold green]🔧 Patch[/bold green]  ·  {conf_str}",
                    border_style="green",
                    padding=(0, 1),
                )
            )

        # Related files hint
        related = result.get("related_files", [])
        if related:
            self.console.print(
                f"\n[dim]  Also check: {', '.join(related)}[/dim]"
            )

        self.console.print()

    # ── Full context dump (when user presses 's') ────────────────────
    def show_full_context(self, context):
        self.console.rule("[dim]Full Context[/dim]", style="dim")
        if context.primary_file and context.primary_snippet:
            self.console.print(
                Panel(
                    Syntax(context.primary_snippet, "python", theme="monokai"),
                    title=f"[dim]{context.primary_file}[/dim]",
                    border_style="dim",
                )
            )
        for rf in context.related_files:
            self.console.print(
                Panel(
                    Syntax(rf["snippet"], "python", theme="monokai"),
                    title=f"[dim]{rf['path']}[/dim]",
                    border_style="dim",
                )
            )
