from __future__ import annotations

from pathlib import Path

import pytest

from mesh_common.identity import NodeKeyPair, generate_keypair, load_or_create_keypair


def test_generated_keypair_can_sign_and_verify():
    keys = generate_keypair(node_id="node-b")
    payload = b'{"node_id":"node-b","endpoint":"http://127.0.0.1:8082"}'
    signature = keys.sign(payload)
    assert keys.public_key_hex
    assert keys.verify(payload, signature) is True
    assert NodeKeyPair.from_public_hex(keys.public_key_hex).verify(payload, signature) is True


def test_verify_rejects_tampered_payload():
    keys = generate_keypair(node_id="node-b")
    signature = keys.sign(b"original")
    assert keys.verify(b"tampered", signature) is False


def test_load_or_create_persists_same_public_key(tmp_path: Path):
    path = tmp_path / "node.ed25519"
    first = load_or_create_keypair(path, node_id="node-a")
    second = load_or_create_keypair(path, node_id="node-a")
    assert first.public_key_hex == second.public_key_hex
    assert path.is_file()
    assert "PRIVATE" in path.read_text() or len(path.read_bytes()) > 0
