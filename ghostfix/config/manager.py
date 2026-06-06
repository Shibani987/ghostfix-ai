"""
Config Manager
Handles:
  - ~/.ghostfix/config.json  (global: AI provider + API key)
  - ./ghostfix.config.py     (project-level: custom model, watch settings)
"""
import json
import sys
from pathlib import Path

from rich.console import Console
from rich.prompt import Prompt, Confirm
from rich.panel import Panel

console = Console()

GLOBAL_CONFIG_DIR = Path.home() / ".ghostfix"
GLOBAL_CONFIG_FILE = GLOBAL_CONFIG_DIR / "config.json"

PROVIDERS = {
    "1": ("openai",  "OpenAI    (GPT-4o)"),
    "2": ("claude",  "Claude    (Anthropic)"),
    "3": ("gemini",  "Gemini    (Google)"),
}


class ConfigManager:
    def __init__(self, config_path: str | None = None):
        self.config_path = Path(config_path) if config_path else None

    # ------------------------------------------------------------------ #
    #  Load                                                                #
    # ------------------------------------------------------------------ #
    def load(self) -> dict:
        cfg: dict = {}

        # 1. Global config
        if GLOBAL_CONFIG_FILE.exists():
            try:
                cfg.update(json.loads(GLOBAL_CONFIG_FILE.read_text()))
            except Exception:
                pass

        # 2. Project-level ghostfix.config.py  (overrides global)
        project_cfg = self._load_project_config()
        if project_cfg:
            self._merge(cfg, project_cfg)

        return cfg

    def _load_project_config(self) -> dict | None:
        """Import ghostfix.config.py from project root (or --config path)."""
        candidates = []
        if self.config_path:
            candidates.append(self.config_path)
        candidates.append(Path.cwd() / "ghostfix.config.py")

        for p in candidates:
            if p.exists():
                try:
                    import importlib.util
                    spec = importlib.util.spec_from_file_location("_ghostfix_cfg", p)
                    mod = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(mod)
                    raw = getattr(mod, "GHOSTFIX_CONFIG", None)
                    if isinstance(raw, dict):
                        console.print(f"[dim]📄 Loaded project config: {p}[/dim]")
                        return raw
                except Exception as e:
                    console.print(f"[yellow]⚠  Could not load {p}: {e}[/yellow]")
        return None

    @staticmethod
    def _merge(base: dict, override: dict):
        for k, v in override.items():
            if isinstance(v, dict) and isinstance(base.get(k), dict):
                ConfigManager._merge(base[k], v)
            else:
                base[k] = v

    # ------------------------------------------------------------------ #
    #  Save                                                                #
    # ------------------------------------------------------------------ #
    def _save_global(self, cfg: dict):
        GLOBAL_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        GLOBAL_CONFIG_FILE.write_text(json.dumps(cfg, indent=2))

    # ------------------------------------------------------------------ #
    #  Interactive AI setup                                                #
    # ------------------------------------------------------------------ #
    def ensure_ai_provider(self, cfg: dict, force_provider: str | None = None) -> dict:
        """Make sure an AI cloud provider + API key is configured."""
        # Already have everything?
        if cfg.get("provider") and cfg.get("api_key") and not force_provider:
            console.print(
                f"[dim]🔑 Using saved provider: [bold]{cfg['provider']}[/bold][/dim]"
            )
            return cfg

        # Choose provider
        if force_provider:
            provider = force_provider
        elif cfg.get("provider") and not force_provider:
            provider = cfg["provider"]
        else:
            provider = self._prompt_provider()

        # Ask for API key
        existing_key = cfg.get("api_key", "")
        if existing_key:
            mask = existing_key[:8] + "..."
            use_saved = Confirm.ask(
                f"\n[cyan]Use saved API key[/cyan] [dim]({mask})[/dim]?",
                default=True,
            )
            if not use_saved:
                existing_key = ""

        if not existing_key:
            key_label = {
                "openai": "OpenAI API key (sk-...)",
                "claude": "Anthropic API key (sk-ant-...)",
                "gemini": "Google Gemini API key",
            }.get(provider, "API key")
            api_key = Prompt.ask(f"\n[cyan]Enter your {key_label}[/cyan]", password=True)
            if not api_key.strip():
                console.print("[red]No API key provided. Exiting.[/red]")
                sys.exit(1)
            existing_key = api_key.strip()

        cfg["provider"] = provider
        cfg["api_key"] = existing_key
        self._save_global(cfg)
        console.print(f"\n[green]✅  Provider saved:[/green] {provider}\n")
        return cfg

    def _prompt_provider(self) -> str:
        console.print(
            Panel(
                "\n".join(f"  [bold]{k}[/bold].  {v}" for k, v in PROVIDERS.values()),
                title="[bold cyan]Choose AI Provider[/bold cyan]",
                border_style="cyan",
                padding=(1, 2),
            )
        )
        choice = Prompt.ask(
            "Select", choices=list(PROVIDERS.keys()), default="1"
        )
        provider, label = PROVIDERS[choice]
        console.print(f"[green]✔[/green]  {label}")
        return provider
