"""Paired backups use real SQLite/Cookie identities, never developer configuration."""

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import uuid

import pytest

from easy_tdx.web import research_backup as backup
from easy_tdx.web.account_store import AccountStore
from easy_tdx.web.research_archive import ArchiveError, ResearchArchive
from tests.unit.test_research_archive import payload


@pytest.fixture
def source(tmp_path):
    directory = tmp_path / "source"
    accounts = AccountStore(directory / "accounts.db")
    admin = accounts.create_user("admin", "Restore-test-password!", role="admin")
    alice = accounts.create_user("alice", "Restore-test-password!", role="user")
    bob = accounts.create_user("bob", "Restore-test-password!", role="user")
    sessions = {user.id: accounts.create_session(user.id) for user in (admin, alice, bob)}
    accounts.set_preferences(alice.id, {"tracking": {"groups": [{"name": "研究观察"}]}})
    accounts.update_user(bob.id, active=False)
    archives = ResearchArchive(directory / "research_archives.db")
    keys = [str(uuid.uuid4()) for _ in range(3)]
    for key in keys:
        archives.create(alice.id, key, "chart", payload(), "原始研究", "精度与原版本均保留")
    archives.mutate(alice.id, keys[0], 1, "edit", note="多设备新备注")
    archives.mutate(alice.id, keys[1], 1, "delete")
    archives.mutate(alice.id, keys[2], 1, "delete")
    archives.mutate(alice.id, keys[2], 2, "purge")
    archives.create(bob.id, keys[0], "chart", payload(), "停用账户保留")
    return directory, accounts, archives, admin, alice, bob, sessions, keys


def test_backup_restore_preserves_identity_precision_revisions_trash_and_purge(source, tmp_path):
    directory, accounts, archives, admin, alice, bob, sessions, keys = source
    destination, restored = tmp_path / "backup", tmp_path / "isolated"
    manifest = backup.create_backup(directory, destination)
    assert manifest["counts"] == {
        "users": 3,
        "active": 2,
        "deleted": 1,
        "purged": 1,
        "bytes": sum(archives.list(owner)["quota"]["used_bytes"] for owner in (alice.id, bob.id)),
    }
    assert backup.verify_backup(destination) == manifest
    result = backup.restore_backup(destination, restored)
    assert result["activated"] is False
    restored_accounts = AccountStore(restored / "accounts.db")
    restored_archives = ResearchArchive(restored / "research_archives.db")
    for user in (admin, alice, bob):
        assert restored_accounts.get_user(user.id) == accounts.get_user(user.id)
        assert restored_accounts.get_user_for_session(sessions[user.id]) is None
        assert restored_archives.list(user.id) == archives.list(user.id)
    assert accounts.get_user_for_session(sessions[alice.id]) is not None
    assert restored_accounts.authenticate("alice", "Restore-test-password!").id == alice.id
    assert restored_accounts.authenticate("bob", "Restore-test-password!") is None
    assert restored_archives.get(alice.id, keys[0]) == archives.get(alice.id, keys[0])
    restored_archives.mutate(alice.id, keys[1], 2, "restore")
    assert restored_archives.get(alice.id, keys[1])["payload"] == payload()
    with pytest.raises(ArchiveError) as stale:
        restored_archives.mutate(alice.id, keys[0], 1, "edit", note="迟到写入")
    assert stale.value.status == 409
    with pytest.raises(ArchiveError) as purged:
        restored_archives.create(alice.id, keys[2], "chart", payload(), "不能复活")
    assert purged.value.status == 410
    assert archives.list(alice.id)["items"][0]["state"] != "purged"


def test_wal_commits_included_and_source_bytes_or_sessions_not_rewritten(source, tmp_path):
    directory, accounts, archives, _, alice, _, sessions, _ = source
    connections = [sqlite3.connect(directory / name) for name in backup.FILES]
    try:
        for db in connections:
            assert db.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
            db.execute("PRAGMA wal_autocheckpoint=0")
            db.execute("BEGIN")
            db.execute("SELECT COUNT(*) FROM sqlite_schema").fetchone()
        new_key = str(uuid.uuid4())
        archives.create(alice.id, new_key, "chart", payload(), "WAL 已提交")
        assert (directory / "research_archives.db-wal").stat().st_size > 0
        backup.create_backup(directory, tmp_path / "wal-backup")
        # Opening an application store would run schema initialization and write
        # a new header. A backup is read-only evidence, not a live app directory.
        with sqlite3.connect(
            (tmp_path / "wal-backup" / "research_archives.db").as_uri() + "?mode=ro", uri=True
        ) as copied:
            assert (
                copied.execute(
                    "SELECT name FROM research_archives WHERE id=?", (new_key,)
                ).fetchone()[0]
                == "WAL 已提交"
            )
        assert accounts.get_user_for_session(sessions[alice.id]) is not None
        assert not list((tmp_path / "wal-backup").glob("*-wal"))
        backup.verify_backup(tmp_path / "wal-backup")
    finally:
        for db in connections:
            db.close()


