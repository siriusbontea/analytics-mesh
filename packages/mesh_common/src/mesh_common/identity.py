from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
    load_pem_private_key,
)


@dataclass
class NodeKeyPair:
    """Ed25519 identity for a mesh node. Public-only instances can verify but not sign."""

    node_id: str
    _private: Ed25519PrivateKey | None
    _public: Ed25519PublicKey

    @property
    def public_key_hex(self) -> str:
        return self._public.public_bytes(encoding=Encoding.Raw, format=PublicFormat.Raw).hex()

    def sign(self, payload: bytes) -> str:
        if self._private is None:
            raise ValueError("cannot sign without a private key")
        return self._private.sign(payload).hex()

    def verify(self, payload: bytes, signature_hex: str) -> bool:
        try:
            self._public.verify(bytes.fromhex(signature_hex), payload)
            return True
        except (InvalidSignature, ValueError):
            return False

    def private_pem(self) -> bytes:
        if self._private is None:
            raise ValueError("cannot serialize a public-only keypair")
        return self._private.private_bytes(
            encoding=Encoding.PEM,
            format=PrivateFormat.PKCS8,
            encryption_algorithm=NoEncryption(),
        )

    @classmethod
    def from_public_hex(cls, public_key_hex: str, node_id: str = "") -> NodeKeyPair:
        public = Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_key_hex))
        return cls(node_id=node_id, _private=None, _public=public)

    @classmethod
    def from_private_pem(cls, pem: bytes, node_id: str) -> NodeKeyPair:
        loaded = load_pem_private_key(pem, password=None)
        if not isinstance(loaded, Ed25519PrivateKey):
            raise ValueError("identity file is not an Ed25519 private key")
        return cls(node_id=node_id, _private=loaded, _public=loaded.public_key())


def generate_keypair(node_id: str) -> NodeKeyPair:
    private = Ed25519PrivateKey.generate()
    return NodeKeyPair(node_id=node_id, _private=private, _public=private.public_key())


def load_or_create_keypair(path: Path | str, node_id: str) -> NodeKeyPair:
    key_path = Path(path)
    if key_path.is_file():
        return NodeKeyPair.from_private_pem(key_path.read_bytes(), node_id=node_id)
    keys = generate_keypair(node_id)
    key_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.write_bytes(keys.private_pem())
    key_path.chmod(0o600)
    return keys


def build_registration(
    keys: NodeKeyPair,
    endpoint: str,
    token: str,
    labels: list[str] | None = None,
    signed_at: str | None = None,
) -> dict[str, object]:
    from datetime import datetime, timezone

    stamped = signed_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    payload = canonical_registration_payload(
        node_id=keys.node_id,
        endpoint=endpoint,
        public_key=keys.public_key_hex,
        signed_at=stamped,
    )
    return {
        "node_id": keys.node_id,
        "endpoint": endpoint,
        "public_key": keys.public_key_hex,
        "labels": labels or [],
        "token": token,
        "signed_at": stamped,
        "signature": keys.sign(payload),
    }


def canonical_registration_payload(
    node_id: str,
    endpoint: str,
    public_key: str,
    signed_at: str,
) -> bytes:
    return json.dumps(
        {
            "endpoint": endpoint,
            "node_id": node_id,
            "public_key": public_key,
            "signed_at": signed_at,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
