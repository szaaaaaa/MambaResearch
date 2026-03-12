from __future__ import annotations

import asyncio
import os
import unittest
from unittest.mock import AsyncMock, MagicMock, mock_open, patch

import yaml
from fastapi import HTTPException

from src.server.routes import config as config_routes
from src.server.settings import APP_RUNTIME_MODE


class ServerConfigRoutesTest(unittest.TestCase):
    def test_credential_status_reports_dotenv_presence(self) -> None:
        with patch.dict(os.environ, {}, clear=True), patch.object(
            config_routes,
            "_read_env_file",
            return_value={"GEMINI_API_KEY": "file-key"},
        ):
            out = config_routes._credential_status({"GEMINI_API_KEY": "file-key"})

        self.assertEqual(out["GEMINI_API_KEY"], {"present": True, "source": "dotenv"})

    def test_save_credentials_writes_dotenv(self) -> None:
        request = MagicMock()
        request.json = AsyncMock(return_value={"GEMINI_API_KEY": "browser-key"})

        with patch.dict(os.environ, {}, clear=True), patch.object(
            config_routes, "_read_env_file", return_value={}
        ), patch.object(config_routes, "_write_env_file") as write_mock:
            out = asyncio.run(config_routes.save_credentials(request))

        write_mock.assert_called_once_with({"GEMINI_API_KEY": "browser-key"})
        self.assertEqual(out["status"], "success")
        self.assertEqual(out["status_map"]["GEMINI_API_KEY"], {"present": True, "source": "dotenv"})

    def test_save_credentials_keeps_existing_dotenv_when_payload_is_blank(self) -> None:
        request = MagicMock()
        request.json = AsyncMock(return_value={"GEMINI_API_KEY": ""})

        with patch.dict(os.environ, {}, clear=True), patch.object(
            config_routes,
            "_read_env_file",
            return_value={"GEMINI_API_KEY": "saved-key"},
        ), patch.object(config_routes, "_write_env_file") as write_mock:
            out = asyncio.run(config_routes.save_credentials(request))

        write_mock.assert_called_once_with({"GEMINI_API_KEY": "saved-key"})
        self.assertEqual(out["status_map"]["GEMINI_API_KEY"], {"present": True, "source": "dotenv"})

    def test_merge_runtime_credentials_prefers_request_values(self) -> None:
        out = config_routes._merge_runtime_credentials(
            base_env={"OPENAI_API_KEY": "env"},
            saved_credentials={"GEMINI_API_KEY": "saved"},
            request_credentials={"OPENAI_API_KEY": "browser", "GITHUB_TOKEN": "gh-token"},
        )

        self.assertEqual(out["OPENAI_API_KEY"], "browser")
        self.assertEqual(out["GEMINI_API_KEY"], "saved")
        self.assertEqual(out["GITHUB_TOKEN"], "gh-token")

    def test_get_config_includes_runtime_mode_metadata(self) -> None:
        config_path = MagicMock()
        config_path.exists.return_value = True
        config_path.open = mock_open(read_data="llm:\n  provider: openai\n")

        with patch.object(config_routes, "CONFIG_PATH", config_path):
            out = config_routes.get_config()

        self.assertEqual(out["runtime_mode"], APP_RUNTIME_MODE)
        self.assertEqual(out["llm"]["provider"], "openai")

    def test_save_config_ignores_runtime_mode_metadata(self) -> None:
        request = MagicMock()
        request.json = AsyncMock(
            return_value={
                "runtime_mode": "3-agent",
                "llm": {"provider": "openai"},
            }
        )

        config_path = MagicMock()
        config_path.parent = MagicMock()
        file_handle = mock_open()
        config_path.open = file_handle

        with patch.object(config_routes, "CONFIG_PATH", config_path):
            out = asyncio.run(config_routes.save_config(request))

        saved_yaml = "".join(call.args[0] for call in file_handle().write.call_args_list)
        saved = yaml.safe_load(saved_yaml)

        self.assertEqual(out["status"], "success")
        self.assertEqual(saved, {"llm": {"provider": "openai"}})

    def test_save_config_rejects_non_object_payload(self) -> None:
        request = MagicMock()
        request.json = AsyncMock(return_value=["bad"])

        with self.assertRaises(HTTPException) as exc:
            asyncio.run(config_routes.save_config(request))

        self.assertEqual(exc.exception.status_code, 400)

    def test_save_credentials_rejects_non_object_payload(self) -> None:
        request = MagicMock()
        request.json = AsyncMock(return_value=["bad"])

        with self.assertRaises(HTTPException) as exc:
            asyncio.run(config_routes.save_credentials(request))

        self.assertEqual(exc.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
