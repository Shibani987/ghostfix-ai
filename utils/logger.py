from rich.console import Console

console = Console()

def info(msg):
    console.print(f"[cyan]{msg}[/cyan]")

def error(msg):
    console.print(f"[red]{msg}[/red]")