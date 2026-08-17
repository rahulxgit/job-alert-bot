"""Coverage for the truncated-JSON recovery path and the config wiring that
increases output-token budgets / timeouts for the AI Gateway and Gemini.
Regression tests for the 2026-08-17 incident: 24/111 jobs failed AI
evaluation with "LLM response did not contain a JSON object" because a
512/1024-token default output budget cut structured verdicts off mid-JSON,
and a 12s gateway timeout killed requests before a cold Render provider
could respond."""
from unittest.mock import MagicMock, patch

import config
from utils.llm_json import parse_json_object


def test_parses_clean_json_unchanged():
    text = '{"fit_score": 70, "why": ["a", "b"], "gaps": []}'
    parsed = parse_json_object(text)
    assert parsed["fit_score"] == 70
    assert parsed["why"] == ["a", "b"]


def test_repairs_json_truncated_mid_string_value():
    # Cut off in the middle of the last "why" string, no closing brackets.
    truncated = (
        '{"fit_score": 70, "role_match": 18, "why": ["React and Node.js '
        'experience match", "Strong project evidence from DriveCl'
    )
    parsed = parse_json_object(truncated)
    assert parsed["fit_score"] == 70
    assert parsed["role_match"] == 18
    # The dangling incomplete string is dropped; the completed array entry survives.
    assert parsed["why"] == ["React and Node.js experience match"]


def test_repairs_json_truncated_mid_array():
    truncated = '{"fit_score": 55, "gaps": ["missing AWS experience", "no team lead'
    parsed = parse_json_object(truncated)
    assert parsed["fit_score"] == 55
    assert parsed["gaps"] == ["missing AWS experience"]


def test_repairs_json_truncated_right_after_a_complete_field():
    truncated = '{"fit_score": 82, "role_match": 20, "experience_match":'
    parsed = parse_json_object(truncated)
    assert parsed["fit_score"] == 82
    assert parsed["role_match"] == 20
    assert "experience_match" not in parsed


def test_still_raises_when_nothing_usable_is_present():
    try:
        parse_json_object("Sorry, I can't help with that request.")
    except ValueError as exc:
        assert "did not contain a JSON object" in str(exc)
    else:
        raise AssertionError("garbage input was not rejected")


def test_still_raises_on_empty_object_fragment():
    try:
        parse_json_object("{")
    except ValueError:
        pass
    else:
        raise AssertionError("an empty open-brace fragment should not parse")


def test_gateway_timeout_and_token_budget_defaults_are_generous():
    # Locks in the fix: 12s/no-maxTokens was the root cause of the incident.
    assert config.AI_GATEWAY_TIMEOUT_SECONDS >= 60
    assert config.AI_GATEWAY_MAX_TOKENS >= 2000


def test_gemini_timeout_and_token_budget_defaults_are_generous():
    assert config.GEMINI_TIMEOUT_SECONDS >= 40
    assert config.GEMINI_MAX_OUTPUT_TOKENS >= 1200


def test_gateway_provider_sends_max_tokens_in_request_body():
    from ai.gateway_provider import GatewayProvider

    fake_response = MagicMock()
    fake_response.status_code = 200
    fake_response.json.return_value = {
        "content": {
            "fit_score": 70, "role_match": 15, "experience_match": 15,
            "technical_match": 20, "project_match": 8, "education_match": 8,
            "location_match": 4, "company_quality": 3, "decision": "good_match",
            "is_fresher_appropriate": True, "why": [], "gaps": [],
        }
    }
    fake_response.raise_for_status = lambda: None

    with patch("ai.gateway_provider.requests.post", return_value=fake_response) as mock_post:
        GatewayProvider().evaluate("dummy prompt")

    sent_body = mock_post.call_args.kwargs["json"]
    assert sent_body["maxTokens"] == config.AI_GATEWAY_MAX_TOKENS
    assert mock_post.call_args.kwargs["timeout"] == config.AI_GATEWAY_TIMEOUT_SECONDS


def test_gemini_provider_sends_configured_max_output_tokens():
    from ai.gemini_provider import GeminiProvider

    fake_response = MagicMock()
    fake_response.status_code = 200
    fake_response.raise_for_status = lambda: None
    fake_response.json.return_value = {
        "candidates": [{"content": {"parts": [{"text": (
            '{"fit_score": 70, "role_match": 15, "experience_match": 15, '
            '"technical_match": 20, "project_match": 8, "education_match": 8, '
            '"location_match": 4, "company_quality": 3, "decision": "good_match", '
            '"is_fresher_appropriate": true, "why": [], "gaps": []}'
        )}]}}]
    }

    with patch("ai.gemini_provider.requests.post", return_value=fake_response) as mock_post:
        GeminiProvider().evaluate("dummy prompt")

    sent_body = mock_post.call_args.kwargs["json"]
    assert sent_body["generationConfig"]["maxOutputTokens"] == config.GEMINI_MAX_OUTPUT_TOKENS
    assert mock_post.call_args.kwargs["timeout"] == config.GEMINI_TIMEOUT_SECONDS
