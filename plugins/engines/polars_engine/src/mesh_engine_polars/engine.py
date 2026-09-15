from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from pathlib import Path
from typing import Any
from uuid import uuid4

import polars as pl
import pyarrow.parquet as pq

from mesh_common.hashing import sha256_file
from mesh_common.schemas import ArtifactRef, QueryPlan, TableSchema
from mesh_engine_duckdb.sql_guard import SqlGuardError, validate_sql

__version__ = "0.1.0"


def _frame_for_table(table: TableSchema, registered: dict[str, Any]) -> pl.LazyFrame | pl.DataFrame:
    if table.name in registered:
        return pl.from_arrow(registered[table.name])
    if not table.source_path:
        raise SqlGuardError(f"table {table.name} has no source_path")
    path = Path(table.source_path)
    if table.format == "csv":
        return pl.scan_csv(path)
    if table.format == "parquet":
        return pl.scan_parquet(path)
    if table.format == "json":
        text = path.read_text(encoding="utf-8").lstrip()
        if text.startswith("["):
            return pl.read_json(path)
        return pl.scan_ndjson(path)
    raise SqlGuardError(f"unsupported table format: {table.format}")


class PolarsEngine:
    id = "polars"
    version = __version__

    def execute(self, plan: QueryPlan, arrow_tables: dict[str, Any] | None = None) -> ArtifactRef:
        sql = validate_sql(plan.sql)
        artifact_dir = Path(plan.artifact_dir)
        artifact_dir.mkdir(parents=True, exist_ok=True)
        registered = arrow_tables or {}
        frames: dict[str, pl.LazyFrame | pl.DataFrame] = {}
        for table in plan.tables:
            frames[table.name] = _frame_for_table(table, registered)

        def _run() -> pl.DataFrame:
            ctx = pl.SQLContext(frames=frames, eager=False)
            result = ctx.execute(sql)
            if isinstance(result, pl.LazyFrame):
                result = result.limit(int(plan.row_limit)).collect()
            else:
                result = result.head(int(plan.row_limit))
            return result

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(_run)
            try:
                frame = future.result(timeout=plan.timeout_seconds)
            except FuturesTimeout as exc:
                raise TimeoutError(f"polars query exceeded {plan.timeout_seconds}s") from exc

        arrow = frame.to_arrow()
        artifact_id = str(uuid4())
        path = artifact_dir / f"{artifact_id}.parquet"
        pq.write_table(arrow, path)
        return ArtifactRef(
            artifact_id=artifact_id,
            path=str(path.resolve()),
            format="parquet",
            sha256=sha256_file(path),
            row_count=arrow.num_rows,
            column_names=list(arrow.column_names),
        )
