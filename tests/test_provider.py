import json

import httpx
import pytest

from harvest.models import DailyAnalysis, DailyHarvest
from harvest.providers.responses import ProviderError, ResponsesProvider
from tests.test_models_render import sample_harvest


def _response_payload() -> dict:
    return {
        "id": "resp_test",
        "status": "completed",
        "output": [
            {
                "type": "message",
                "content": [
                    {"type": "output_text", "text": sample_harvest().model_dump_json()},
                ],
            }
        ],
        "usage": {"input_tokens": 123, "output_tokens": 45, "total_tokens": 168},
    }


@pytest.mark.parametrize(
    ("provider_name", "expected_url", "expects_strict"),
    [
        ("deepseek", "https://api.deepseek.com/responses", False),
        ("openai", "https://api.openai.com/v1/responses", True),
    ],
)
def test_provider_builds_responses_api_payload(provider_name, expected_url, expects_strict) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == expected_url
        assert request.headers["authorization"] == "Bearer secret"
        payload = json.loads(request.content)
        assert payload["store"] is False
        assert payload["text"]["format"]["type"] == "json_schema"
        assert ("strict" in payload["text"]["format"]) is expects_strict
        if provider_name == "deepseek":
            assert payload["reasoning"] == {"effort": "none"}
        else:
            assert "reasoning" not in payload
        return httpx.Response(200, json=_response_payload())

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = ResponsesProvider(
        provider=provider_name,
        model="test-model",
        api_key="secret",
        client=client,
        retry_delays=(),
    )
    result, usage = provider.generate(
        instructions="system",
        input_text="input",
        output_type=DailyHarvest,
        schema_name="daily",
    )
    assert result.section("algorithms").progress[0] == "理解净票数含义"
    assert usage.total_tokens == 168


def test_provider_rejects_empty_output() -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"output": [], "usage": {}}))
    )
    provider = ResponsesProvider(
        provider="deepseek",
        model="test-model",
        api_key="secret",
        client=client,
        retry_delays=(),
    )
    with pytest.raises(ProviderError, match="没有返回文本"):
        provider.generate(
            instructions="system",
            input_text="input",
            output_type=DailyHarvest,
            schema_name="daily",
        )


def test_provider_reports_incomplete_reason_without_retrying() -> None:
    requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(
            200,
            json={
                "status": "incomplete",
                "incomplete_details": {"reason": "max_output_tokens"},
                "output": [{"type": "reasoning", "content": []}],
                "usage": {},
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = ResponsesProvider(
        provider="deepseek",
        model="test-model",
        api_key="secret",
        client=client,
        retry_delays=(0, 0),
    )
    with pytest.raises(ProviderError, match="status=incomplete, reason=max_output_tokens"):
        provider.generate(
            instructions="system",
            input_text="input",
            output_type=DailyHarvest,
            schema_name="daily",
        )
    assert requests == 1


def test_provider_rejects_schema_invalid_json() -> None:
    body = {
        "output": [{"type": "message", "content": [{"type": "output_text", "text": '{"deep": []}'}]}],
        "usage": {},
    }
    client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=body)))
    provider = ResponsesProvider(
        provider="openai",
        model="test-model",
        api_key="secret",
        client=client,
        retry_delays=(),
    )
    with pytest.raises(ProviderError, match="无法获得有效的结构化结果"):
        provider.generate(
            instructions="system",
            input_text="input",
            output_type=DailyHarvest,
            schema_name="daily",
        )


def test_provider_accepts_json_wrapped_in_markdown_fence() -> None:
    analysis = DailyAnalysis(report=sample_harvest(), project_suggestions=[])
    body = {
        "output": [
            {
                "type": "message",
                "content": [
                    {"type": "output_text", "text": f"```json\n{analysis.model_dump_json()}\n```"}
                ],
            }
        ],
        "usage": {},
    }
    client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=body)))
    provider = ResponsesProvider(
        provider="deepseek",
        model="test-model",
        api_key="secret",
        client=client,
        retry_delays=(),
    )

    result, _ = provider.generate(
        instructions="system",
        input_text="input",
        output_type=DailyAnalysis,
        schema_name="daily",
    )

    assert result.report.overview == analysis.report.overview


@pytest.mark.parametrize(
    "body",
    [
        {"error": {"message": "Authentication Fails, Your api key: secret is invalid"}},
        {"error": "Authorization failed for Bearer secret"},
    ],
)
def test_provider_redacts_api_key_from_error(body) -> None:
    client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(401, json=body)))
    provider = ResponsesProvider(
        provider="deepseek",
        model="test-model",
        api_key="secret",
        client=client,
        retry_delays=(),
    )

    with pytest.raises(ProviderError) as caught:
        provider.generate(
            instructions="system",
            input_text="input",
            output_type=DailyHarvest,
            schema_name="daily",
        )

    assert "secret" not in str(caught.value)
    assert "[REDACTED]" in str(caught.value)
