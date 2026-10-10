"""Authenticated HTTP/1.1 pipeline against isolated localhost QA only."""
import json
import socket
import uuid

import httpx

from tests.unit.test_research_archive import payload

with httpx.Client(base_url="http://127.0.0.1:8768") as client:
    client.post("/api/v1/auth/login", json={
        "username": "factor-qa", "password": "Local-factor-QA-only-2026!",
    }).raise_for_status()
    token = client.cookies.get("easy_tdx_session")

body = json.dumps({"kind": "chart", "name": "pipeline QA", "payload": payload()}).encode()
cookie = f"Cookie: easy_tdx_session={token}\r\n"
put = (f"PUT /api/v1/research/archives/{uuid.uuid4()} HTTP/1.1\r\n"
       "Host: 127.0.0.1:8768\r\n" + cookie +
       f"Content-Type: application/json\r\nContent-Length: {len(body)}\r\n\r\n").encode() + body
get = ("GET /api/v1/research/archives HTTP/1.1\r\nHost: 127.0.0.1:8768\r\n" +
       cookie + "Connection: close\r\n\r\n").encode()
with socket.create_connection(("127.0.0.1", 8768), timeout=10) as sock:
    sock.sendall(put + get)
    result = bytearray()
    while chunk := sock.recv(65536):
        result.extend(chunk)
for response in bytes(result).split(b"HTTP/1.1 ")[1:]:
    print(response.split(b"\r\n", 1)[0].decode())
    if not response.startswith((b"200", b"201")):
        print(response.split(b"\r\n\r\n", 1)[1].decode())
