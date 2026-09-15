from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

from mesh_common.schemas import Receipt


class PolicyDenied(Exception):
    """Raised when a YAML (or future OPA/Cedar) policy rejects a request."""

    def __init__(self, reason: str, receipt: Receipt | None = None) -> None:
        self.reason = reason
        self.receipt = receipt
        super().__init__(reason)


class PolicyDecision(BaseModel):
    allowed: bool
    reason: str | None = None
    max_row_limit: int | None = None
    query_timeout_seconds: float | None = None
    model_mode: Literal["local_only", "allow_frontier"] = "local_only"


class PrincipalRule(BaseModel):
    allow_adhoc_sql: bool = True
    allow_assist: bool = True
    connectors: list[str] = Field(default_factory=lambda: ["*"])
    analytics: list[str] = Field(default_factory=lambda: ["*"])
    nodes: list[str] = Field(default_factory=lambda: ["*"])
    max_row_limit: int | None = None
    query_timeout_seconds: float | None = None
    model_mode: Literal["local_only", "allow_frontier"] = "local_only"


class PolicyEngine:
    """Replaceable allowlist interface. YAML now; OPA/Cedar later."""

    def authorize(
        self,
        *,
        principal: str,
        action: str,
        node_id: str,
        connector_ids: list[str] | None = None,
        analytic_id: str | None = None,
        model_provider: str | None = None,
    ) -> PolicyDecision:
        raise NotImplementedError


class AllowAllPolicy(PolicyEngine):
    """M1–M3 compatible default when no policy file is configured."""

    def authorize(
        self,
        *,
        principal: str,
        action: str,
        node_id: str,
        connector_ids: list[str] | None = None,
        analytic_id: str | None = None,
        model_provider: str | None = None,
    ) -> PolicyDecision:
        del principal, action, node_id, connector_ids, analytic_id, model_provider
        return PolicyDecision(allowed=True, model_mode="allow_frontier")


class YamlPolicy(PolicyEngine):
    def __init__(
        self,
        principals: dict[str, PrincipalRule],
        *,
        default_principal: str | None = None,
        deny_unknown_principals: bool = True,
    ) -> None:
        self.principals = principals
        self.default_principal = default_principal
        self.deny_unknown_principals = deny_unknown_principals

    @classmethod
    def from_yaml(cls, text: str) -> YamlPolicy:
        raw = yaml.safe_load(text) or {}
        principals = {
            name: PrincipalRule.model_validate(body or {})
            for name, body in (raw.get("principals") or {}).items()
        }
        return cls(
            principals,
            default_principal=raw.get("default_principal"),
            deny_unknown_principals=bool(raw.get("deny_unknown_principals", True)),
        )

    def authorize(
        self,
        *,
        principal: str,
        action: str,
        node_id: str,
        connector_ids: list[str] | None = None,
        analytic_id: str | None = None,
        model_provider: str | None = None,
    ) -> PolicyDecision:
        lookup = principal or self.default_principal or ""
        rule = self.principals.get(lookup)
        if rule is None:
            if self.deny_unknown_principals:
                return PolicyDecision(allowed=False, reason=f"unknown principal: {principal}")
            return PolicyDecision(allowed=True, model_mode="allow_frontier")

        if not _allows(rule.nodes, node_id):
            return PolicyDecision(allowed=False, reason=f"principal {principal} cannot use node {node_id}")

        for connector_id in connector_ids or []:
            if not _allows(rule.connectors, connector_id):
                return PolicyDecision(
                    allowed=False,
                    reason=f"principal {principal} cannot use connector {connector_id}",
                )

        if action == "run_query" and not rule.allow_adhoc_sql:
            return PolicyDecision(allowed=False, reason=f"principal {principal} cannot run ad-hoc SQL")

        if action == "run_analytic":
            if not analytic_id:
                return PolicyDecision(allowed=False, reason="analytic_id is required")
            if not _allows(rule.analytics, analytic_id):
                return PolicyDecision(
                    allowed=False,
                    reason=f"principal {principal} cannot run analytic {analytic_id}",
                )

        if action.startswith("assist"):
            if not rule.allow_assist:
                return PolicyDecision(allowed=False, reason=f"principal {principal} cannot use model assist")
            if model_provider == "frontier" and rule.model_mode == "local_only":
                return PolicyDecision(
                    allowed=False,
                    reason="policy is local_only; frontier model assist is not allowed",
                )

        return PolicyDecision(
            allowed=True,
            max_row_limit=rule.max_row_limit,
            query_timeout_seconds=rule.query_timeout_seconds,
            model_mode=rule.model_mode,
        )


def load_policy(path: Path | str | None) -> PolicyEngine:
    if path is None:
        return AllowAllPolicy()
    return YamlPolicy.from_yaml(Path(path).read_text())


def _allows(allowed: list[str], value: str) -> bool:
    return "*" in allowed or value in allowed
