from __future__ import annotations

import json
from pathlib import Path
from typing import Literal, Optional

import httpx
import typer
import uvicorn

app = typer.Typer(
    name="mesh",
    help="Analytics Mesh CLI: serve a node or plane, query, run analytics, MCP, propose SQL, and inspect receipts.",
    no_args_is_help=True,
)
analytics_app = typer.Typer(help="List and run registered analytics.")
app.add_typer(analytics_app, name="analytics")


@app.command()
def assist(
    question: Optional[str] = typer.Option(None, "--question", "-q", help="Natural-language question → proposed SQL"),
    explain: Optional[str] = typer.Option(None, "--explain", help="Artifact id to explain (auxiliary model)"),
    url: str = typer.Option("http://127.0.0.1:8080", "--url"),
    node: Optional[str] = typer.Option(None, "--node", help="Target node id when talking to the control plane"),
    principal: str = typer.Option("local", "--principal"),
    confirm_run: bool = typer.Option(
        False,
        "--confirm-run",
        help="After proposing SQL, run it. Never implied; omit this flag to only print the proposal.",
    ),
) -> None:
    """Propose SQL from a question, or explain a result. Never auto-executes SQL."""
    if bool(question) == bool(explain):
        raise typer.BadParameter("provide exactly one of --question or --explain")
    if explain is not None:
        payload: dict[str, object] = {"artifact_id": explain, "principal": principal}
        if node is not None:
            path = f"/nodes/{node}/assist/explain"
        else:
            path = "/assist/explain"
        response = httpx.post(f"{url.rstrip('/')}{path}", json=payload, timeout=60.0)
        if response.status_code >= 400:
            _print_http_error(response)
            raise typer.Exit(code=1)
        _print_json(response.json())
        return

    payload = {"question": question, "principal": principal}
    if node is not None:
        path = f"/nodes/{node}/assist/nl2sql"
    else:
        path = "/assist/nl2sql"
    response = httpx.post(f"{url.rstrip('/')}{path}", json=payload, timeout=60.0)
    if response.status_code >= 400:
        _print_http_error(response)
        raise typer.Exit(code=1)
    body = response.json()
    _print_json(body)
    if not confirm_run:
        typer.echo("Not run. Re-invoke with --confirm-run after you have reviewed the SQL.", err=True)
        return
    sql = body.get("sql")
    if not sql:
        typer.echo("No SQL to confirm.", err=True)
        raise typer.Exit(code=1)
    query_payload: dict[str, object] = {
        "sql": sql,
        "principal": principal,
        "assist_model_provider": body.get("model_provider"),
        "assist_model_id": body.get("model_id"),
    }
    if node is not None:
        query_payload["node_id"] = node
    ran = httpx.post(f"{url.rstrip('/')}/query", json=query_payload, timeout=60.0)
    if ran.status_code >= 400:
        _print_http_error(ran)
        raise typer.Exit(code=1)
    _print_json(ran.json())


def _print_json(payload: object) -> None:
    typer.echo(json.dumps(payload, indent=2, default=str))


def _print_http_error(response: httpx.Response) -> None:
    try:
        _print_json(response.json())
    except json.JSONDecodeError:
        typer.echo(response.text)


def target_kind_from_health(health: object) -> Literal["node", "plane"]:
    """Classify a /health body. Plane has plane_id; a node has node_id."""
    if isinstance(health, dict) and health.get("plane_id"):
        return "plane"
    return "node"


