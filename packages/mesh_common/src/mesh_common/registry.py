from __future__ import annotations

from pathlib import Path

import yaml

from mesh_common.schemas import AnalyticSpec

_SEMVER_PARTS = 3


class AnalyticSpecError(ValueError):
    """Raised when an analytic YAML/SQL definition is invalid."""


def parse_semver(version: str) -> tuple[int, int, int]:
    parts = version.split(".")
    if len(parts) != _SEMVER_PARTS or not all(part.isdigit() for part in parts):
        raise AnalyticSpecError(f"invalid semver: {version}")
    return int(parts[0]), int(parts[1]), int(parts[2])


class AnalyticRegistry:
    def __init__(self, specs: list[AnalyticSpec] | None = None) -> None:
        self._specs = list(specs or [])
        self._index: dict[tuple[str, str], AnalyticSpec] = {
            (item.analytic_id, item.version): item for item in self._specs
        }

    @classmethod
    def empty(cls) -> AnalyticRegistry:
        return cls([])

    @classmethod
    def load(cls, root: Path | str) -> AnalyticRegistry:
        base = Path(root)
        if not base.is_dir():
            raise AnalyticSpecError(f"analytics directory not found: {base}")
        specs: list[AnalyticSpec] = []
        seen: set[tuple[str, str]] = set()
        for path in sorted(base.rglob("*")):
            if path.suffix.lower() not in {".yaml", ".yml"}:
                continue
            spec = _load_spec(path)
            key = (spec.analytic_id, spec.version)
            if key in seen:
                raise AnalyticSpecError(f"duplicate analytic {spec.analytic_id}@{spec.version}")
            seen.add(key)
            specs.append(spec)
        return cls(specs)

    def list(self) -> list[AnalyticSpec]:
        return sorted(self._specs, key=lambda item: (item.analytic_id, parse_semver(item.version)))

    def get(self, analytic_id: str, version: str | None = None) -> AnalyticSpec:
        matches = [item for item in self._specs if item.analytic_id == analytic_id]
        if not matches:
            raise KeyError(analytic_id)
        if version is None:
            return max(matches, key=lambda item: parse_semver(item.version))
        for item in matches:
            if item.version == version:
                return item
        raise KeyError(f"{analytic_id}@{version}")


def _load_spec(path: Path) -> AnalyticSpec:
    raw = yaml.safe_load(path.read_text()) or {}
    if not isinstance(raw, dict):
        raise AnalyticSpecError(f"{path}: expected a mapping")
    analytic_id = raw.get("analytic_id")
    version = raw.get("version")
    if not analytic_id or not version:
        raise AnalyticSpecError(f"{path}: analytic_id and version are required")
    parse_semver(str(version))
    engine = raw.get("engine", "duckdb")
    entry = raw.get("entry")
    sql = raw.get("sql")
    if entry:
        sql_path = (path.parent / entry).resolve()
        if not sql_path.is_file():
            raise AnalyticSpecError(f"{path}: entry file not found: {entry}")
        sql = sql_path.read_text()
        entry_value = str(sql_path)
    elif sql:
        entry_value = str(path)
    else:
        raise AnalyticSpecError(f"{path}: provide entry (SQL file) or sql")
    return AnalyticSpec(
        analytic_id=str(analytic_id),
        version=str(version),
        engine=str(engine),
        entry=entry_value,
        sql=sql,
        allowed_connectors=list(raw.get("allowed_connectors") or []),
        description=str(raw.get("description") or ""),
        params_schema=dict(raw.get("params_schema") or {}),
        path=str(path.resolve()),
    )