def test_both_database_writers_reserved_through_entire_pair_copy(source, tmp_path, monkeypatch):
    original = backup._new_file
    observed = []

    def probe(path):
        for name in backup.FILES:
            with sqlite3.connect(source[0] / name, timeout=0.01) as db:
                with pytest.raises(sqlite3.OperationalError, match="locked"):
                    db.execute("BEGIN IMMEDIATE")
            observed.append((path.name, name))
        original(path)

    monkeypatch.setattr(backup, "_new_file", probe)
    backup.create_backup(source[0], tmp_path / "pair")
    assert len(observed) == 4
    for name in backup.FILES:
        with sqlite3.connect(source[0] / name, timeout=0.1) as db:
            db.execute("BEGIN IMMEDIATE")


def test_copy_failure_preserves_source_and_never_marks_partial_backup_complete(
    source, tmp_path, monkeypatch
):
    original = backup._new_file

    def fail_second(path):
        if path.name == "research_archives.db":
            raise OSError("simulated disk full")
        original(path)

    monkeypatch.setattr(backup, "_new_file", fail_second)
    with pytest.raises(OSError, match="disk full"):
        backup.create_backup(source[0], tmp_path / "partial")
    assert not (tmp_path / "partial" / "manifest.json").exists()
    with pytest.raises(backup.BackupError):
        backup.restore_backup(tmp_path / "partial", tmp_path / "restored")
    assert source[1].get_user_for_session(source[6][source[4].id]) is not None


