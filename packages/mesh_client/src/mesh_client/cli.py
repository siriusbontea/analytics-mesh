from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import httpx
import typer
import uvicorn

app = typer.Typer(name="mesh", help="Analytics Mesh CLI: serve, query, and inspect receipts.", no_args_is_help=True)


def _print_json(payload: object) -> None:
    typer.echo(json.dumps(payload, indent=2, default=str))


@app.command()
def serve(
    config: Path = typer.Option(Path("configs/examples/node.yaml"), "--config", "-c", help="Node YAML config"),
    host: Optional[str] = typer.Option(None, "--host", help="Override listen host"),
    port: Optional[int] = typer.Option(None, "--port", help="Override listen port"),
) -> None:
    """Start a local node that serves files and runs sandboxed SQL."""
    from mesh_node.app import create_app
    from mesh_node.config import load_config

    cfg = load_config(config)
    listen_host = host or cfg.listen_host
    listen_port = port or cfg.listen_port
    typer.echo(f"serving node {cfg.node_id} on http://{listen_host}:{listen_port}")
    uvicorn.run(create_app(cfg), host=listen_host, port=listen_port, log_level="info")


@app.command()
def health(url: str = typer.Option("http://127.0.0.1:8080", "--url")) -> None:
    """Show node health."""
    response = httpx.get(f"{url.rstrip('/')}/health", timeout=10.0)
    response.raise_for_status()
    _print_json(response.json())


@app.command()
def connectors(url: str = typer.Option("http://127.0.0.1:8080", "--url")) -> None:
    """List connectors and discovered tables."""
    response = httpx.get(f"{url.rstrip('/')}/connectors", timeout=10.0)
    response.raise_for_status()
    _print_json(response.json())


@app.command()
def query(
    sql: Optional[str] = typer.Option(None, "--sql", help="SELECT / WITH query"),
    sql_file: Optional[Path] = typer.Option(None, "--sql-file", help="Read SQL from a file"),
    url: str = typer.Option("http://127.0.0.1:8080", "--url"),
    row_limit: Optional[int] = typer.Option(None, "--row-limit"),
    principal: str = typer.Option("local", "--principal"),
    out: Optional[Path] = typer.Option(None, "--out", help="Write the Parquet artifact to this path"),
) -> None:
    """Run sandboxed SQL on the node and print the artifact + receipt."""
    if bool(sql) == bool(sql_file):
        raise typer.BadParameter("provide exactly one of --sql or --sql-file")
    statement = sql if sql is not None else sql_file.read_text()  # type: ignore[union-attr]
    payload: dict[str, object] = {"sql": statement, "principal": principal}
    if row_limit is not None:
        payload["row_limit"] = row_limit
    response = httpx.post(f"{url.rstrip('/')}/query", json=payload, timeout=60.0)
    if response.status_code >= 400:
        try:
            _print_json(response.json())
        except json.JSONDecodeError:
            typer.echo(response.text)
        raise typer.Exit(code=1)
    body = response.json()
    _print_json(body)
    if out is not None and body.get("artifact"):
        artifact_id = body["artifact"]["artifact_id"]
        download = httpx.get(f"{url.rstrip('/')}/results/{artifact_id}", timeout=60.0)
        download.raise_for_status()
        out.write_bytes(download.content)
        typer.echo(f"wrote {out}")


@app.command()
def receipt(
    receipt_id: str = typer.Argument(..., help="Receipt id from a query"),
    url: str = typer.Option("http://127.0.0.1:8080", "--url"),
    verify_chain: bool = typer.Option(False, "--verify-chain", help="Also print hash-chain verification"),
) -> None:
    """Fetch a receipt by id."""
    response = httpx.get(f"{url.rstrip('/')}/receipts/{receipt_id}", timeout=10.0)
    if response.status_code == 404:
        typer.echo("receipt not found", err=True)
        raise typer.Exit(code=1)
    response.raise_for_status()
    _print_json(response.json())
    if verify_chain:
        chain = httpx.get(f"{url.rstrip('/')}/receipts/chain", timeout=10.0)
        chain.raise_for_status()
        _print_json(chain.json())


def main() -> None:
    app()


if __name__ == "__main__":
    main()
