from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from mesh_common.schemas import AnalyticSpec

_SEMVER_PARTS = 3
_TOKEN_RE = re.compile(r"[a-z0-9]+")
_STOPWORDS = frozenset({"by", "the", "and", "for", "of", "a", "an", "to", "in", "on", "or"})


def _tokens(text: str) -> list[str]:
    return [token for token in _TOKEN_RE.findall(text.lower()) if token not in _STOPWORDS and len(token) >= 3]


def _stem(token: str) -> str:
    if token.endswith("ies") and len(token) > 4:
        return token[:-3] + "y"
    if token.endswith("s") and len(token) > 3 and not token.endswith("ss"):
        return token[:-1]
    return token


def _analytic_id(item: AnalyticSpec | dict[str, Any]) -> str:
    if isinstance(item, AnalyticSpec):
        return item.analytic_id
    return str(item["analytic_id"])


def match_registered_analytic(
    question: str,
    analytics: list[AnalyticSpec] | list[dict[str, Any]],
) -> AnalyticSpec | dict[str, Any] | None:
    """Return a clearly matching registered analytic, or None.

    Clear match means the question contains the analytic id as a phrase
    (underscores become spaces), or every significant id token (length >= 3,
    minus stopwords) appears after simple plural stemming. Description-only
    overlap is not enough — e.g. "which product sold the most?" does not
    match ``top_products``. Prefer the longest id when several match so
    ``top products polars`` selects ``top_products_polars``.
    """
    raw = " ".join(_TOKEN_RE.findall(question.lower()))
    if not raw or not analytics:
        return None
    question_stems = {_stem(token) for token in _tokens(question)}
    phrase_hits: list[AnalyticSpec | dict[str, Any]] = []
    token_hits: list[AnalyticSpec | dict[str, Any]] = []
    for item in analytics:
        analytic_id = _analytic_id(item)
        phrase = " ".join(_TOKEN_RE.findall(analytic_id.replace("_", " ").lower()))
        significant = [token for token in _TOKEN_RE.findall(phrase) if token not in _STOPWORDS and len(token) >= 3]
        if phrase and phrase in raw:
            phrase_hits.append(item)
        elif len(significant) >= 2 and all(_stem(token) in question_stems for token in significant):
            token_hits.append(item)
    hits = phrase_hits or token_hits
    if not hits:
        return None
    return max(hits, key=lambda item: len(_analytic_id(item)))


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
