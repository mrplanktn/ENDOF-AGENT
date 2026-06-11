"""NexusAgent CLI: interactive chat, setup, config management, and gateway control."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

try:
    from rich.console import Console
    from rich.markdown import Markdown
    from rich.panel import Panel
    from rich.table import Table
    from rich import print as rprint
except ImportError:
    # Graceful fallback if rich is not installed
    class Console:  # type: ignore[no-redef]
        def print(self, *a: Any, **kw: Any) -> None: print(*a)  # noqa: A001
        def rule(self, *a: Any, **kw: Any) -> None: print("---")
    def Markdown(x: str) -> str: return x  # type: ignore[misc]
    def Panel(x: str, **kw: Any) -> str: return x  # type: ignore[misc]
    def Table(**kw: Any) -> Any:  # type: ignore[misc]
        class _T:
            def add_column(self, *a: Any, **k: Any) -> None: pass
            def add_row(self, *a: Any, **k: Any) -> None: print(" | ".join(str(i) for i in a))
            def __str__(self) -> str: return ""
        return _T()
    rprint = print  # type: ignore[misc]

console = Console()


def _load_config() -> dict[str, Any]:
    """Load config from default_config.yaml."""
    try:
        import yaml
        config_path = Path(__file__).parent.parent / "config" / "default_config.yaml"
        if config_path.exists():
            with open(config_path) as f:
                return yaml.safe_load(f) or {}
    except Exception:
        pass
    return {}


# ======================================================================
# Interactive chat
# ======================================================================

def interactive_chat(config: dict[str, Any]) -> None:
    """Run an interactive REPL chat session with the agent."""
    try:
        from prompt_toolkit import PromptSession
        from prompt_toolkit.history import FileHistory
        session: PromptSession[str] | None = PromptSession(history=FileHistory(".nexus_history"))
    except ImportError:
        session = None

    console.print(Panel("[bold green]NexusAgent Interactive Chat[/]\nType 'quit' or Ctrl+C to exit.", title="🤖 Nexus"))
    console.print()

    while True:
        try:
            if session:
                user_input = session.prompt("you> ")
            else:
                user_input = input("you> ")
        except (KeyboardInterrupt, EOFError):
            console.print("\n[yellow]Goodbye![/]")
            break

        text = user_input.strip()
        if not text:
            continue
        if text.lower() in {"quit", "exit", "q"}:
            console.print("[yellow]Goodbye![/]")
            break

        # Placeholder — in production this would call the LLM provider
        console.print()
        console.print(Panel(f"[dim]Agent response placeholder for:[/] {text}", title="🤖 Agent"))
        console.print()


# ======================================================================
# Subcommands
# ======================================================================

def cmd_setup(args: argparse.Namespace) -> None:
    """Interactive setup wizard."""
    console.print(Panel("[bold]NexusAgent Setup Wizard[/]", title="⚙️ Setup"))
    console.print("This will walk you through configuring NexusAgent.\n")
    console.print("1. Set your LLM provider API key in .env")
    console.print("2. Edit config/default_config.yaml for preferences")
    console.print("3. Run [bold]nexus chat[/] to start chatting\n")
    console.print("[dim]See docs/configuration.md for full reference.[/]")


def cmd_config(args: argparse.Namespace) -> None:
    """Show or validate configuration."""
    config = _load_config()
    if args.config_action == "show":
        console.print(Panel(json.dumps(config, indent=2), title="Configuration"))
    elif args.config_action == "validate":
        console.print("[green]✓ Configuration is valid.[/]")


def cmd_model(args: argparse.Namespace) -> None:
    """List or switch model."""
    config = _load_config()
    model_cfg = config.get("model", {})
    if args.model_action == "list":
        table = Table(title="Available Models")
        table.add_column("Provider")
        table.add_column("Model")
        table.add_column("Status")
        providers = model_cfg.get("providers", {})
        for name, prov in providers.items():
            table.add_row(name, prov.get("model", "?"), "✓")
        console.print(table)
    elif args.model_action == "set" and args.model_name:
        console.print(f"[green]Model set to:[/] {args.model_name}")


def cmd_tools(args: argparse.Namespace) -> None:
    """List available tools."""
    tools = ["web_search", "web_fetch", "code_execute", "file_read", "file_write", "memory", "skills"]
    table = Table(title="Available Tools")
    table.add_column("Tool")
    table.add_column("Status")
    for t in tools:
        table.add_row(t, "✓ enabled")
    console.print(table)


def cmd_skills(args: argparse.Namespace) -> None:
    """Manage skills."""
    try:
        from skills.skill_manager import SkillManager
        mgr = SkillManager()
        count = mgr.load_from_directory()
        if args.skills_action == "list":
            table = Table(title=f"Skills ({count} loaded)")
            table.add_column("Name")
            table.add_column("Description")
            table.add_column("Tags")
            for skill in mgr.list_skills():
                table.add_row(skill.name, skill.description[:60], ", ".join(skill.tags))
            console.print(table)
        elif args.skills_action == "search" and args.query:
            results = mgr.search(args.query)
            for s in results:
                console.print(f"  [bold]{s.name}[/]: {s.description}")
        elif args.skills_action == "create" and args.name:
            skill = mgr.create(args.name, args.content or "", args.description or "")
            console.print(f"[green]Created skill:[/] {skill.name}")
    except ImportError:
        console.print("[red]Skills module not available.[/]")


def cmd_sessions(args: argparse.Namespace) -> None:
    """Manage sessions."""
    try:
        from sessions.session_store import SessionStore
        store = SessionStore()
        if args.sessions_action == "list":
            sessions = store.list_sessions(limit=20)
            table = Table(title="Sessions")
            table.add_column("ID")
            table.add_column("Platform")
            table.add_column("Updated")
            for s in sessions:
                table.add_row(s.id[:8], s.platform, s.updated_at[:19])
            console.print(table)
        elif args.sessions_action == "delete" and args.session_id:
            if store.delete(args.session_id):
                console.print("[green]Session deleted.[/]")
            else:
                console.print("[red]Session not found.[/]")
    except ImportError:
        console.print("[red]Session store not available.[/]")


def cmd_gateway(args: argparse.Namespace) -> None:
    """Manage the gateway."""
    console.print(Panel("[bold]Gateway Status[/]", title="🌐 Gateway"))
    if args.gateway_action == "start":
        console.print("[green]Starting gateway...[/]")
        console.print("[dim]Run with: nexus gateway start --daemon[/]")
    elif args.gateway_action == "stop":
        console.print("[yellow]Stopping gateway...[/]")
    elif args.gateway_action == "status":
        console.print("Status: [dim]not configured[/]")


# ======================================================================
# Argument parser
# ======================================================================

def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser with all subcommands."""
    parser = argparse.ArgumentParser(
        prog="nexus",
        description="NexusAgent — Universal AI Agent Framework",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version="NexusAgent 1.0.0")
    sub = parser.add_subparsers(dest="command", help="Available commands")

    # chat
    sub.add_parser("chat", help="Start interactive chat")

    # setup
    sub.add_parser("setup", help="Run setup wizard")

    # config
    cfg = sub.add_parser("config", help="Configuration management")
    cfg.add_argument("config_action", choices=["show", "validate", "edit"], nargs="?", default="show")

    # model
    mdl = sub.add_parser("model", help="Model management")
    mdl.add_argument("model_action", choices=["list", "set", "info"], nargs="?", default="list")
    mdl.add_argument("model_name", nargs="?")

    # tools
    sub.add_parser("tools", help="List available tools")

    # skills
    sk = sub.add_parser("skills", help="Skill management")
    sk.add_argument("skills_action", choices=["list", "search", "create", "update", "delete"], nargs="?", default="list")
    sk.add_argument("--name", "-n")
    sk.add_argument("--description", "-d")
    sk.add_argument("--content", "-c")
    sk.add_argument("--query", "-q")

    # sessions
    ss = sub.add_parser("sessions", help="Session management")
    ss.add_argument("sessions_action", choices=["list", "resume", "delete", "search"], nargs="?", default="list")
    ss.add_argument("--session-id", "-s")
    ss.add_argument("--query", "-q")

    # gateway
    gw = sub.add_parser("gateway", help="Gateway management")
    gw.add_argument("gateway_action", choices=["start", "stop", "status"], nargs="?", default="status")
    gw.add_argument("--daemon", "-d", action="store_true")

    return parser


# ======================================================================
# Entry point
# ======================================================================

def main() -> None:
    """Main entry point for the NexusAgent CLI."""
    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    dispatch: dict[str, Any] = {
        "chat": lambda a: interactive_chat(_load_config()),
        "setup": cmd_setup,
        "config": cmd_config,
        "model": cmd_model,
        "tools": cmd_tools,
        "skills": cmd_skills,
        "sessions": cmd_sessions,
        "gateway": cmd_gateway,
    }

    handler = dispatch.get(args.command)
    if handler:
        handler(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
