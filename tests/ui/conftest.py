from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_healthy(url: str, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            response = httpx.get(f"{url}/health", timeout=1.0)
            if response.status_code == 200 and response.json().get("status") == "ok":
                return
        except httpx.HTTPError as exc:
            last_error = exc
        time.sleep(0.2)
    raise RuntimeError(f"temp node at {url}/health did not become ready: {last_error}")


@pytest.fixture(scope="session")
def browser_type_launch_args(browser_type_launch_args: dict) -> dict:
    args = list(browser_type_launch_args.get("args") or [])
    for extra in ("--disable-dev-shm-usage", "--no-sandbox"):
        if extra not in args:
            args.append(extra)
    return {**browser_type_launch_args, "args": args}


@pytest.fixture(scope="session")
def live_node(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    """Hermetic node on an ephemeral port (same shape as scripts/deep-smoke.sh --start)."""
    tmp_dir = tmp_path_factory.mktemp("mesh-ui-node")
    port = _free_port()
    config_path = tmp_dir / "node.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "node_id": "ui-test-node",
                "artifact_dir": str(tmp_dir / "artifacts"),
                "receipt_db": str(tmp_dir / "receipts.sqlite"),
                "identity_key_path": str(tmp_dir / "identity.pem"),
                "listen_host": "127.0.0.1",
                "listen_port": port,
                "connectors": [
                    {
                        "id": "local_files",
                        "type": "local_files",
                        "root": str(REPO / "data" / "samples"),
                        "labels": ["personal"],
                    }
                ],
                "analytics_dir": str(REPO / "analytics"),
                "policy_path": str(REPO / "configs" / "examples" / "policy.yaml"),
                "limits": {
                    "default_row_limit": 10000,
                    "max_row_limit": 100000,
                    "query_timeout_seconds": 30,
                },
            }
        ),
        encoding="utf-8",
    )
    log_path = tmp_dir / "serve.log"
    log_file = log_path.open("w", encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, "-m", "mesh_client", "serve", "--config", str(config_path)],
        cwd=str(REPO),
        stdout=log_file,
        stderr=subprocess.STDOUT,
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
        start_new_session=True,
    )
    base_url = f"http://127.0.0.1:{port}"
    try:
        try:
            _wait_healthy(base_url)
        except Exception:
            log_file.flush()
            if log_path.exists():
                sys.stderr.write(log_path.read_text(encoding="utf-8"))
            raise
        yield base_url
    finally:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.wait(timeout=5)
        log_file.close()
