from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel


class PlaneConfig(BaseModel):
    plane_id: str = "home-plane"
    registration_token: str = "demo-pair-token"
    store_path: Path = Path("var/plane/plane.sqlite")
    listen_host: str = "127.0.0.1"
    listen_port: int = 8090

    def resolve_paths(self, base: Path) -> PlaneConfig:
        store = self.store_path if self.store_path.is_absolute() else (base / self.store_path).resolve()
        return self.model_copy(update={"store_path": store})


def load_config(path: Path | str) -> PlaneConfig:
    config_path = Path(path)
    raw = yaml.safe_load(config_path.read_text()) or {}
    return PlaneConfig.model_validate(raw).resolve_paths(Path.cwd())
