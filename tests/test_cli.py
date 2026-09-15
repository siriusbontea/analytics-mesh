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


def test_cli_query_and_receipt(tmp_path: Path, data_dir: Path):
    cfg = NodeConfig(
        node_id="cli-node",
        artifact_dir=tmp_path / "artifacts",
        receipt_db=tmp_path / "receipts.sqlite",
        connectors=[ConnectorConfig(id="local_files", type="local_files", root=data_dir)],
        limits=LimitsConfig(default_row_limit=100, max_row_limit=1000, query_timeout_seconds=10),
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
    finally:
        server.should_exit = True
        thread.join(timeout=5)
