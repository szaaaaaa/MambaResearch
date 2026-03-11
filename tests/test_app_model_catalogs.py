from __future__ import annotations

import asyncio
import os
import unittest
from unittest.mock import AsyncMock, MagicMock, mock_open, patch

import app
import yaml


class AppModelCatalogTest(unittest.TestCase):
    def test_first_secret_value_reads_only_environment(self) -> None:
        with patch.dict(os.environ, {"GEMINI_API_KEY": "env-key"}, clear=True), patch.object(
            app,
            "_read_env_file",
            return_value={"GEMINI_API_KEY": "file-key"},
        ):
            out = app._first_secret_value("GEMINI_API_KEY", "GOOGLE_API_KEY")

        self.assertEqual(out, "env-key")

    def test_credential_status_reports_dotenv_presence(self) -> None:
        with patch.dict(os.environ, {}, clear=True), patch.object(
            app,
            "_read_env_file",
            return_value={"GEMINI_API_KEY": "file-key"},
        ):
            out = app._credential_status({"GEMINI_API_KEY": "file-key"})

        self.assertEqual(out["GEMINI_API_KEY"], {"present": True, "source": "dotenv"})

    def test_save_credentials_writes_dotenv(self) -> None:
        request = MagicMock()
        request.json = AsyncMock(return_value={"GEMINI_API_KEY": "browser-key"})

        with patch.dict(os.environ, {}, clear=True), patch.object(app, "_read_env_file", return_value={}), patch.object(
            app,
            "_write_env_file",
        ) as write_mock:
            out = asyncio.run(app.save_credentials(request))

        write_mock.assert_called_once_with({"GEMINI_API_KEY": "browser-key"})
        self.assertEqual(out["status"], "success")
        self.assertEqual(out["status_map"]["GEMINI_API_KEY"], {"present": True, "source": "dotenv"})

    def test_save_credentials_keeps_existing_dotenv_when_payload_is_blank(self) -> None:
        request = MagicMock()
        request.json = AsyncMock(return_value={"GEMINI_API_KEY": ""})

        with patch.dict(os.environ, {}, clear=True), patch.object(
            app,
            "_read_env_file",
            return_value={"GEMINI_API_KEY": "saved-key"},
        ), patch.object(app, "_write_env_file") as write_mock:
            out = asyncio.run(app.save_credentials(request))

        write_mock.assert_called_once_with({"GEMINI_API_KEY": "saved-key"})
        self.assertEqual(out["status_map"]["GEMINI_API_KEY"], {"present": True, "source": "dotenv"})

    def test_build_run_command_accepts_prompt_alias(self) -> None:
        out = app._build_run_command({"runOverrides": {"prompt": "continue from current draft", "mode": "os"}})

        self.assertIn("--topic", out)
        self.assertIn("continue from current draft", out)
        self.assertEqual(out[-2:], ["--mode", "os"])

    def test_build_run_command_forces_os_mode(self) -> None:
        out = app._build_run_command({"runOverrides": {"prompt": "topic", "mode": "legacy"}})

        self.assertIn("--mode", out)
        self.assertEqual(out[-1], "os")

    def test_merge_runtime_credentials_prefers_request_values(self) -> None:
        out = app._merge_runtime_credentials(
            base_env={"OPENAI_API_KEY": "env"},
            saved_credentials={"GEMINI_API_KEY": "saved"},
            request_credentials={"OPENAI_API_KEY": "browser", "GITHUB_TOKEN": "gh-token"},
        )

        self.assertEqual(out["OPENAI_API_KEY"], "browser")
        self.assertEqual(out["GEMINI_API_KEY"], "saved")
        self.assertEqual(out["GITHUB_TOKEN"], "gh-token")

    def test_build_openai_catalog_keeps_only_llm_models(self) -> None:
        payload = [
            {"id": "gpt-4o"},
            {"id": "o4-mini"},
            {"id": "text-embedding-3-small"},
            {"id": "gpt-image-1"},
            {"id": "whisper-1"},
        ]

        out = app._build_openai_catalog(payload)

        self.assertEqual(out["vendors"], [{"value": "openai", "label": "OpenAI"}])
        self.assertEqual(
            [item["value"] for item in out["modelsByVendor"]["openai"]],
            ["gpt-4o", "o4-mini"],
        )

    def test_build_gemini_catalog_keeps_generate_content_models(self) -> None:
        payload = [
            {
                "name": "models/gemini-2.5-pro",
                "displayName": "Gemini 2.5 Pro",
                "supportedGenerationMethods": ["generateContent", "countTokens"],
            },
            {
                "name": "models/text-embedding-004",
                "displayName": "Text Embedding 004",
                "supportedGenerationMethods": ["embedContent"],
            },
            {
                "name": "models/aqa",
                "displayName": "AQA",
                "supportedGenerationMethods": ["generateContent"],
            },
        ]

        out = app._build_gemini_catalog(payload)

        self.assertEqual(out["vendors"], [{"value": "google", "label": "Google"}])
        self.assertEqual(
            [item["value"] for item in out["modelsByVendor"]["google"]],
            ["gemini-2.5-pro"],
        )

    def test_openai_models_endpoint_requires_key(self) -> None:
        with patch.dict(os.environ, {}, clear=True), patch.object(app, "_read_env_file", return_value={}):
            out = app.get_openai_models()

        self.assertTrue(out["missing_api_key"])
        self.assertEqual(out["model_count"], 0)

    def test_gemini_models_endpoint_uses_google_api_key_fallback(self) -> None:
        payload = [
            {
                "name": "models/gemini-2.5-flash",
                "displayName": "Gemini 2.5 Flash",
                "supportedGenerationMethods": ["generateContent"],
            }
        ]
        with patch.dict(os.environ, {"GOOGLE_API_KEY": "test-key"}, clear=True), patch.object(
            app,
            "_read_env_file",
            return_value={},
        ), patch.object(app, "_request_paginated_json", return_value=payload) as request_mock:
            out = app.get_gemini_models()

        request_mock.assert_called_once()
        self.assertEqual(out["model_count"], 1)
        self.assertEqual(out["modelsByVendor"]["google"][0]["value"], "gemini-2.5-flash")

    def test_get_config_includes_runtime_mode_metadata(self) -> None:
        config_path = MagicMock()
        config_path.exists.return_value = True
        config_path.open = mock_open(read_data="llm:\n  provider: openai\n")

        with patch.object(app, "CONFIG_PATH", config_path):
            out = app.get_config()

        self.assertEqual(out["runtime_mode"], app.APP_RUNTIME_MODE)
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

        with patch.object(app, "CONFIG_PATH", config_path):
            out = asyncio.run(app.save_config(request))

        saved_yaml = "".join(call.args[0] for call in file_handle().write.call_args_list)
        saved = yaml.safe_load(saved_yaml)

        self.assertEqual(out["status"], "success")
        self.assertEqual(saved, {"llm": {"provider": "openai"}})


if __name__ == "__main__":
    unittest.main()
