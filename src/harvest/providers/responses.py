from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from harvest.config import AppConfig, get_api_key
from harvest.models import NetworkTrace, Usage
from harvest.text_safety import sanitize_untrusted_text


T = TypeVar("T", bound=BaseModel)


class ProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class StructuredResult:
    value: BaseModel
    usage: Usage


class ResponsesProvider:
    def __init__(
        self,
        *,
        provider: str,
        model: str,
        api_key: str,
        client: httpx.Client | None = None,
        retry_delays: tuple[float, ...] = (0.25, 0.75),
    ):
        if provider not in {"deepseek", "openai"}:
            raise ProviderError("不支持的模型服务商")
        cleaned_api_key = api_key.strip()
        if not cleaned_api_key or any(
            character.isspace() or not character.isprintable() for character in cleaned_api_key
        ):
            raise ProviderError("API Key 格式无效：不能包含空白或控制字符")
        self.provider = provider
        self.model = model
        self.api_key = cleaned_api_key
        self.endpoint = (
            "https://api.deepseek.com/responses"
            if provider == "deepseek"
            else "https://api.openai.com/v1/responses"
        )
        self.client = client or httpx.Client(timeout=httpx.Timeout(90.0, connect=15.0))
        self.retry_delays = retry_delays

    def generate(self, *, instructions: str, input_text: str, output_type: type[T], schema_name: str) -> tuple[T, Usage]:
        value, usage, _ = self._generate(
            instructions=instructions,
            input_text=input_text,
            output_type=output_type,
            schema_name=schema_name,
        )
        return value, usage

    def generate_traced(
        self, *, instructions: str, input_text: str, output_type: type[T], schema_name: str
    ) -> tuple[T, Usage, NetworkTrace]:
        return self._generate(
            instructions=instructions,
            input_text=input_text,
            output_type=output_type,
            schema_name=schema_name,
        )

    def _generate(
        self, *, instructions: str, input_text: str, output_type: type[T], schema_name: str
    ) -> tuple[T, Usage, NetworkTrace]:
        schema = output_type.model_json_schema()
        format_config = {
            "type": "json_schema",
            "name": schema_name,
            "schema": schema,
        }
        if self.provider == "openai":
            format_config["strict"] = True
        payload = {
            "model": self.model,
            "input": [
                {"role": "system", "content": instructions},
                {"role": "user", "content": input_text},
            ],
            "text": {"format": format_config},
            "max_output_tokens": 4000,
            "store": False,
        }
        if self.provider == "deepseek":
            # Daily/weekly synthesis is constrained extraction. DeepSeek V4
            # enables thinking by default, and reasoning consumes the same
            # max_output_tokens budget as the required JSON response.
            payload["reasoning"] = {"effort": "none"}
        last_error: Exception | None = None
        started = time.monotonic()
        for attempt in range(len(self.retry_delays) + 1):
            try:
                response = self.client.post(
                    self.endpoint,
                    headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                    json=payload,
                )
                if response.status_code in {408, 409, 429} or response.status_code >= 500:
                    raise ProviderError(f"模型服务暂时不可用（HTTP {response.status_code}）")
                if response.is_error:
                    detail = _safe_error_detail(response, api_key=self.api_key)
                    raise ProviderError(f"模型请求失败（HTTP {response.status_code}）：{detail}")
                body = response.json()
                if not isinstance(body, dict):
                    raise ProviderError("模型返回的响应不是 JSON 对象")
                output_text = _extract_output_text(body, api_key=self.api_key)
                value = _validate_structured_output(output_text, output_type)
                usage_raw = body.get("usage") or {}
                usage = Usage(
                    input_tokens=usage_raw.get("input_tokens"),
                    output_tokens=usage_raw.get("output_tokens"),
                    total_tokens=usage_raw.get("total_tokens"),
                )
                trace = NetworkTrace(
                    endpoint=self.endpoint,
                    provider=self.provider,
                    model=self.model,
                    schema_name=schema_name,
                    status_code=response.status_code,
                    elapsed_ms=round((time.monotonic() - started) * 1000),
                    request_payload=payload,
                    response_payload=body,
                    usage=usage,
                )
                return value, usage, trace
            except (httpx.TimeoutException, httpx.NetworkError, json.JSONDecodeError, ValidationError, ProviderError) as exc:
                last_error = exc
                retryable = isinstance(exc, (httpx.TimeoutException, httpx.NetworkError, json.JSONDecodeError, ValidationError))
                if isinstance(exc, ProviderError) and any(
                    marker in str(exc) for marker in ("暂时不可用",)
                ):
                    retryable = True
                if not retryable or attempt >= len(self.retry_delays):
                    break
                time.sleep(self.retry_delays[attempt])
        if isinstance(last_error, ProviderError):
            raise last_error
        if isinstance(last_error, (json.JSONDecodeError, ValidationError)):
            raise ProviderError("无法获得有效的结构化结果：响应格式不符合约定") from last_error
        if isinstance(last_error, httpx.HTTPError):
            raise ProviderError("模型网络请求失败；请检查网络后重试") from last_error
        raise ProviderError("无法获得有效的结构化结果") from last_error


