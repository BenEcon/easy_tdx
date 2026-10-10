"""Checkpoint shape must be valid in addition to its signature and snapshot."""

import base64
import hashlib
import hmac
import json

import pytest

from easy_tdx.web import research_cursor as cursor


@pytest.mark.parametrize("kind", ["search", "solution"])
def test_valid_checkpoint_round_trip_and_fingerprint_order(kind):
    payload = {"kind": kind, "fingerprint": "snapshot", "path": [1, 0, 1]}
    if kind == "search":
        payload["emitted"] = 0
    assert cursor.decode_cursor(cursor.encode_cursor(payload), "snapshot", kind) == payload
    assert cursor.fingerprint({"a": 1, "b": 2}) == cursor.fingerprint({"b": 2, "a": 1})


@pytest.mark.parametrize("path", [None, "10", {}, [True], [-1], [2], [1.0], ["0"]])
@pytest.mark.parametrize("kind", ["search", "solution"])
def test_signed_invalid_path_rejected(path, kind):
    token = cursor.encode_cursor(
        {"kind": kind, "fingerprint": "snapshot", "path": path, "emitted": 1}
    )
    with pytest.raises(ValueError, match="检查点失效"):
        cursor.decode_cursor(token, "snapshot", kind)


@pytest.mark.parametrize("emitted", [None, True, -1, 1.0, "1", [], {}])
def test_signed_invalid_count_rejected(emitted):
    token = cursor.encode_cursor(
        {"kind": "search", "fingerprint": "snapshot", "path": [], "emitted": emitted}
    )
    with pytest.raises(ValueError, match="检查点失效"):
        cursor.decode_cursor(token, "snapshot", "search")


@pytest.mark.parametrize(
    "payload",
    [None, [], "text", 1, {}, {"kind": "search", "fingerprint": "snapshot", "path": []}],
)
def test_signed_non_object_or_missing_fields_rejected(payload):
    # Emulate malformed server-issued legacy tokens, not a forged client signature.
    raw = json.dumps(payload).encode()
    signature = hmac.new(cursor._KEY, raw, hashlib.sha256).hexdigest()
    token = base64.urlsafe_b64encode(raw).decode() + "." + signature
    with pytest.raises(ValueError, match="检查点失效"):
        cursor.decode_cursor(token, "snapshot", "search")


def test_size_limits_still_apply(monkeypatch):
    monkeypatch.setattr(cursor, "_MAX_BYTES", 64)
    with pytest.raises(ValueError, match="安全长度"):
        cursor.encode_cursor({"path": [1] * 100})
    with pytest.raises(ValueError, match="检查点失效"):
        cursor.decode_cursor("x" * 129, "snapshot", "search")
