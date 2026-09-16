"""Small env-based secret overrides. Pairing token only — not PKI or SSO."""

from __future__ import annotations

import os

DEFAULT_PAIR_TOKEN_ENV = "MESH_PAIR_TOKEN"


def resolve_pair_token(
    configured: str | None = None,
    *,
    pair_token_env: str | None = None,
    override: str | None = None,
) -> str:
    """Resolve the plane/node pairing token.

    Precedence:
    1. ``override`` (CLI ``--token``)
    2. Environment variable named by ``pair_token_env``, or ``MESH_PAIR_TOKEN``
       when ``pair_token_env`` is unset
    3. YAML ``configured`` value (example configs keep ``demo-pair-token``)
    """
    if override and override.strip():
        return override.strip()
    env_name = pair_token_env or DEFAULT_PAIR_TOKEN_ENV
    env_value = os.environ.get(env_name)
    if env_value and env_value.strip():
        return env_value.strip()
    if pair_token_env:
        raise ValueError(f"pairing token missing (set {pair_token_env})")
    if configured and configured.strip():
        return configured.strip()
    raise ValueError("registration token is required")
