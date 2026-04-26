"""Zotero client + 凭据层单元测试（mock requests，不打真实 API）。"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.server.integrations.zotero.client import ZoteroClient
from src.server.integrations.zotero.credentials import (
    ZoteroCredentials,
    ZoteroCredentialsMissing,
    load_zotero_credentials,
)


# ----- credentials.py ---------------------------------------------------


def _write_env(path: Path, mapping: dict[str, str]) -> None:
    path.write_text("\n".join(f"{k}={v}" for k, v in mapping.items()) + "\n", encoding="utf-8")


def test_load_credentials_from_env_vars(monkeypatch, tmp_path):
    monkeypatch.setenv("ZOTERO_USER_ID", "12345")
    monkeypatch.setenv("ZOTERO_API_KEY", "secret-key")
    creds = load_zotero_credentials(env_path=tmp_path / "missing.env")
    assert creds.user_id == "12345"
    assert creds.api_key == "secret-key"


def test_load_credentials_from_dotenv_file(monkeypatch, tmp_path):
    monkeypatch.delenv("ZOTERO_USER_ID", raising=False)
    monkeypatch.delenv("ZOTERO_API_KEY", raising=False)
    env = tmp_path / ".env"
    _write_env(env, {"ZOTERO_USER_ID": "67890", "ZOTERO_API_KEY": "file-key"})
    creds = load_zotero_credentials(env_path=env)
    assert creds.user_id == "67890"
    assert creds.api_key == "file-key"


def test_load_credentials_env_overrides_dotenv(monkeypatch, tmp_path):
    monkeypatch.setenv("ZOTERO_USER_ID", "env-id")
    monkeypatch.setenv("ZOTERO_API_KEY", "env-key")
    env = tmp_path / ".env"
    _write_env(env, {"ZOTERO_USER_ID": "file-id", "ZOTERO_API_KEY": "file-key"})
    creds = load_zotero_credentials(env_path=env)
    assert creds.user_id == "env-id"
    assert creds.api_key == "env-key"


def test_load_credentials_missing_raises_with_guidance(monkeypatch, tmp_path):
    monkeypatch.delenv("ZOTERO_USER_ID", raising=False)
    monkeypatch.delenv("ZOTERO_API_KEY", raising=False)
    with pytest.raises(ZoteroCredentialsMissing) as exc:
        load_zotero_credentials(env_path=tmp_path / "missing.env")
    msg = str(exc.value)
    assert "ZOTERO_USER_ID" in msg
    assert "ZOTERO_API_KEY" in msg
    assert "MambaResearch 设置面板" in msg
    assert "zotero.org" in msg


def test_load_credentials_partial_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("ZOTERO_USER_ID", "12345")
    monkeypatch.delenv("ZOTERO_API_KEY", raising=False)
    with pytest.raises(ZoteroCredentialsMissing) as exc:
        load_zotero_credentials(env_path=tmp_path / "missing.env")
    msg = str(exc.value)
    assert "ZOTERO_API_KEY" in msg
    assert "ZOTERO_USER_ID" not in msg.split("missing")[1].split(".")[0]


# ----- client.py: list_collections / search / get_item ------------------


def _make_client(*, response: MagicMock | None = None) -> tuple[ZoteroClient, MagicMock]:
    """构造注入 mock session 的 client，返回 (client, session_mock)。"""
    sess = MagicMock()
    if response is not None:
        sess.request.return_value = response
    creds = ZoteroCredentials(user_id="12345", api_key="test-key")
    return ZoteroClient(credentials=creds, session=sess), sess


def _mock_response(status: int = 200, json_body=None, text: str = "") -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = json_body if json_body is not None else {}
    resp.text = text
    if status >= 400:
        resp.raise_for_status.side_effect = Exception(f"HTTP {status}")
    else:
        resp.raise_for_status.return_value = None
    return resp


def test_list_collections_extracts_key_and_name():
    body = [
        {"key": "AAA", "data": {"name": "Inbox"}},
        {"key": "BBB", "data": {"name": "Phys"}},
        "garbage",  # 非 dict 应被跳过
    ]
    client, sess = _make_client(response=_mock_response(200, json_body=body))
    out = client.list_collections()
    assert out == [{"key": "AAA", "name": "Inbox"}, {"key": "BBB", "name": "Phys"}]
    sess.request.assert_called_once()
    args, kwargs = sess.request.call_args
    assert args[0] == "GET"
    assert "/users/12345/collections" in args[1]
    assert kwargs["headers"]["Zotero-API-Key"] == "test-key"


def test_search_passes_query_and_limit():
    body = [
        {
            "key": "ITEM1",
            "data": {"title": "Mamba paper", "itemType": "preprint", "creators": []},
        }
    ]
    client, sess = _make_client(response=_mock_response(200, json_body=body))
    out = client.search("mamba", limit=5)
    assert out[0]["key"] == "ITEM1"
    assert out[0]["title"] == "Mamba paper"
    args, kwargs = sess.request.call_args
    assert kwargs["params"]["q"] == "mamba"
    assert kwargs["params"]["limit"] == "5"
    assert kwargs["params"]["qmode"] == "everything"


def test_search_clamps_limit_to_100():
    client, sess = _make_client(response=_mock_response(200, json_body=[]))
    client.search("x", limit=500)
    _, kwargs = sess.request.call_args
    assert kwargs["params"]["limit"] == "100"


def test_get_item_returns_data_section():
    client, sess = _make_client(
        response=_mock_response(200, json_body={"data": {"title": "T", "version": 7}})
    )
    out = client.get_item("ITEM1")
    assert out["title"] == "T"
    assert out["version"] == 7


# ----- client.py: add_tag (multi-step) ---------------------------------


def test_add_tag_merges_with_existing_tags():
    creds = ZoteroCredentials(user_id="12345", api_key="test-key")
    sess = MagicMock()
    sess.request.side_effect = [
        # GET /items/<key> → existing
        _mock_response(
            200,
            json_body={
                "data": {
                    "version": 9,
                    "tags": [{"tag": "old"}, {"tag": "shared"}],
                }
            },
        ),
        # PATCH /items/<key>
        _mock_response(204),
    ]
    client = ZoteroClient(credentials=creds, session=sess)
    out = client.add_tag("ITEM1", ["new", "shared"])
    assert out["ok"] is True
    assert sorted(out["tags"]) == ["new", "old", "shared"]
    patch_call = sess.request.call_args_list[1]
    assert patch_call.args[0] == "PATCH"
    assert patch_call.kwargs["headers"]["If-Unmodified-Since-Version"] == "9"
    sent_tags = sorted(t["tag"] for t in patch_call.kwargs["json"]["tags"])
    assert sent_tags == ["new", "old", "shared"]


def test_add_tag_returns_error_on_http_failure():
    creds = ZoteroCredentials(user_id="12345", api_key="test-key")
    sess = MagicMock()
    sess.request.side_effect = [
        _mock_response(200, json_body={"data": {"version": 1, "tags": []}}),
        _mock_response(412, text="precondition failed"),
    ]
    client = ZoteroClient(credentials=creds, session=sess)
    out = client.add_tag("ITEM1", ["x"])
    assert out["ok"] is False
    assert "412" in out["error"]


# ----- client.py: upload_pdf -------------------------------------------


def _write_pdf(path: Path, content: bytes = b"%PDF-1.4 fake") -> Path:
    path.write_bytes(content)
    return path


def test_upload_pdf_full_happy_path(tmp_path):
    creds = ZoteroCredentials(user_id="12345", api_key="test-key")
    pdf_bytes = b"%PDF-1.4 fake content here"
    pdf = _write_pdf(tmp_path / "paper.pdf", pdf_bytes)
    sess = MagicMock()
    sess.request.side_effect = [
        # 1. POST /items create
        _mock_response(200, json_body={"success": {"0": "ABC123"}}),
        # 2. POST /items/<key>/file (auth) — 现代模式 prefix + suffix raw body
        _mock_response(
            200,
            json_body={
                "url": "https://s3.zotero.org/upload",
                "uploadKey": "tok-xyz",
                "prefix": "PRE-",
                "suffix": "-POST",
                "contentType": "application/x-zotero-upload",
            },
        ),
        # 3. POST upload_url
        _mock_response(201),
        # 4. POST /items/<key>/file (register)
        _mock_response(204),
    ]
    client = ZoteroClient(credentials=creds, session=sess)
    out = client.upload_pdf(pdf, collection="C1", tags=["mamba"], title="My Title", authors=["A"])
    assert out["ok"] is True
    assert out["item_key"] == "ABC123"
    assert out["title"] == "My Title"
    assert sess.request.call_count == 4

    # 验第一步 payload 形状
    create_call = sess.request.call_args_list[0]
    item_payload = create_call.kwargs["json"][0]
    assert item_payload["itemType"] == "attachment"
    assert item_payload["linkMode"] == "imported_file"
    assert item_payload["filename"] == "paper.pdf"
    assert item_payload["collections"] == ["C1"]
    assert item_payload["tags"] == [{"tag": "mamba"}]
    assert item_payload["creators"][0]["name"] == "A"

    # 验第三步 raw body 是 prefix + content + suffix，且 Content-Type 用 auth 给的
    upload_call = sess.request.call_args_list[2]
    assert upload_call.args[0] == "POST"
    assert upload_call.args[1] == "https://s3.zotero.org/upload"
    assert upload_call.kwargs["data"] == b"PRE-" + pdf_bytes + b"-POST"
    assert upload_call.kwargs["headers"]["Content-Type"] == "application/x-zotero-upload"


def test_upload_pdf_skips_when_zotero_already_has_file(tmp_path):
    creds = ZoteroCredentials(user_id="12345", api_key="test-key")
    pdf = _write_pdf(tmp_path / "paper.pdf")
    sess = MagicMock()
    sess.request.side_effect = [
        _mock_response(200, json_body={"success": {"0": "DUP1"}}),
        _mock_response(200, json_body={"exists": 1}),
    ]
    client = ZoteroClient(credentials=creds, session=sess)
    out = client.upload_pdf(pdf)
    assert out["ok"] is True
    assert out["item_key"] == "DUP1"
    assert out.get("skipped_upload") is True
    assert sess.request.call_count == 2


def test_upload_pdf_rejects_nonexistent_file(tmp_path):
    client, sess = _make_client(response=_mock_response(200))
    out = client.upload_pdf(tmp_path / "nope.pdf")
    assert out["ok"] is False
    assert "not found" in out["error"]
    sess.request.assert_not_called()


def test_upload_pdf_rejects_non_pdf_extension(tmp_path):
    txt = tmp_path / "doc.txt"
    txt.write_text("not a pdf")
    client, sess = _make_client(response=_mock_response(200))
    out = client.upload_pdf(txt)
    assert out["ok"] is False
    assert ".txt" in out["error"]
    sess.request.assert_not_called()


def test_upload_pdf_returns_error_on_create_failure(tmp_path):
    pdf = _write_pdf(tmp_path / "paper.pdf")
    creds = ZoteroCredentials(user_id="12345", api_key="test-key")
    sess = MagicMock()
    sess.request.return_value = _mock_response(403, text="forbidden")
    client = ZoteroClient(credentials=creds, session=sess)
    out = client.upload_pdf(pdf)
    assert out["ok"] is False
    assert "create item" in out["error"]
    assert "403" in out["error"]


def test_upload_pdf_returns_error_when_create_rejected(tmp_path):
    pdf = _write_pdf(tmp_path / "paper.pdf")
    creds = ZoteroCredentials(user_id="12345", api_key="test-key")
    sess = MagicMock()
    sess.request.return_value = _mock_response(
        200, json_body={"success": {}, "failed": {"0": "validation error"}}
    )
    client = ZoteroClient(credentials=creds, session=sess)
    out = client.upload_pdf(pdf)
    assert out["ok"] is False
    assert "rejected" in out["error"]


# ----- client.py: __post_init__ wires credentials ----------------------


def test_client_loads_credentials_when_not_passed(monkeypatch, tmp_path):
    monkeypatch.setenv("ZOTERO_USER_ID", "auto-id")
    monkeypatch.setenv("ZOTERO_API_KEY", "auto-key")
    # 注：不 patch ENV_PATH，因为 env vars 已 set 优先
    client = ZoteroClient()
    assert client.credentials.user_id == "auto-id"
    assert client.credentials.api_key == "auto-key"


def test_client_propagates_credentials_missing(monkeypatch, tmp_path):
    monkeypatch.delenv("ZOTERO_USER_ID", raising=False)
    monkeypatch.delenv("ZOTERO_API_KEY", raising=False)
    monkeypatch.setattr(
        "src.server.integrations.zotero.credentials.ENV_PATH",
        tmp_path / "absent.env",
    )
    with pytest.raises(ZoteroCredentialsMissing):
        ZoteroClient()
