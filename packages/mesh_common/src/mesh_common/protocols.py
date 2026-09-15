from __future__ import annotations

from collections.abc import Iterator
from typing import Protocol, runtime_checkable

import pyarrow as pa

from mesh_common.schemas import ArtifactRef, QueryPlan, TableSchema


@runtime_checkable
class Connector(Protocol):
    id: str
    version: str
    sensitivity_labels: list[str]

    def discover_schema(self) -> list[TableSchema]: ...

    def scan(
        self,
        table_or_path: str,
        projection: list[str] | None = None,
        filter_expr: str | None = None,
    ) -> Iterator[pa.RecordBatch]: ...


@runtime_checkable
class Engine(Protocol):
    id: str
    version: str

    def execute(self, plan: QueryPlan) -> ArtifactRef: ...