def build_provider(config: AppConfig, *, client: httpx.Client | None = None) -> ResponsesProvider:
    api_key = get_api_key(config)
    if not api_key:
        raise ProviderError(f"缺少 {config.api_key_name}；请直接运行 harvest 或使用 harvest auth")
    return ResponsesProvider(
        provider=config.provider,
        model=config.model,
        api_key=api_key,
        client=client,
    )


def _extract_output_text(body: dict, *, api_key: str | None = None) -> str:
    direct = body.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct
    chunks: list[str] = []
    for item in body.get("output") or []:
        if item.get("type") != "message":
            continue
        for content in item.get("content") or []:
            if content.get("type") in {"output_text", "text"} and isinstance(content.get("text"), str):
                chunks.append(content["text"])
    if not chunks:
        error = body.get("error")
        if error:
            detail = _redact_sensitive_text(sanitize_untrusted_text(str(error)), api_key=api_key)[:300]
            raise ProviderError(f"模型没有返回文本结果：{detail}")
        status = body.get("status")
        incomplete = body.get("incomplete_details") or {}
        reason = incomplete.get("reason") if isinstance(incomplete, dict) else None
        context = ", ".join(
            item for item in (f"status={status}" if status else None, f"reason={reason}" if reason else None) if item
        )
        raise ProviderError(f"模型没有返回文本结果{f'（{context}）' if context else ''}")
    return "".join(chunks)


def _validate_structured_output(output_text: str, output_type: type[T]) -> T:
    text = output_text.strip()
    try:
        return output_type.model_validate_json(text)
    except ValidationError as first_error:
        # Some OpenAI-compatible providers wrap JSON-schema output in a
        # Markdown code fence despite being asked for structured output.
        fenced = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        fenced = re.sub(r"\s*```$", "", fenced).strip()
        if fenced != text:
            try:
                return output_type.model_validate_json(fenced)
            except ValidationError:
                pass
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            return output_type.model_validate_json(text[start : end + 1])
        raise first_error


def _redact_sensitive_text(text: str, *, api_key: str | None = None) -> str:
    if api_key:
        text = text.replace(api_key, "[REDACTED]")
    text = re.sub(
        r"(?i)(api[ _-]?key(?:\s+is)?\s*[:=]\s*)[^\s,;]+",
        r"\1[REDACTED]",
        text,
    )
    return re.sub(r"(?i)(bearer\s+)[^\s,;]+", r"\1[REDACTED]", text)


def _safe_error_detail(response: httpx.Response, *, api_key: str | None = None) -> str:
    try:
        body = response.json()
        error = body.get("error", body)
        if isinstance(error, dict):
            detail = str(error.get("message") or error.get("code") or "未知错误")
        else:
            detail = str(error)
    except (ValueError, json.JSONDecodeError):
        detail = response.text or "未知错误"
    return sanitize_untrusted_text(_redact_sensitive_text(detail, api_key=api_key))[:300]
