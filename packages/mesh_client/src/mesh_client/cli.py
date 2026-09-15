from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import httpx
import typer
import uvicorn

app = typer.Typer(
    name="mesh",
    help="Analytics Mesh CLI: serve a node or plane, query, and inspect receipts.",
    no_args_is_help=True,
)


def _print_json(payload: object) -> None:
    typer.echo(json.dumps(payload, indent=2, default=str))


def _print_http_error(response: httpx.Response) -> None:
    try:
        _print_json(response.json())
    except json.JSONDecodeError:
        typer.echo(response.text)


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


@app.command("plane")
def serve_plane(
    config: Path = typer.Option(Path("configs/examples/plane.yaml"), "--config", "-c", help="Plane YAML config"),
    host: Optional[str] = typer.Option(None, "--host", help="Override listen host"),
    port: Optional[int] = typer.Option(None, "--port", help="Override listen port"),
) -> None:
    """Start the thin control plane (node registry + job routing)."""
    from mesh_plane.app import create_app
    from mesh_plane.config import load_config

    cfg = load_config(config)
    listen_host = host or cfg.listen_host
    listen_port = port or cfg.listen_port
    typer.echo(f"serving plane {cfg.plane_id} on http://{listen_host}:{listen_port}")
    uvicorn.run(create_app(cfg), host=listen_host, port=listen_port, log_level="info")


@app.command()
def pair(
    config: Optional[Path] = typer.Option(None, "--config", "-c", help="Node YAML config"),
    node_id: Optional[str] = typer.Option(None, "--node-id", help="Node id when not using --config"),
    identity_key: Optional[Path] = typer.Option(None, "--identity-key", help="Ed25519 PEM path"),
    url: str = typer.Option("http://127.0.0.1:8090", "--url", help="Control plane URL"),
    token: Optional[str] = typer.Option(None, "--token", help="Registration token"),
    endpoint: Optional[str] = typer.Option(None, "--endpoint", help="How the plane should reach this node"),
) -> None:
    """Register this node with the control plane (demo pairing token)."""
    if config is not None:
        from mesh_node.config import load_config
        from mesh_node.pairing import register_with_plane
        from mesh_node.runtime import NodeRuntime

        cfg = load_config(config)
        runtime = NodeRuntime(cfg)
        try:
            body = register_with_plane(runtime, cfg, plane_url=url, token=token, endpoint=endpoint)
        except httpx.HTTPStatusError as exc:
            _print_http_error(exc.response)
            raise typer.Exit(code=1) from exc
        _print_json(body)
        return

    if not node_id or identity_key is None or not token or not endpoint:
        raise typer.BadParameter("provide --config, or --node-id, --identity-key, --token, and --endpoint")

    from mesh_common.identity import build_registration, load_or_create_keypair

    keys = load_or_create_keypair(identity_key, node_id)
    payload = build_registration(keys, endpoint=endpoint, token=token)
    response = httpx.post(f"{url.rstrip('/')}/nodes/register", json=payload, timeout=10.0)
    if response.status_code >= 400:
        _print_http_error(response)
        raise typer.Exit(code=1)
    _print_json(response.json())


@app.command()
def nodes(url: str = typer.Option("http://127.0.0.1:8090", "--url", help="Control plane URL")) -> None:
    """List nodes registered with the control plane."""
    response = httpx.get(f"{url.rstrip('/')}/nodes", timeout=10.0)
    response.raise_for_status()
    _print_json(response.json())


@app.command()
def jobs(url: str = typer.Option("http://127.0.0.1:8090", "--url", help="Control plane URL")) -> None:
    """List plane job records (metadata and pointers only)."""
    response = httpx.get(f"{url.rstrip('/')}/jobs", timeout=10.0)
    response.raise_for_status()
    _print_json(response.json())


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
    node: Optional[str] = typer.Option(None, "--node", help="Target node id when talking to the control plane"),
    row_limit: Optional[int] = typer.Option(None, "--row-limit"),
    principal: str = typer.Option("local", "--principal"),
    out: Optional[Path] = typer.Option(None, "--out", help="Write the Parquet artifact to this path"),
) -> None:
    """Run sandboxed SQL on a node (directly or via the plane)."""
    if bool(sql) == bool(sql_file):
        raise typer.BadParameter("provide exactly one of --sql or --sql-file")
    statement = sql if sql is not None else sql_file.read_text()  # type: ignore[union-attr]
    payload: dict[str, object] = {"sql": statement, "principal": principal}
    if row_limit is not None:
        payload["row_limit"] = row_limit
    if node is not None:
        payload["node_id"] = node
    response = httpx.post(f"{url.rstrip('/')}/query", json=payload, timeout=60.0)
    if response.status_code >= 400:
        _print_http_error(response)
        raise typer.Exit(code=1)
    body = response.json()
    _print_json(body)
    if out is not None and body.get("artifact"):
        if node is not None and body.get("job"):
            download = httpx.get(f"{url.rstrip('/')}/jobs/{body['job']['job_id']}/result", timeout=60.0)
        else:
            artifact_id = body["artifact"]["artifact_id"]
            download = httpx.get(f"{url.rstrip('/')}/results/{artifact_id}", timeout=60.0)
        download.raise_for_status()
        out.write_bytes(download.content)
        typer.echo(f"wrote {out}")


@app.command()
def receipt(
    receipt_id: str = typer.Argument(..., help="Receipt id from a query"),
    url: str = typer.Option("http://127.0.0.1:8080", "--url"),
    node: Optional[str] = typer.Option(None, "--node", help="Owning node id when fetching via the plane"),
    verify_chain: bool = typer.Option(False, "--verify-chain", help="Also print hash-chain verification"),
) -> None:
    """Fetch a receipt by id (verified on the owning node)."""
    if node is not None:
        receipt_url = f"{url.rstrip('/')}/nodes/{node}/receipts/{receipt_id}"
        chain_url = f"{url.rstrip('/')}/nodes/{node}/receipts/chain"
    else:
        receipt_url = f"{url.rstrip('/')}/receipts/{receipt_id}"
        chain_url = f"{url.rstrip('/')}/receipts/chain"
    response = httpx.get(receipt_url, timeout=10.0)
    if response.status_code == 404:
        typer.echo("receipt not found", err=True)
        raise typer.Exit(code=1)
    response.raise_for_status()
    body = response.json()
    _print_json(body)
    if verify_chain:
        if node is None and "node_id" in body:
            chain_url = f"{url.rstrip('/')}/nodes/{body['node_id']}/receipts/chain"
        try:
            chain = httpx.get(chain_url, timeout=10.0)
            chain.raise_for_status()
            _print_json(chain.json())
        except httpx.HTTPError:
            if node is None and "node_id" not in body:
                raise
            # Plane has no global chain; verification stays on the owning node.
            owning = body.get("node_id")
            if owning:
                chain = httpx.get(f"{url.rstrip('/')}/nodes/{owning}/receipts/chain", timeout=10.0)
                chain.raise_for_status()
                _print_json(chain.json())
            else:
                raise


def main() -> None:
    app()


if __name__ == "__main__":
    main()
