"""Small text-only adapter for Anthropic and compatible Chat APIs.

All agent response paths use the same messages.create interface. No provider
fallback is performed: each agent always calls its configured model.
"""
from dataclasses import dataclass
from typing import Callable, Optional

import requests
from anthropic import Anthropic, APIError


BASE_URLS = {
    "nvidia": "https://integrate.api.nvidia.com/v1",
    "dashscope": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "groq": "https://api.groq.com/openai/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
    "zhipu": "https://open.bigmodel.cn/api/paas/v4",
}
SUPPORTED_PROVIDERS = {"anthropic", *BASE_URLS}
RESERVED_BODY_FIELDS = {"model", "messages", "stream", "max_tokens", "max_completion_tokens"}


class LLMError(RuntimeError):
    """Safe-to-log error, without credentials or the remote response body."""

    def __init__(self, message: str, retryable: bool = False,
                 status_code: Optional[int] = None):
        super().__init__(message)
        self.retryable = retryable
        self.status_code = status_code


@dataclass
class TextBlock:
    text: str


@dataclass
class TextResponse:
    content: list[TextBlock]


class LLMClient:
    def __init__(self, api_key: str, provider: str = "anthropic",
                 base_url: Optional[str] = None, timeout: float = 180,
                 extra_body: Optional[dict] = None,
                 on_usage: Optional[Callable[[int, int], None]] = None):
        if provider not in SUPPORTED_PROVIDERS:
            raise ValueError(f"Unsupported provider: {provider}")
        self.provider = provider
        self._api_key = api_key
        self.base_url = (base_url or BASE_URLS.get(provider, "")).rstrip("/")
        self.timeout = timeout
        self.extra_body = dict(extra_body or {})
        if RESERVED_BODY_FIELDS.intersection(self.extra_body):
            raise ValueError("extra_body cannot override model, messages, stream or token limits")
        self.on_usage = on_usage
        self.messages = self
        self._anthropic = None
        if provider == "anthropic":
            kwargs = {"api_key": api_key, "timeout": timeout, "max_retries": 0}
            if base_url:
                kwargs["base_url"] = base_url
            self._anthropic = Anthropic(**kwargs)

    def _http_error(self, model: str, status: int) -> LLMError:
        hints = {
            400: "Check model parameters and conversation format.",
            401: "Check this agent's API key.",
            402: "Check this provider's credits or billing.",
            403: "Check key permissions, model access and API region.",
            404: "Check model ID and base_url for this provider.",
            429: "rate_limit: check provider quota; try again later.",
        }
        return LLMError(
            f"{self.provider}/{model}: HTTP {status}. "
            + hints.get(status, "Provider request failed; check provider status."),
            retryable=status in (408, 429) or status >= 500,
            status_code=status,
        )

    def _record_usage(self, input_tokens, output_tokens):
        if (self.on_usage and isinstance(input_tokens, int)
                and isinstance(output_tokens, int)):
            self.on_usage(input_tokens, output_tokens)

    def create(self, *, model: str, system: str, messages: list,
               max_tokens: int = 4000) -> TextResponse:
        # Use fresh dictionaries: never mutate the shared conversation history.
        turns = [{"role": m["role"], "content": m["content"]} for m in messages]
        if turns and turns[-1]["role"] == "assistant":
            turns.append({"role": "user", "content": "Please continue the discussion."})

        if self.provider == "anthropic":
            try:
                response = self._anthropic.messages.create(
                    model=model, system=system, messages=turns,
                    max_tokens=max_tokens, **self.extra_body,
                )
            except APIError as exc:
                status = getattr(exc, "status_code", None)
                if status:
                    raise self._http_error(model, status) from None
                raise LLMError(f"anthropic/{model}: connection or timeout error.", True) from None
            self._record_usage(response.usage.input_tokens, response.usage.output_tokens)
            text = "\n".join(block.text for block in response.content
                             if getattr(block, "type", None) == "text")
            finish_reason = response.stop_reason
        else:
            token_limit_field = "max_completion_tokens" if self.provider == "groq" else "max_tokens"
            payload = {
                **self.extra_body,
                "model": model,
                "messages": [{"role": "system", "content": system}, *turns],
                token_limit_field: max_tokens,
                "stream": False,
            }
            try:
                response = requests.post(
                    f"{self.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self._api_key}",
                             "Content-Type": "application/json", "Accept": "application/json"},
                    json=payload, timeout=(15, self.timeout), allow_redirects=False,
                )
            except requests.RequestException:
                raise LLMError(f"{self.provider}/{model}: connection or timeout error.", True) from None
            try:
                if response.status_code != 200:
                    raise self._http_error(model, response.status_code)
                data = response.json()
                choice = data["choices"][0]
                # Do not publish reasoning_content as an agent's final answer.
                text = choice["message"].get("content")
                if isinstance(text, list):
                    text = "\n".join(p["text"] for p in text
                                     if p.get("type") == "text" and isinstance(p.get("text"), str))
                finish_reason = choice.get("finish_reason")
                usage = data.get("usage") or {}
                self._record_usage(usage.get("prompt_tokens"), usage.get("completion_tokens"))
            except (ValueError, KeyError, IndexError, TypeError, AttributeError):
                raise LLMError(f"{self.provider}/{model}: invalid Chat Completions response.") from None
            finally:
                response.close()

        if not isinstance(text, str) or not text.strip():
            raise LLMError(
                f"{self.provider}/{model}: no final text returned. "
                "Check max_tokens / thinking settings; reasoning-only output is not an answer."
            )
        if finish_reason in ("length", "max_tokens"):
            print(f"Warning: {model} reached max_tokens; this response may be incomplete.")
        return TextResponse(content=[TextBlock(text=text)])
