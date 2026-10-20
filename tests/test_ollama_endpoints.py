"""AI Assistant's chat configuration and standalone generate both work."""

import json
from unittest.mock import MagicMock

import pytest

import ollama_client
from config import Settings


def test_ai_assistant_timeout_is_honored(monkeypatch):
    monkeypatch.setenv("OLLAMA_TIMEOUT", "600")
    assert Settings.from_env().ollama_timeout == 600


@pytest.mark.parametrize("endpoint", ["generate", "chat", "chat/"])
def test_generate_json_uses_the_configured_endpoint_protocol(monkeypatch, endpoint):
    monkeypatch.setattr(ollama_client, "OLLAMA_URL", f"http://localhost:11434/api/{endpoint}")
    is_chat = endpoint.rstrip("/") == "chat"
    response_data = (
        {"message": {"role": "assistant", "content": '{"ok":true}'}}
        if is_chat
        else {"response": '{"ok":true}'}
    )
    response = MagicMock()
    response.__enter__.return_value.read.return_value = json.dumps(response_data).encode()
    urlopen = MagicMock(return_value=response)
    monkeypatch.setattr(ollama_client.urllib.request, "urlopen", urlopen)
    assert ollama_client.generate_json("Return JSON", retries=1) == {"ok": True}
    payload = json.loads(urlopen.call_args.args[0].data)
    if is_chat:
        assert payload["messages"] == [{"role": "user", "content": "Return JSON"}]
        assert "prompt" not in payload
    else:
        assert payload["prompt"] == "Return JSON"
        assert "messages" not in payload