def test_restored_real_cookie_access_and_disabled_account(source, tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from easy_tdx.web.routers import auth
    from easy_tdx.web.routers.research_archive import build_router

    backup.create_backup(source[0], tmp_path / "backup")
    backup.restore_backup(tmp_path / "backup", tmp_path / "restore")
    accounts = AccountStore(tmp_path / "restore" / "accounts.db")
    archives = ResearchArchive(tmp_path / "restore" / "research_archives.db")
    monkeypatch.setattr(auth, "get_account_store", lambda: accounts)
    app = FastAPI()
    app.include_router(build_router(lambda: archives, auth.get_current_user), prefix="/api/v1")
    _, _, _, admin, alice, bob, sessions, keys = source
    with TestClient(app) as client:
        client.cookies.set(auth.SESSION_COOKIE, sessions[alice.id])
        assert client.get("/api/v1/research/archives").status_code == 401
        for user in (admin, alice, bob):
            token = accounts.create_session(user.id)
            client.cookies.set(auth.SESSION_COOKIE, token)
            response = client.get(f"/api/v1/research/archives/{keys[0]}")
            assert response.status_code == (
                200 if user.id == alice.id else 401 if user.id == bob.id else 404
            )


@pytest.mark.parametrize("action", [backup.create_backup, backup.restore_backup])
def test_never_overwrites_existing_directory_or_sentinel(source, tmp_path, action):
    directory = source[0]
    if action is backup.restore_backup:
        backup.create_backup(directory, tmp_path / "backup")
        directory = tmp_path / "backup"
    destination = tmp_path / "occupied"
    destination.mkdir()
    sentinel = destination / "keep.txt"
    sentinel.write_text("user data")
    with pytest.raises(backup.BackupError, match="目标已存在"):
        action(directory, destination)
    assert sentinel.read_text() == "user data"


def test_mismatched_owner_pair_never_becomes_complete(source, tmp_path):
    directory, _, archives, *_ = source
    archives.create("absent-owner", str(uuid.uuid4()), "chart", payload(), "错误归属")
    with pytest.raises(backup.BackupError, match="归属"):
        backup.create_backup(directory, tmp_path / "bad")
    assert not (tmp_path / "bad" / "manifest.json").exists()


@pytest.mark.parametrize("fault", ["bytes", "digest", "payload", "version", "admin", "revision"])
def test_invalid_database_rejected_without_repair(source, tmp_path, fault):
    directory, *_ = source
    name = "accounts.db" if fault == "admin" else "research_archives.db"
    with sqlite3.connect(directory / name) as db:
        if fault == "bytes":
            db.execute("UPDATE research_archives SET size_bytes=1 WHERE state='active'")
        elif fault == "digest":
            db.execute("UPDATE research_archives SET digest=?", ("a" * 64,))
        elif fault == "payload":
            text = '{"value":NaN}'
            db.execute(
                "UPDATE research_archives SET payload=?,digest=?,"
                "size_bytes=length(CAST(?||name||note AS BLOB)) WHERE state='active'",
                (text, hashlib.sha256(text.encode()).hexdigest(), text),
            )
        elif fault == "version":
            db.execute("PRAGMA user_version=99")
        elif fault == "revision":
            db.execute("DELETE FROM archive_owners")
        else:
            db.execute("UPDATE users SET active=0")
    with pytest.raises(backup.BackupError):
        backup.create_backup(directory, tmp_path / "bad")
    assert not (tmp_path / "bad" / "manifest.json").exists()


@pytest.mark.parametrize("fault", ["missing", "tampered", "manifest", "symlink", "journal"])
def test_incomplete_or_tampered_artifacts_cannot_restore(source, tmp_path, fault):
    directory = tmp_path / "backup"
    backup.create_backup(source[0], directory)
    path = directory / "research_archives.db"
    if fault == "missing":
        path.unlink()
    elif fault == "tampered":
        with path.open("ab") as stream:
            stream.write(b"bad")
    elif fault == "manifest":
        (directory / "manifest.json").write_text("{}")
    elif fault == "symlink":
        path.unlink()
        path.symlink_to(source[0] / "research_archives.db")
    else:
        (directory / "research_archives.db-wal").write_bytes(b"not standalone")
    with pytest.raises(backup.BackupError):
        backup.restore_backup(directory, tmp_path / "restore")
    assert not (tmp_path / "restore").exists()


def test_lock_contention_is_bounded_and_failed_copy_has_no_manifest(source, tmp_path):
    with sqlite3.connect(source[0] / "research_archives.db") as db:
        db.execute("BEGIN IMMEDIATE")
        with pytest.raises((sqlite3.OperationalError, backup.BackupError)):
            backup.create_backup(source[0], tmp_path / "busy", timeout=0.1)
    assert not (tmp_path / "busy" / "manifest.json").exists()
    # A failed paired reservation must not keep the other database locked.
    with sqlite3.connect(source[0] / "accounts.db", timeout=0.1) as db:
        db.execute("BEGIN IMMEDIATE")


def test_missing_source_never_creates_database_and_nested_destination_rejected(source, tmp_path):
    with pytest.raises(backup.BackupError):
        backup.create_backup(tmp_path / "absent", tmp_path / "copy")
    assert not (tmp_path / "absent").exists()
    with pytest.raises(backup.BackupError, match="嵌套"):
        backup.create_backup(source[0], source[0] / "copy")


@pytest.mark.skipif(os.name == "nt", reason="POSIX mode assertions")
def test_backup_and_restore_permissions_are_private(source, tmp_path):
    backup.create_backup(source[0], tmp_path / "backup")
    backup.restore_backup(tmp_path / "backup", tmp_path / "restore")
    for directory in (tmp_path / "backup", tmp_path / "restore"):
        assert directory.stat().st_mode & 0o777 == 0o700
        for path in directory.iterdir():
            assert path.stat().st_mode & 0o777 == 0o600


def test_actual_cli_success_errors_and_no_secret_output(source, tmp_path):
    command = [sys.executable, "-m", "easy_tdx.web.research_backup"]
    result = subprocess.run(
        command + ["create", "--source", str(source[0]), "--destination", str(tmp_path / "cli")],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["ok"] is True
    assert "password_hash" not in result.stdout and "Restore-test-password" not in result.stdout
    result = subprocess.run(
        command + ["verify", "--source", str(tmp_path / "cli")],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0
    result = subprocess.run(
        command + ["restore", "--source", str(tmp_path / "cli"), "--destination", str(source[0])],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 1 and json.loads(result.stdout)["ok"] is False


def test_near_object_limit_unicode_backup_restore_preserves_raw_digest(source, tmp_path):
    directory, _, archives, _, alice, *_ = source
    value = payload()
    value["large_unknown_future_field"] = "界" * 7_900_000
    value["precise"] = 1.2345678901234567
    key = str(uuid.uuid4())
    record, _ = archives.create(alice.id, key, "chart", value, "近上限完整存档")
    assert record["size_bytes"] > 22 * 1024 * 1024
    backup.create_backup(directory, tmp_path / "large-backup")
    backup.restore_backup(tmp_path / "large-backup", tmp_path / "large-restore")
    restored = ResearchArchive(tmp_path / "large-restore" / "research_archives.db")
    result = restored.get(alice.id, key)
    assert result["digest"] == record["digest"]
    assert result["payload"] == value
