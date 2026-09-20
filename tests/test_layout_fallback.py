from unittest.mock import patch

from agent.layout_fallback import OllamaLayoutFallback


def test_ollama_layout_fallback_returns_only_an_existing_safe_key():
    candidate = {"email": "person@example.com", "current_title": "Data Engineer"}
    with patch("agent.layout_fallback.generate_json", return_value={"candidate_key": "current_title"}) as generate:
        key = OllamaLayoutFallback().resolve_candidate_key("Professional headline", candidate)

    assert key == "current_title"
    prompt = generate.call_args.args[0]
    assert "Data Engineer" not in prompt
    assert "person@example.com" not in prompt


def test_ollama_layout_fallback_never_maps_sensitive_questions():
    with patch("agent.layout_fallback.generate_json") as generate:
        key = OllamaLayoutFallback().resolve_candidate_key(
            "What is your expected salary?", {"email": "person@example.com"}
        )

    assert key is None
    generate.assert_not_called()


def test_ollama_layout_fallback_rejects_unlisted_model_key():
    with patch("agent.layout_fallback.generate_json", return_value={"candidate_key": "salary"}):
        key = OllamaLayoutFallback().resolve_candidate_key(
            "Contact detail", {"email": "person@example.com"}
        )

    assert key is None
