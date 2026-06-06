"""
GhostFix CLI — AI-powered terminal error watcher & auto-fixer
"""
import click
import sys
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from ghostfix.config.manager import ConfigManager
from ghostfix.core.watcher import ProcessWatcher
from ghostfix.ui.renderer import Renderer

console = Console()


def print_banner():
    banner = Text()
    banner.append("👻 GhostFix", style="bold magenta")
    banner.append(" v0.1.0", style="dim")
    banner.append("  —  AI-powered error watcher & auto-fixer", style="italic cyan")
    console.print(Panel(banner, border_style="magenta", padding=(0, 2)))


@click.group(invoke_without_command=True)
@click.pass_context
def main(ctx):
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@main.command()
@click.argument("command")
@click.option("--fix", is_flag=True, default=False, help="Auto-fix errors when detected")
@click.option("--ai", is_flag=True, default=False, help="Use cloud AI provider (OpenAI/Claude/Gemini)")
@click.option("--provider", type=click.Choice(["openai", "claude", "gemini"]), default=None, help="Force specific AI provider")
@click.option("--auto", is_flag=True, default=False, help="Apply patches without confirmation")
@click.option("--config", type=click.Path(), default=None, help="Path to ghostfix.config.py")
@click.option("--verbose", "-v", is_flag=True, default=False, help="Show verbose output")
def watch(command, fix, ai, provider, auto, config, verbose):
    """Watch a command and auto-fix errors.

    \b
    Examples:
      ghostfix watch "npm run server" --fix --ai
      ghostfix watch "python manage.py runserver" --fix
      ghostfix watch "flask run" --fix --ai --provider claude
      ghostfix watch "go run main.go" --fix
    """
    print_banner()

    # Load config
    cfg_manager = ConfigManager(config_path=config)
    cfg = cfg_manager.load()

    # If --ai flag, ensure provider is configured
    if ai:
        cfg = cfg_manager.ensure_ai_provider(
            cfg,
            force_provider=provider,
            prompt_each_run=True,
            save=False,
        )

    elif not cfg.get("model"):
        # No --ai and no config model → prompt user
        console.print(
            "\n[yellow]⚠  No AI provider configured.[/yellow]\n"
            "Run with [bold]--ai[/bold] to use a cloud provider, or create a "
            "[bold]ghostfix.config.py[/bold] for a custom/local model.\n"
        )
        sys.exit(1)

    # Override auto_apply if --auto flag
    if auto:
        cfg.setdefault("fix", {})["auto_apply"] = True

    renderer = Renderer(console=console, verbose=verbose)

    watcher = ProcessWatcher(
        command=command,
        config=cfg,
        fix_enabled=fix,
        renderer=renderer,
    )

    try:
        console.print(f"\n[bold green]▶  Watching:[/bold green] [cyan]{command}[/cyan]\n")
        watcher.run()
    except KeyboardInterrupt:
        console.print("\n\n[dim]👻 GhostFix stopped.[/dim]\n")
        sys.exit(0)


@main.command()
def setup():
    """Interactive setup: configure AI provider and API key."""
    print_banner()
    cfg_manager = ConfigManager()
    cfg = cfg_manager.load()
    cfg_manager.ensure_ai_provider(cfg, force_provider=None)
    console.print("\n[green]✅  Setup complete![/green]")


@main.command()
def config_show():
    """Show current GhostFix configuration."""
    print_banner()
    cfg_manager = ConfigManager()
    cfg = cfg_manager.load()
    import json
    # Mask API keys
    display = dict(cfg)
    if display.get("api_key"):
        display["api_key"] = display["api_key"][:8] + "..." 
    console.print_json(json.dumps(display, indent=2))


@main.command()
def init():
    """Create a ghostfix.config.py in the current directory (for custom models)."""
    target = Path.cwd() / "ghostfix.config.py"
    if target.exists():
        console.print("[yellow]ghostfix.config.py already exists.[/yellow]")
        return

    template = '''\
# ghostfix.config.py
# Place this file in your project root to use a custom/local model
# without needing any cloud API key.

GHOSTFIX_CONFIG = {
    "model": {
        "type": "custom",

        # --- Ollama (local) example ---
        "endpoint": "http://localhost:11434/api/chat",
        "model_name": "codellama:13b",

        # --- Your own server example ---
        # "endpoint": "http://192.168.1.100:8000/v1/chat",
        # "api_key": "optional-if-needed",
        # "headers": {"X-Custom-Header": "value"},
        #
        # The endpoint must accept POST with JSON body:
        # { "model": "...", "messages": [...] }
        # and return { "message": { "content": "..." } }
        # (OpenAI-compatible format)
    },

    "watch": {
        "ignore": [
            "node_modules", ".git", "dist", "__pycache__",
            "venv", ".env", "migrations", ".mypy_cache",
        ],
        "max_file_size_kb": 500,
        "context_lines": 60,
    },

    "fix": {
        "auto_apply": False,       # True = no confirmation prompt
        "create_backup": True,     # backup before patching
        "restart_on_fix": True,    # restart command after fix
        "max_retries": 3,          # retry limit for same error
    },

    "ui": {
        "language": "english",     # "bangla" coming soon
        "show_diff": True,
        "color_theme": "dark",
    },
}
'''
    target.write_text(template)
    console.print(f"[green]✅  Created:[/green] {target}")
    console.print("[dim]Edit ghostfix.config.py to point to your local model endpoint.[/dim]")


if __name__ == "__main__":
    main()
