import typer

from cctop.duration import parse_duration
from cctop.hooks.install import install_hooks, uninstall_hooks

app = typer.Typer(help="cctop — monitor Claude Code sessions in real-time")


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    recent: str = typer.Option("0", help="Include sessions ended within this duration (e.g. 30m, 1h, 2h, 1d)"),
) -> None:
    """Launch the cctop TUI."""
    if ctx.invoked_subcommand is None:
        from cctop.app import CctopApp

        recent_td = parse_duration(recent)
        cctop_app = CctopApp(recent=recent_td)
        cctop_app.run()


@app.command()
def install() -> None:
    """Install cctop hooks into Claude Code settings."""
    try:
        install_hooks()
        typer.echo("Hooks installed. Restart your Claude Code sessions for hooks to take effect.")
    except RuntimeError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc


@app.command()
def uninstall() -> None:
    """Remove cctop hooks and clean up."""
    uninstall_hooks()
    typer.echo("cctop hooks removed and data cleaned up.")
