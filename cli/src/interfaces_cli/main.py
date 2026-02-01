"""Phi CLI - Hacker-style CLI for Physical AI Framework.

Usage:
    phi           # Launch interactive menu
    phi health    # Check backend health
    phi profiles  # List profile instances
"""

import logging
import os
import sys
from typing import Optional

import typer

from interfaces_cli.core.logging import setup_file_logging

# Configure logging for CLI with console and file output
log_level = os.environ.get("PHI_LOG_LEVEL", "WARNING").upper()
console_level = getattr(logging, log_level, logging.WARNING)
setup_file_logging(app_name="cli", console_level=console_level)
# Set specific loggers to DEBUG when verbose
if log_level == "DEBUG":
    logging.getLogger("interfaces_cli").setLevel(logging.DEBUG)
from rich import print as rprint

from interfaces_cli.client import PhiClient

# Typer app for direct commands
cli = typer.Typer(
    help="Physical AI CLI - Hacker-style interface for robot control",
    invoke_without_command=True,
    no_args_is_help=False,
)


@cli.callback()
def main_callback(ctx: typer.Context):
    """Launch interactive menu if no command specified."""
    if ctx.invoked_subcommand is None:
        # No subcommand - launch interactive mode
        run_interactive()


def run_interactive(backend_url: Optional[str] = None) -> None:
    """Run the interactive menu-based CLI."""
    try:
        from interfaces_cli.app import PhiApplication

        app = PhiApplication(backend_url=backend_url)
        app.run()
    except KeyboardInterrupt:
        print("\nExiting...")
        sys.exit(0)
    except Exception as e:
        rprint(f"[red]Error: {e}[/red]")
        sys.exit(1)


@cli.command()
def health():
    """Check backend health."""
    client = PhiClient()
    try:
        result = client.health()
        rprint(f"[green]Backend status: {result['status']}[/green]")
    except Exception as e:
        rprint(f"[red]Backend unreachable: {e}[/red]")
        raise typer.Exit(1)


@cli.command()
def profiles():
    """List profile instances."""
    client = PhiClient()
    try:
        result = client.list_profile_instances()
        instances = result.get("instances", [])
        if instances:
            rprint("[green]Profile Instances:[/green]")
            for inst in instances:
                name = inst.get("name") or "active"
                inst_id = inst.get("id", "")
                class_key = inst.get("class_key", "")
                rprint(f"  - {name} ({class_key}) {inst_id}")
        else:
            rprint("[yellow]No profile instances found[/yellow]")
    except Exception as e:
        rprint(f"[red]Error listing profiles: {e}[/red]")
        raise typer.Exit(1)


@cli.command()
def devices():
    """List connected devices."""
    client = PhiClient()
    try:
        result = client.list_devices()
        device_list = result.get("devices", [])
        if device_list:
            rprint("[green]Devices:[/green]")
            for d in device_list:
                rprint(f"  - {d.get('id', 'unknown')}: {d.get('type', 'unknown')}")
        else:
            rprint("[yellow]No devices connected[/yellow]")
    except Exception as e:
        rprint(f"[red]Error listing devices: {e}[/red]")
        raise typer.Exit(1)


@cli.command()
def info():
    """Show system information."""
    client = PhiClient()
    try:
        result = client.get_system_info()
        rprint("[green]System Info:[/green]")
        for key, value in result.items():
            rprint(f"  {key}: {value}")
    except Exception as e:
        rprint(f"[red]Error getting system info: {e}[/red]")
        raise typer.Exit(1)


def main():
    """Main entry point."""
    cli()


if __name__ == "__main__":
    main()