def chain_path(
    *,
    target: Literal["node", "plane"],
    node: Optional[str],
    owning_node_id: Optional[str],
) -> str:
    """Hash-chain URL path. Nodes expose /receipts/chain; the plane proxies /nodes/{id}/..."""
    if node:
        return f"/nodes/{node}/receipts/chain"
    if target == "plane":
        if not owning_node_id:
            raise ValueError("plane chain verification requires a node id")
        return f"/nodes/{owning_node_id}/receipts/chain"
    return "/receipts/chain"


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
    typer.echo(f"web UI: http://{listen_host}:{listen_port}/ui")
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
    typer.echo(f"web UI: http://{listen_host}:{listen_port}/ui (pick a registered node)")
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
    """Register this node with the control plane (shared pairing token)."""
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
        except ValueError as exc:
            raise typer.BadParameter(str(exc)) from exc
        _print_json(body)
        return

    from mesh_common.secrets import resolve_pair_token

    if not node_id or identity_key is None or not endpoint:
        raise typer.BadParameter(
            "provide --config, or --node-id, --identity-key, --endpoint, and --token (or MESH_PAIR_TOKEN)"
        )
    try:
        token = resolve_pair_token(configured=token, override=token)
    except ValueError as exc:
        raise typer.BadParameter(
            "provide --config, or --node-id, --identity-key, --endpoint, and --token (or MESH_PAIR_TOKEN)"
        ) from exc

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
def mcp(
    url: str = typer.Option("http://127.0.0.1:8080", "--url", envvar="MESH_URL", help="Node or plane URL"),
    node: Optional[str] = typer.Option(None, "--node", envvar="MESH_NODE", help="Target node id when talking to the plane"),
    principal: str = typer.Option("local", "--principal", envvar="MESH_PRINCIPAL"),
    transport: str = typer.Option(
        "stdio",
        "--transport",
        help="stdio (desktop MCP clients), http (JSON /tools), or streamable-http (MCP HTTP)",
    ),
    host: str = typer.Option("127.0.0.1", "--host", envvar="MESH_MCP_HOST"),
    port: int = typer.Option(8765, "--port", envvar="MESH_MCP_PORT"),
) -> None:
    """Start the analytics-only MCP adapter (list_analytics / run_analytic / get_receipt)."""
    from mesh_mcp.server import run_server

    if transport == "http":
        typer.echo(f"MCP HTTP on http://{host}:{port} (tools at /tools, POST /tools/{{name}})")
        typer.echo(f"upstream mesh: {url}" + (f" node={node}" if node else ""))
    run_server(url=url, principal=principal, node_id=node, transport=transport, host=host, port=port)


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
    base = url.rstrip("/")
    if node is not None:
        receipt_url = f"{base}/nodes/{node}/receipts/{receipt_id}"
    else:
        receipt_url = f"{base}/receipts/{receipt_id}"
    response = httpx.get(receipt_url, timeout=10.0)
    if response.status_code == 404:
        typer.echo("receipt not found", err=True)
        raise typer.Exit(code=1)
    if response.status_code >= 400:
        _print_http_error(response)
        raise typer.Exit(code=1)
    body = response.json()
    _print_json(body)
    if not verify_chain:
        return
    try:
        health = httpx.get(f"{base}/health", timeout=10.0)
        health.raise_for_status()
        target = target_kind_from_health(health.json())
        owning = node or (body.get("node_id") if isinstance(body, dict) else None)
        path = chain_path(target=target, node=node, owning_node_id=owning if isinstance(owning, str) else None)
        chain = httpx.get(f"{base}{path}", timeout=10.0)
        chain.raise_for_status()
    except (httpx.HTTPError, ValueError, json.JSONDecodeError) as exc:
        typer.echo(f"chain verification failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    chain_body = chain.json()
    _print_json(chain_body)
    if not isinstance(chain_body, dict) or chain_body.get("valid") is not True:
        typer.echo("receipt chain is not valid", err=True)
        raise typer.Exit(code=1)


@analytics_app.command("list")
def analytics_list(
    url: str = typer.Option("http://127.0.0.1:8080", "--url"),
    node: Optional[str] = typer.Option(None, "--node", help="Target node id when talking to the control plane"),
) -> None:
    """List versioned analytics registered on a node."""
    path = f"/nodes/{node}/analytics" if node is not None else "/analytics"
    response = httpx.get(f"{url.rstrip('/')}{path}", timeout=10.0)
    if response.status_code >= 400:
        _print_http_error(response)
        raise typer.Exit(code=1)
    _print_json(response.json())


@analytics_app.command("run")
def analytics_run(
    analytic_id: str = typer.Argument(..., help="Registered analytic id"),
    url: str = typer.Option("http://127.0.0.1:8080", "--url"),
    node: Optional[str] = typer.Option(None, "--node", help="Target node id when talking to the control plane"),
    version: Optional[str] = typer.Option(None, "--version", help="Pin a semver; default is latest"),
    row_limit: Optional[int] = typer.Option(None, "--row-limit"),
    principal: str = typer.Option("local", "--principal"),
    out: Optional[Path] = typer.Option(None, "--out", help="Write the Parquet artifact to this path"),
) -> None:
    """Run a registered analytic by id (not ad-hoc SQL)."""
    payload: dict[str, object] = {"analytic_id": analytic_id, "principal": principal}
    if version is not None:
        payload["version"] = version
    if row_limit is not None:
        payload["row_limit"] = row_limit
    if node is not None:
        payload["node_id"] = node
    response = httpx.post(f"{url.rstrip('/')}/analytics/run", json=payload, timeout=60.0)
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


def main() -> None:
    app()


if __name__ == "__main__":
    main()
