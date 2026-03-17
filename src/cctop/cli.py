import typer

app = typer.Typer(help="cctop — monitor Claude Code sessions in real-time")


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    recent: str = typer.Option("0", help="Include sessions ended within this duration (e.g. 30m, 1h, 2h, 1d)"),
) -> None:
    """Launch the cctop TUI."""
    if ctx.invoked_subcommand is None:
        typer.echo(f"cctop TUI would launch here (recent={recent})")


@app.command()
def install() -> None:
    """Install cctop hooks into Claude Code settings."""
    typer.echo("install placeholder")


@app.command()
def uninstall() -> None:
    """Remove cctop hooks and clean up."""
    typer.echo("uninstall placeholder")
