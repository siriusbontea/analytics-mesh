from __future__ import annotations

import json
import threading
from pathlib import Path

import uvicorn
from typer.testing import CliRunner

from mesh_client.cli import app
from mesh_node.app import create_app
from mesh_node.config import ConnectorConfig, LimitsConfig, NodeConfig


def test_cli_help():
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "serve" in result.stdout
    assert "query" in result.stdout
    assert "receipt" in result.stdout
    assert "plane" in result.stdout
    assert "nodes" in result.stdout
    assert "pair" in result.stdout
    assert "jobs" in result.stdout
    assert "analytics" in result.stdout
    assert "assist" in result.stdout


def test_cli_query_and_receipt(tmp_path: Path, data_dir: Path):
    cfg = NodeConfig(
        node_id="cli-node",
        artifact_dir=tmp_path / "artifacts",
        receipt_db=tmp_path / "receipts.sqlite",
        connectors=[ConnectorConfig(id="local_files", type="local_files", root=data_dir)],
        limits=LimitsConfig(default_row_limit=100, max_row_limit=1000, query_timeout_seconds=10),
        analytics_dir=Path(__file__).resolve().parents[1] / "analytics",
    )
    server_app = create_app(cfg)
    server = uvicorn.Server(uvicorn.Config(server_app, host="127.0.0.1", port=0, log_level="error"))

    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        for _ in range(50):
            if server.started:
                break
            thread.join(0.05)
        assert server.started
        port = server.servers[0].sockets[0].getsockname()[1]
        url = f"http://127.0.0.1:{port}"
        runner = CliRunner()

        health = runner.invoke(app, ["health", "--url", url])
        assert health.exit_code == 0
        assert "ok" in health.stdout

        query = runner.invoke(
            app,
            ["query", "--url", url, "--sql", "SELECT product FROM sales"],
        )
        assert query.exit_code == 0
        payload = json.loads(query.stdout)
        receipt_id = payload["receipt"]["receipt_id"]
        assert receipt_id

        receipt = runner.invoke(app, ["receipt", receipt_id, "--url", url])
        assert receipt.exit_code == 0
        assert receipt_id in receipt.stdout
        assert "succeeded" in receipt.stdout

        listed = runner.invoke(app, ["analytics", "list", "--url", url])
        assert listed.exit_code == 0, listed.stdout
        listed_body = json.loads(listed.stdout)
        assert {item["analytic_id"] for item in listed_body["analytics"]} >= {"top_products"}

        ran = runner.invoke(app, ["analytics", "run", "top_products", "--url", url])
        assert ran.exit_code == 0, ran.stdout
        ran_body = json.loads(ran.stdout)
        assert ran_body["receipt"]["action"] == "run_analytic"
        assert ran_body["receipt"]["model_provider"] is None
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def _start_server(server_app, host: str = "127.0.0.1") -> tuple[uvicorn.Server, threading.Thread, str]:
    server = uvicorn.Server(uvicorn.Config(server_app, host=host, port=0, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(50):
        if server.started:
            break
        thread.join(0.05)
    assert server.started
    port = server.servers[0].sockets[0].getsockname()[1]
    return server, thread, f"http://127.0.0.1:{port}"


def test_cli_query_via_plane_targets_node_b(tmp_path: Path, sales_csv_text: str):
    from mesh_node.app import create_app as create_node_app
    from mesh_plane.app import create_app as create_plane_app
    from mesh_plane.config import PlaneConfig

    node_b_data = tmp_path / "data-b"
    node_b_data.mkdir()
    (node_b_data / "sales.csv").write_text(
        "order_id,product,region,amount,sold_on\n"
        "1,babylon-sprocket,west,99.0,2026-02-01\n"
    )
    node_a = NodeConfig(
        node_id="node-a",
        artifact_dir=tmp_path / "artifacts-a",
        receipt_db=tmp_path / "receipts-a.sqlite",
        identity_key_path=tmp_path / "node-a.ed25519",
        connectors=[ConnectorConfig(id="local_files", type="local_files", root=tmp_path / "data-a")],
        limits=LimitsConfig(default_row_limit=100, max_row_limit=1000, query_timeout_seconds=10),
    )
    (tmp_path / "data-a").mkdir()
    (tmp_path / "data-a" / "sales.csv").write_text(sales_csv_text)
    node_b = NodeConfig(
        node_id="node-b",
        artifact_dir=tmp_path / "artifacts-b",
        receipt_db=tmp_path / "receipts-b.sqlite",
        identity_key_path=tmp_path / "node-b.ed25519",
        connectors=[ConnectorConfig(id="local_files", type="local_files", root=node_b_data)],
        limits=LimitsConfig(default_row_limit=100, max_row_limit=1000, query_timeout_seconds=10),
    )
    plane_cfg = PlaneConfig(plane_id="cli-plane", registration_token="demo-pair-token", store_path=tmp_path / "plane.sqlite")

    servers: list[tuple[uvicorn.Server, threading.Thread]] = []
    try:
        server_a, thread_a, url_a = _start_server(create_node_app(node_a))
        server_b, thread_b, url_b = _start_server(create_node_app(node_b))
        server_p, thread_p, url_p = _start_server(create_plane_app(plane_cfg))
        servers.extend([(server_a, thread_a), (server_b, thread_b), (server_p, thread_p)])
        runner = CliRunner()

        pair_a = runner.invoke(
            app,
            [
                "pair",
                "--node-id",
                "node-a",
                "--identity-key",
                str(tmp_path / "node-a.ed25519"),
                "--url",
                url_p,
                "--token",
                "demo-pair-token",
                "--endpoint",
                url_a,
            ],
        )
        pair_b = runner.invoke(
            app,
            [
                "pair",
                "--node-id",
                "node-b",
                "--identity-key",
                str(tmp_path / "node-b.ed25519"),
                "--url",
                url_p,
                "--token",
                "demo-pair-token",
                "--endpoint",
                url_b,
            ],
        )
        assert pair_a.exit_code == 0, pair_a.stdout
        assert pair_b.exit_code == 0, pair_b.stdout

        nodes = runner.invoke(app, ["nodes", "--url", url_p])
        assert nodes.exit_code == 0
        listed = json.loads(nodes.stdout)
        assert {item["node_id"] for item in listed["nodes"]} == {"node-a", "node-b"}

        query = runner.invoke(
            app,
            ["query", "--url", url_p, "--node", "node-b", "--sql", "SELECT product FROM sales"],
        )
        assert query.exit_code == 0, query.stdout
        payload = json.loads(query.stdout)
        assert payload["job"]["node_id"] == "node-b"
        assert payload["job"]["status"] == "succeeded"
        assert payload["receipt"]["node_id"] == "node-b"
        receipt_id = payload["receipt"]["receipt_id"]

        jobs = runner.invoke(app, ["jobs", "--url", url_p])
        assert jobs.exit_code == 0
        assert receipt_id in jobs.stdout

        receipt = runner.invoke(app, ["receipt", receipt_id, "--url", url_p])
        assert receipt.exit_code == 0
        assert receipt_id in receipt.stdout
        assert "succeeded" in receipt.stdout
    finally:
        for server, thread in servers:
            server.should_exit = True
            thread.join(timeout=5)
