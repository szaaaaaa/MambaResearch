"""Zotero Web API 同步 HTTP client。

仅覆盖 1a 范围内必需的方法签名，让 1b（MCP server 适配层）能直接包装。
upload_pdf 走 Zotero 官方三步流程：(1) 创建 attachment item → (2) 申请
upload auth → (3) 实际 PUT 文件到 Zotero S3。失败任意一步即返回 dict
``{"ok": False, "error": "..."}``，让上层 MCP tool 把错误扁平回给用户。

HTTP 库选 ``requests`` 与项目现有 ``src/ingest/web_fetcher.py`` 对齐；
同步路径足够，MCP server 进程独立、tool 调用串行，无需异步并发。
"""
from __future__ import annotations

import hashlib
import mimetypes
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

from .credentials import ZoteroCredentials, load_zotero_credentials

API_BASE = "https://api.zotero.org"
DEFAULT_TIMEOUT = 30.0
USER_AGENT = "MambaResearch-Zotero/1.0"


@dataclass
class ZoteroClient:
    """Zotero Web API 同步 client。

    Parameters
    ----------
    credentials
        显式传入；未传则调 ``load_zotero_credentials()`` 从 env/.env 解析，
        缺失时抛 ``ZoteroCredentialsMissing``。
    base_url
        API 根 URL；测试可指向 mock server。默认 ``https://api.zotero.org``。
    timeout
        单次 HTTP 请求超时秒数。
    session
        可注入 ``requests.Session`` 便于测试 mock；缺省每次新建。
    """

    credentials: ZoteroCredentials | None = None
    base_url: str = API_BASE
    timeout: float = DEFAULT_TIMEOUT
    session: requests.Session | None = None

    def __post_init__(self) -> None:
        if self.credentials is None:
            self.credentials = load_zotero_credentials()

    # ---- 内部 ----------------------------------------------------------

    def _headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        headers = {
            "Zotero-API-Key": self.credentials.api_key,  # type: ignore[union-attr]
            "Zotero-API-Version": "3",
            "User-Agent": USER_AGENT,
        }
        if extra:
            headers.update(extra)
        return headers

    def _user_url(self, suffix: str) -> str:
        uid = self.credentials.user_id  # type: ignore[union-attr]
        return f"{self.base_url}/users/{uid}{suffix}"

    def _request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        sess = self.session or requests
        return sess.request(method, url, timeout=self.timeout, **kwargs)

    # ---- 公开 API -------------------------------------------------------

    def list_collections(self) -> list[dict[str, Any]]:
        """列出当前 user library 的所有 collection。

        Returns
        -------
        list of dict
            每条含 ``key`` / ``name`` 至少。空 library 返回 ``[]``。
        """
        resp = self._request("GET", self._user_url("/collections"), headers=self._headers())
        resp.raise_for_status()
        items = resp.json()
        return [
            {"key": str(it.get("key", "")), "name": str(it.get("data", {}).get("name", ""))}
            for it in items
            if isinstance(it, dict)
        ]

    def search(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        """全文搜 user library。

        Parameters
        ----------
        query
            自由文本查询。
        limit
            返回上限，Zotero 服务端最大 100。

        Returns
        -------
        list of dict
            每条含 ``key`` / ``title`` / ``creators`` / ``itemType``。
        """
        params = {"q": query.strip(), "qmode": "everything", "limit": str(min(limit, 100))}
        resp = self._request(
            "GET", self._user_url("/items"), headers=self._headers(), params=params
        )
        resp.raise_for_status()
        out: list[dict[str, Any]] = []
        for it in resp.json():
            if not isinstance(it, dict):
                continue
            data = it.get("data", {}) if isinstance(it.get("data"), dict) else {}
            out.append(
                {
                    "key": str(it.get("key", "")),
                    "title": str(data.get("title", "")),
                    "itemType": str(data.get("itemType", "")),
                    "creators": data.get("creators", []),
                }
            )
        return out

    def get_item(self, item_key: str) -> dict[str, Any]:
        """取单个 item 详情（``data`` 段直接返回）。"""
        resp = self._request(
            "GET", self._user_url(f"/items/{item_key}"), headers=self._headers()
        )
        resp.raise_for_status()
        body = resp.json()
        if not isinstance(body, dict):
            return {}
        data = body.get("data", {})
        return data if isinstance(data, dict) else {}

    def add_tag(self, item_key: str, tags: list[str]) -> dict[str, Any]:
        """给 item 追加 tag（合并不覆盖）。

        Returns
        -------
        dict
            ``{"ok": True, "tags": [...]}`` 或 ``{"ok": False, "error": "..."}``.
        """
        existing = self.get_item(item_key)
        current_tags = existing.get("tags", []) if isinstance(existing.get("tags"), list) else []
        current_set = {
            str(t.get("tag", "")) for t in current_tags if isinstance(t, dict) and t.get("tag")
        }
        merged = sorted(current_set | {t for t in tags if t})
        payload = [{"tag": t} for t in merged]
        # PATCH 走 If-Unmodified-Since-Version header；这里简化为读 version
        version = existing.get("version", 0)
        resp = self._request(
            "PATCH",
            self._user_url(f"/items/{item_key}"),
            headers=self._headers({"If-Unmodified-Since-Version": str(version)}),
            json={"tags": payload},
        )
        if resp.status_code >= 400:
            return {"ok": False, "error": f"HTTP {resp.status_code}: {resp.text[:200]}"}
        return {"ok": True, "tags": [t["tag"] for t in payload]}

    def upload_pdf(
        self,
        local_path: str | Path,
        collection: str | None = None,
        tags: list[str] | None = None,
        title: str | None = None,
        authors: list[str] | None = None,
    ) -> dict[str, Any]:
        """上传本地 PDF 到 Zotero（多步流程）。

        步骤:
            1. 创建 attachment item（content type=application/pdf, linkMode=imported_file）
            2. POST ``/items/<key>/file`` 申请 upload auth（含 md5/filesize）
            3. 按 auth 中的 ``url`` + ``params`` PUT 文件
            4. POST ``/items/<key>/file`` 确认完成（key=upload）

        失败时返回 ``{"ok": False, "error": "..."}``；成功返回
        ``{"ok": True, "item_key": "ABC123", "title": "..."}``。
        """
        path = Path(local_path)
        if not path.exists() or not path.is_file():
            return {"ok": False, "error": f"file not found: {local_path}"}
        if path.suffix.lower() != ".pdf":
            return {"ok": False, "error": f"expected .pdf, got {path.suffix}"}

        try:
            content = path.read_bytes()
        except OSError as exc:
            return {"ok": False, "error": f"read failed: {exc}"}
        md5 = hashlib.md5(content).hexdigest()  # noqa: S324 — Zotero 协议要求 md5
        filesize = len(content)
        mime = mimetypes.guess_type(path.name)[0] or "application/pdf"

        derived_title = title or path.stem
        creators = (
            [{"creatorType": "author", "name": a} for a in authors] if authors else []
        )

        # 步骤 1：创建 attachment item
        item_payload: dict[str, Any] = {
            "itemType": "attachment",
            "linkMode": "imported_file",
            "title": derived_title,
            "filename": path.name,
            "contentType": mime,
            "tags": [{"tag": t} for t in (tags or []) if t],
        }
        if creators:
            item_payload["creators"] = creators
        if collection:
            item_payload["collections"] = [collection]
        create_resp = self._request(
            "POST",
            self._user_url("/items"),
            headers=self._headers({"Content-Type": "application/json"}),
            json=[item_payload],
        )
        if create_resp.status_code >= 400:
            return {"ok": False, "error": f"create item HTTP {create_resp.status_code}: {create_resp.text[:200]}"}
        create_body = create_resp.json()
        success = create_body.get("success", {}) if isinstance(create_body, dict) else {}
        if not success:
            failed = create_body.get("failed", {}) if isinstance(create_body, dict) else {}
            return {"ok": False, "error": f"create item rejected: {failed}"}
        item_key = str(next(iter(success.values())))

        # 步骤 2：申请 upload auth
        auth_resp = self._request(
            "POST",
            self._user_url(f"/items/{item_key}/file"),
            headers=self._headers(
                {
                    "Content-Type": "application/x-www-form-urlencoded",
                    "If-None-Match": "*",
                }
            ),
            data={"md5": md5, "filename": path.name, "filesize": str(filesize), "mtime": "0"},
        )
        if auth_resp.status_code >= 400:
            return {
                "ok": False,
                "item_key": item_key,
                "error": f"upload auth HTTP {auth_resp.status_code}: {auth_resp.text[:200]}",
            }
        auth = auth_resp.json()
        if not isinstance(auth, dict):
            return {"ok": False, "item_key": item_key, "error": "upload auth: bad shape"}
        if auth.get("exists") == 1:
            # 服务端已有同 md5 文件，跳过实际上传
            return {"ok": True, "item_key": item_key, "title": derived_title, "skipped_upload": True}

        upload_url = str(auth.get("url", "")).strip()
        upload_token = str(auth.get("uploadKey", "")).strip()
        prefix = bytes(auth.get("prefix", ""), "utf-8") if isinstance(auth.get("prefix"), str) else b""
        suffix = bytes(auth.get("suffix", ""), "utf-8") if isinstance(auth.get("suffix"), str) else b""
        upload_ct = str(auth.get("contentType", mime)).strip() or mime
        if not upload_url or not upload_token:
            return {"ok": False, "item_key": item_key, "error": "upload auth: missing url/uploadKey"}

        # 步骤 3：POST 拼接体到 Zotero 提供的 url。
        # Zotero 现代上传模式：raw body = prefix + 原始文件字节 + suffix，
        # Content-Type 用 auth.contentType（早期 multipart/form-data 模式已弃）。
        upload_body = prefix + content + suffix
        put_resp = self._request(
            "POST",
            upload_url,
            data=upload_body,
            headers={"Content-Type": upload_ct},
        )
        # Zotero 文档：S3 返回 201/204 视为成功
        if put_resp.status_code not in (200, 201, 204):
            return {
                "ok": False,
                "item_key": item_key,
                "error": f"file upload HTTP {put_resp.status_code}: {put_resp.text[:200]}",
            }

        # 步骤 4：register upload
        reg_resp = self._request(
            "POST",
            self._user_url(f"/items/{item_key}/file"),
            headers=self._headers(
                {
                    "Content-Type": "application/x-www-form-urlencoded",
                    "If-None-Match": "*",
                }
            ),
            data={"upload": upload_token},
        )
        if reg_resp.status_code >= 400:
            return {
                "ok": False,
                "item_key": item_key,
                "error": f"register upload HTTP {reg_resp.status_code}: {reg_resp.text[:200]}",
            }
        return {"ok": True, "item_key": item_key, "title": derived_title}

    def download_attachment(
        self,
        item_key: str,
        dest_dir: str | Path,
        *,
        filename: str | None = None,
    ) -> dict[str, Any]:
        """下载 Zotero item 的 PDF 附件到本地目录。

        如果 ``item_key`` 指向 attachment（``itemType == "attachment"`` 且
        ``contentType == "application/pdf"``），直接 GET 其 ``/file``。
        否则视作 parent item（journalArticle 等），先 GET ``/children`` 取
        首个 PDF attachment 子条目再下载。

        Parameters
        ----------
        item_key
            Zotero item key（attachment 本体或 parent item 任一）。
        dest_dir
            本地目标目录；不存在时按需 mkdir（含父目录）。
        filename
            可选——指定写盘文件名；不传则用 attachment ``data.filename``，
            缺则退回 ``<attachment_key>.pdf``。最终文件名若无 ``.pdf`` 后缀
            会自动追加。

        Returns
        -------
        dict
            成功::

                {"ok": True, "path": "<abs path>", "filename": "<name>",
                 "bytes": N, "attachment_key": "<key>"}

            失败::

                {"ok": False, "error": "<message>"}

            失败原因覆盖：item 不存在 / item 非 attachment 且无 PDF child /
            HTTP 4xx-5xx / 写盘 OSError。
        """
        item = self.get_item(item_key)
        if not item:
            return {"ok": False, "error": f"item not found: {item_key}"}

        item_type = str(item.get("itemType", ""))
        item_content_type = str(item.get("contentType", "")).lower()

        if item_type == "attachment":
            if item_content_type and item_content_type != "application/pdf":
                return {
                    "ok": False,
                    "error": (
                        f"attachment {item_key} contentType={item_content_type}, "
                        "expected application/pdf"
                    ),
                }
            attachment_key = item_key
            attachment_filename = str(item.get("filename") or "") or None
        else:
            children_resp = self._request(
                "GET",
                self._user_url(f"/items/{item_key}/children"),
                headers=self._headers(),
            )
            if children_resp.status_code >= 400:
                return {
                    "ok": False,
                    "error": (
                        f"list children HTTP {children_resp.status_code}: "
                        f"{children_resp.text[:200]}"
                    ),
                }
            try:
                children = children_resp.json()
            except ValueError:
                children = []
            if not isinstance(children, list):
                children = []

            attachment_key = None
            attachment_filename = None
            for child in children:
                if not isinstance(child, dict):
                    continue
                data = child.get("data") if isinstance(child.get("data"), dict) else {}
                if data.get("itemType") != "attachment":
                    continue
                child_ct = str(data.get("contentType", "")).lower()
                if child_ct != "application/pdf":
                    continue
                key = str(child.get("key") or "")
                if not key:
                    continue
                attachment_key = key
                attachment_filename = str(data.get("filename") or "") or None
                break

            if attachment_key is None:
                return {
                    "ok": False,
                    "error": f"item {item_key} has no PDF attachment child",
                }

        dl_resp = self._request(
            "GET",
            self._user_url(f"/items/{attachment_key}/file"),
            headers=self._headers(),
        )
        if dl_resp.status_code >= 400:
            return {
                "ok": False,
                "error": (
                    f"download HTTP {dl_resp.status_code}: {dl_resp.text[:200]}"
                ),
            }
        body = dl_resp.content
        if not body:
            return {
                "ok": False,
                "error": f"empty response for attachment {attachment_key}",
            }

        dest = Path(dest_dir)
        try:
            dest.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return {"ok": False, "error": f"mkdir failed: {exc}"}

        final_name = filename or attachment_filename or f"{attachment_key}.pdf"
        if not final_name.lower().endswith(".pdf"):
            final_name = f"{final_name}.pdf"
        target = dest / final_name
        try:
            target.write_bytes(body)
        except OSError as exc:
            return {"ok": False, "error": f"write failed: {exc}"}

        return {
            "ok": True,
            "path": str(target),
            "filename": final_name,
            "bytes": len(body),
            "attachment_key": attachment_key,
        }
