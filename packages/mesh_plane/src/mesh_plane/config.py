from __future__ import annotations

import os
from pathlib import Path

import yaml
from pydantic import BaseModel

from mesh_common.secrets import resolve_pair_token


class PlaneConfig(BaseModel):
    plane_id: str = "home-plane"
    registration_token: str = "demo-pair-token"
    pair_token_env: str | None = None
    store_path: Path = Path("var/plane/plane.sqlite")
    listen_host: str = "127.0.0.1"
    listen_port: int = 8090

    def resolve_paths(self, base: Path) -> PlaneConfig:
        store = self.store_path if self.store_path.is_absolute() else (base / self.store_path).resolve()
        return self.model_copy(update={"store_path": store})

    def resolved_registration_token(self) -> str:
        return resolve_pair_token(self.registration_token, pair_token_env=self.pair_token_env)

    def resolved_listen_host(self) -> str:
        return os.environ.get("MESH_LISTEN_HOST") or self.listen_host

    def resolved_listen_port(self) -> int:
        raw = os.environ.get("MESH_LISTEN_PORT")
        return int(raw) if raw else self.listen_port


def load_config(path: Path | str) -> PlaneConfig:
    config_path = Path(path)
    raw = yaml.safe_load(config_path.read_text()) or {}
    return PlaneConfig.model_validate(raw).resolve_paths(Path.cwd())
