import pytest

from src.dynamic_os.tools.backends import ConfiguredLLMClient


@pytest.mark.parametrize("effort", ["high", "invalid"])
def test_subscription_payload_forwards_effort_and_open_map_schema(tmp_path, effort):
    client = ConfiguredLLMClient(saved_env={}, workspace_root=tmp_path,
                                 config={"llm": {"openai_codex": {"reasoning_effort": effort}}})
    args = dict(model="gpt-6-astra", messages=[{"role": "user", "content": "question"}],
                temperature=0.2, max_tokens=123, response_schema={"type": "object", "additionalProperties": True},
                default_instructions="Answer the question.")
    if effort == "invalid":
        with pytest.raises(ValueError, match="reasoning_effort"):
            client._openai_codex_request_payload(**args)
    else:
        payload = client._openai_codex_request_payload(**args)
        assert payload["reasoning"] == {"effort": "high"}
        assert payload["text"]["format"]["strict"] is False
        assert payload["max_output_tokens"] == 123
