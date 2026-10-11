"""Claude API 呼叫：structured output（JSON schema）＋ refusal fallback。"""

from __future__ import annotations

import json
import logging
import os

import anthropic

log = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-opus-5-5"


class GenerationError(RuntimeError):
    pass


class ClaudeLLM:
    def __init__(self, model: str | None = None, effort: str | None = None):
        self.client = anthropic.Anthropic()
        self.model = model or os.environ.get("CLAUDE_MODEL") or DEFAULT_MODEL
        self.effort = effort or os.environ.get("CLAUDE_EFFORT") or "medium"
        self.input_tokens = 0
        self.output_tokens = 0

    def json_call(self, system: str, user: str, schema: dict) -> dict:
        response = self.client.beta.messages.create(
            model=self.model,
            max_tokens=16000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            output_config={
                "effort": self.effort,
                "format": {"type": "json_schema", "schema": schema},
            },
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        self.input_tokens += response.usage.input_tokens
        self.output_tokens += response.usage.output_tokens

        if response.stop_reason == "refusal":
            raise GenerationError(f"model refused: {response.stop_details}")
        if response.stop_reason == "max_tokens":
            raise GenerationError("response truncated at max_tokens")

        text = next((b.text for b in response.content if b.type == "text"), None)
        if text is None:
            raise GenerationError(f"no text block (request id {response._request_id})")
        return json.loads(text)
