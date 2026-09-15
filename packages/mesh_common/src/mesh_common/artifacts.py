from __future__ import annotations

import time
from pathlib import Path

from pydantic import BaseModel

from mesh_common.schemas import ArtifactRef


class ArtifactStoreConfig(BaseModel):
    """Retention and size caps. Receipts are not stored here and are never pruned."""

    max_bytes_per_file: int = 100 * 1024 * 1024
    max_total_bytes: int = 1024 * 1024 * 1024
    retention_days: int = 7
    max_files: int = 200


class ArtifactTooLarge(ValueError):
    """Raised when a result parquet exceeds max_bytes_per_file."""


class ArtifactStore:
    def __init__(self, root: Path | str, config: ArtifactStoreConfig | None = None) -> None:
        self.root = Path(root)
        self.config = config or ArtifactStoreConfig()
        self.root.mkdir(parents=True, exist_ok=True)

    def commit(self, artifact: ArtifactRef) -> ArtifactRef:
        path = Path(artifact.path)
        size = path.stat().st_size
        if size > self.config.max_bytes_per_file:
            path.unlink(missing_ok=True)
            sidecar = path.with_suffix(".json")
            sidecar.unlink(missing_ok=True)
            raise ArtifactTooLarge(
                f"artifact exceeds max_bytes_per_file ({self.config.max_bytes_per_file} bytes)"
            )
        path.with_suffix(".json").write_text(artifact.model_dump_json())
        self.enforce()
        if not path.is_file():
            raise ArtifactTooLarge("artifact was pruned immediately after write; tighten caps or retry")
        return artifact

    def enforce(self) -> list[str]:
        items = [(path.stat().st_mtime, path) for path in self.root.glob("*.parquet") if path.is_file()]
        items.sort()
        cutoff = time.time() - (self.config.retention_days * 86400)
        deleted: list[str] = []
        remaining: list[tuple[float, Path]] = []
        for mtime, path in items:
            if mtime < cutoff:
                self._delete_pair(path)
                deleted.append(path.stem)
            else:
                remaining.append((mtime, path))

        def parquet_bytes(pairs: list[tuple[float, Path]]) -> int:
            return sum(path.stat().st_size for _mtime, path in pairs if path.is_file())

        while remaining and (
            len(remaining) > self.config.max_files or parquet_bytes(remaining) > self.config.max_total_bytes
        ):
            _mtime, path = remaining.pop(0)
            self._delete_pair(path)
            deleted.append(path.stem)
        return deleted

    @staticmethod
    def _delete_pair(parquet: Path) -> None:
        parquet.unlink(missing_ok=True)
        parquet.with_suffix(".json").unlink(missing_ok=True)
