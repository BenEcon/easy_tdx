"""Signed, snapshot-bound DFS checkpoints. Never trust a client 'complete' flag.

Set EASY_TDX_RESEARCH_CURSOR_KEY identically on all workers for durable/multiworker
continuation. Without it checkpoints intentionally expire on a process restart.
No account secret, file write or persistent market-data cache is required.
"""

import base64
import hashlib
import hmac
import json
import os
import secrets

_KEY = os.environ.get("EASY_TDX_RESEARCH_CURSOR_KEY", "").encode() or secrets.token_bytes(32)
_MAX_BYTES = 262144


def fingerprint(value):
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(encoded).hexdigest()


def encode_cursor(payload):
    raw = json.dumps(payload, separators=(",", ":")).encode()
    if len(raw) > _MAX_BYTES:
        raise ValueError("搜索检查点超出安全长度，未宣告穷举完成")
    signature = hmac.new(_KEY, raw, hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(raw).decode() + "." + signature


def decode_cursor(token, expected_fingerprint, kind):
    try:
        if len(token) > _MAX_BYTES * 2:
            raise ValueError
        encoded, signature = token.rsplit(".", 1)
        raw = base64.b64decode(encoded, altchars=b"-_", validate=True)
        if len(raw) > _MAX_BYTES or not hmac.compare_digest(
            hmac.new(_KEY, raw, hashlib.sha256).hexdigest(), signature
        ):
            raise ValueError
        payload = json.loads(raw)
        if payload["fingerprint"] != expected_fingerprint or payload["kind"] != kind:
            raise ValueError
        return payload
    except (ValueError, KeyError, TypeError, UnicodeError) as exc:
        raise ValueError("检查点失效或行情快照不匹配，请重新开始搜索") from exc
