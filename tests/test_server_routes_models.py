from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from src.server.routes import models as model_routes


class ServerModelRoutesTest(unittest.TestCase):
    def test_first_secret_value_reads_only_environment(self) -> None:
        with patch.dict(os.environ, {"GEMINI_API_KEY": "env-key"}, clear=True), patch.object(
            model_routes,
            "_read_env_file",
            return_value={"GEMINI_API_KEY": "file-key"},
        ):
            out = model_routes._first_secret_value("GEMINI_API_KEY", "GOOGLE_API_KEY")

        self.assertEqual(out, "env-key")

    def test_build_openai_catalog_keeps_only_llm_models(self) -> None:
        payload = [
            {"id": "gpt-4o"},
            {"id": "o4-mini"},
            {"id": "text-embedding-3-small"},
            {"id": "gpt-image-1"},
            {"id": "whisper-1"},
        ]

        out = model_routes._build_openai_catalog(payload)

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

        out = model_routes._build_gemini_catalog(payload)

        self.assertEqual(out["vendors"], [{"value": "google", "label": "Google"}])
        self.assertEqual(
            [item["value"] for item in out["modelsByVendor"]["google"]],
            ["gemini-2.5-pro"],
        )

    def test_openai_models_endpoint_requires_key(self) -> None:
        with patch.dict(os.environ, {}, clear=True), patch.object(model_routes, "_read_env_file", return_value={}):
            out = model_routes.get_openai_models()

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
            model_routes,
            "_read_env_file",
            return_value={},
        ), patch.object(model_routes, "_request_paginated_json", return_value=payload) as request_mock:
            out = model_routes.get_gemini_models()

        request_mock.assert_called_once()
        self.assertEqual(out["model_count"], 1)
        self.assertEqual(out["modelsByVendor"]["google"][0]["value"], "gemini-2.5-flash")

    def test_openrouter_models_raises_http_exception_on_provider_failure(self) -> None:
        with patch.object(model_routes, "_request_json", side_effect=model_routes.urllib.error.HTTPError("", 429, "", None, None)):
            with self.assertRaises(HTTPException) as exc:
                model_routes.get_openrouter_models()

        self.assertEqual(exc.exception.status_code, 429)


if __name__ == "__main__":
    unittest.main()
