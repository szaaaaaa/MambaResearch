"""Colab drive_locator + mcp_server 单元测试。

drive_locator 测试用 in-process SQLite mini DB 验真实的 SQL 路径；
不打 Drive Desktop 真 metadata（platform-specific，CI 不可控）。
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

from src.server.integrations.colab import drive_locator, mcp_server


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_fake_drivefs(root: Path, account_dirs: dict[str, dict[str, str]]) -> Path:
    """构造形如 root/<account>/metadata_sqlite_db 的 fake DriveFS。

    Parameters
    ----------
    root
        DriveFS 根目录（tmp_path 子）。
    account_dirs
        ``{account_id: {filename: stable_id, ...}}``。每条对应 items 表一行。
    """
    root.mkdir(parents=True, exist_ok=True)
    for account, files in account_dirs.items():
        acc_dir = root / account
        acc_dir.mkdir(parents=True, exist_ok=True)
        db_path = acc_dir / "metadata_sqlite_db"
        conn = sqlite3.connect(db_path)
        try:
            conn.execute(
                "CREATE TABLE items (stable_id TEXT, local_title TEXT, parent_stable_id TEXT)"
            )
            for filename, stable in files.items():
                conn.execute(
                    "INSERT INTO items (stable_id, local_title, parent_stable_id) VALUES (?,?,?)",
                    (stable, filename, "root"),
                )
            conn.commit()
        finally:
            conn.close()
    return root


# ---------------------------------------------------------------------------
# drive_locator: lookup_drive_id
# ---------------------------------------------------------------------------


def test_lookup_drive_id_finds_match(tmp_path):
    fake_root = _build_fake_drivefs(
        tmp_path / "DriveFS",
        {"acct-001": {"foo.ipynb": "ABC123XYZ"}},
    )
    db = fake_root / "acct-001" / "metadata_sqlite_db"
    found = drive_locator.lookup_drive_id(Path("X:/whatever/foo.ipynb"), db)
    assert found == "ABC123XYZ"


def test_lookup_drive_id_strips_id_prefix(tmp_path):
    fake_root = _build_fake_drivefs(
        tmp_path / "DriveFS",
        {"acct-001": {"bar.ipynb": "id:WITH_PREFIX"}},
    )
    db = fake_root / "acct-001" / "metadata_sqlite_db"
    assert drive_locator.lookup_drive_id(Path("/bar.ipynb"), db) == "WITH_PREFIX"


def test_lookup_drive_id_returns_none_for_unknown_filename(tmp_path):
    fake_root = _build_fake_drivefs(
        tmp_path / "DriveFS",
        {"acct-001": {"foo.ipynb": "X"}},
    )
    db = fake_root / "acct-001" / "metadata_sqlite_db"
    assert drive_locator.lookup_drive_id(Path("/nope.ipynb"), db) is None


def test_lookup_drive_id_handles_missing_table(tmp_path):
    """schema 不匹配（无 items 表）→ 不抛异常，返 None。"""
    db = tmp_path / "broken.db"
    sqlite3.connect(db).close()  # 空 schema
    assert drive_locator.lookup_drive_id(Path("/x.ipynb"), db) is None


def test_lookup_drive_id_handles_unreadable_file(tmp_path):
    db = tmp_path / "missing.db"
    assert drive_locator.lookup_drive_id(Path("/x.ipynb"), db) is None


# ---------------------------------------------------------------------------
# drive_locator: find_account_dbs / resolve_drive_id
# ---------------------------------------------------------------------------


def test_find_account_dbs_lists_db_files_per_account(tmp_path):
    fake_root = _build_fake_drivefs(
        tmp_path / "DriveFS",
        {"acct-001": {"a.ipynb": "X"}, "acct-002": {"b.ipynb": "Y"}},
    )
    dbs = drive_locator.find_account_dbs(fake_root)
    assert sorted(p.parent.name for p in dbs) == ["acct-001", "acct-002"]


def test_find_account_dbs_skips_dirs_without_db(tmp_path):
    root = tmp_path / "DriveFS"
    root.mkdir()
    (root / "empty-acct").mkdir()
    assert drive_locator.find_account_dbs(root) == []


def test_find_account_dbs_returns_empty_when_root_missing(tmp_path):
    assert drive_locator.find_account_dbs(tmp_path / "absent") == []


def test_resolve_drive_id_returns_first_match(tmp_path):
    fake_root = _build_fake_drivefs(
        tmp_path / "DriveFS",
        {
            "acct-001": {"foo.ipynb": "FROM_ACCT_1"},
            "acct-002": {"bar.ipynb": "FROM_ACCT_2"},
        },
    )
    real_file = tmp_path / "bar.ipynb"
    real_file.write_text("notebook content")
    found = drive_locator.resolve_drive_id(real_file, drivefs_root=fake_root)
    assert found == "FROM_ACCT_2"


def test_resolve_drive_id_returns_none_for_nonexistent_file(tmp_path):
    fake_root = _build_fake_drivefs(
        tmp_path / "DriveFS",
        {"acct-001": {"foo.ipynb": "X"}},
    )
    assert drive_locator.resolve_drive_id(tmp_path / "no_file.ipynb", drivefs_root=fake_root) is None


# ---------------------------------------------------------------------------
# mcp_server: url_for / url_for_github
# ---------------------------------------------------------------------------


def _structured(resp: dict) -> dict:
    return resp["result"]["structuredContent"]


def _is_error(resp: dict) -> bool:
    return bool(resp["result"].get("isError"))


def _err_text(resp: dict) -> str:
    return resp["result"]["content"][0]["text"]


def test_initialize_returns_protocol():
    resp = mcp_server._handle_initialize(1)
    assert resp["result"]["protocolVersion"] == "2024-11-05"
    assert resp["result"]["serverInfo"]["name"] == mcp_server.SERVER_NAME


def test_tools_list_returns_two_tools():
    resp = mcp_server._handle_tools_list(1)
    names = sorted(t["name"] for t in resp["result"]["tools"])
    assert names == ["url_for", "url_for_github"]


def test_url_for_drive_id_mode_when_lookup_succeeds(tmp_path):
    nb = tmp_path / "exp.ipynb"
    nb.write_text("notebook")
    with patch.object(mcp_server, "resolve_drive_id", return_value="DRIVE_XYZ"):
        resp = mcp_server._handle_tools_call(
            1, {"name": "url_for", "arguments": {"local_path": str(nb)}}
        )
    s = _structured(resp)
    assert s["mode"] == "drive_id"
    assert s["drive_id"] == "DRIVE_XYZ"
    assert s["colab_url"] == f"{mcp_server.COLAB_BASE}/drive/DRIVE_XYZ"


def test_url_for_fallback_when_lookup_fails(tmp_path):
    nb = tmp_path / "untracked.ipynb"
    nb.write_text("x")
    with patch.object(mcp_server, "resolve_drive_id", return_value=None):
        resp = mcp_server._handle_tools_call(
            1, {"name": "url_for", "arguments": {"local_path": str(nb)}}
        )
    s = _structured(resp)
    assert s["mode"] == "fallback"
    assert s["colab_url"] == mcp_server.FALLBACK_UPLOAD_URL
    assert s["drive_id"] is None
    assert "Drive Desktop" in s["hint"]


def test_url_for_rejects_non_ipynb_extension(tmp_path):
    py = tmp_path / "x.py"
    py.write_text("print(1)")
    resp = mcp_server._handle_tools_call(
        1, {"name": "url_for", "arguments": {"local_path": str(py)}}
    )
    assert _is_error(resp)
    assert ".ipynb" in _err_text(resp)


def test_url_for_rejects_missing_file(tmp_path):
    resp = mcp_server._handle_tools_call(
        1, {"name": "url_for", "arguments": {"local_path": str(tmp_path / "nope.ipynb")}}
    )
    assert _is_error(resp)
    assert "不存在" in _err_text(resp)


def test_url_for_github_default_branch():
    resp = mcp_server._handle_tools_call(
        1,
        {
            "name": "url_for_github",
            "arguments": {"repo": "owner/repo", "path": "notebooks/foo.ipynb"},
        },
    )
    s = _structured(resp)
    assert s["mode"] == "github"
    assert s["branch"] == "main"
    assert s["colab_url"] == (
        f"{mcp_server.COLAB_BASE}/github/owner/repo/blob/main/notebooks/foo.ipynb"
    )


def test_url_for_github_custom_branch_strips_slashes():
    resp = mcp_server._handle_tools_call(
        1,
        {
            "name": "url_for_github",
            "arguments": {
                "repo": "/owner/repo/",
                "path": "/dir/foo.ipynb",
                "branch": "dev",
            },
        },
    )
    s = _structured(resp)
    assert s["repo"] == "owner/repo"
    assert s["path"] == "dir/foo.ipynb"
    assert s["colab_url"].endswith("/dev/dir/foo.ipynb")


def test_url_for_github_rejects_invalid_repo():
    resp = mcp_server._handle_tools_call(
        1,
        {"name": "url_for_github", "arguments": {"repo": "noslash", "path": "a.ipynb"}},
    )
    assert _is_error(resp)


def test_unknown_tool_returns_error():
    resp = mcp_server._handle_tools_call(1, {"name": "ghost", "arguments": {}})
    assert _is_error(resp)


def test_default_mcp_config_returns_stdio_entry(tmp_path):
    cfg = mcp_server.default_mcp_config(tmp_path)
    assert mcp_server.DEFAULT_SERVER_KEY in cfg
    assert "src.server.integrations.colab.mcp_server" in cfg[mcp_server.DEFAULT_SERVER_KEY]["args"]


def test_default_mcp_config_disabled_via_env(monkeypatch, tmp_path):
    monkeypatch.setenv("MAMBA_COLAB_MCP_DISABLED", "1")
    assert mcp_server.default_mcp_config(tmp_path) == {}
