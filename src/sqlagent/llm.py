"""LLM backends. The agent only needs `complete(messages) -> str`.

- OpenAICompatible: Ollama, vLLM, LM Studio, OpenAI... (any /v1/chat/completions endpoint)
- Bedrock: AWS Bedrock Converse API (Claude, Llama, Mistral...)
- Scripted: replays fixed answers; used by the unit tests and CI, no network needed
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from typing import Protocol

import httpx

Message = dict[str, str]


class LLM(Protocol):
    name: str

    def complete(self, messages: list[Message]) -> str: ...


class OpenAICompatible:
    def __init__(self, model: str, base_url: str | None = None, api_key: str | None = None, timeout: float = 120):
        self.name = model
        self.base_url = (base_url or os.getenv("LLM_BASE_URL", "http://localhost:11434/v1")).rstrip("/")
        self.api_key = api_key or os.getenv("LLM_API_KEY", "ollama")
        self.client = httpx.Client(timeout=timeout)

    def complete(self, messages: list[Message]) -> str:
        r = self.client.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={"model": self.name, "messages": messages, "temperature": 0},
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]


class Bedrock:
    def __init__(self, model: str, region: str | None = None):
        import boto3  # optional dependency

        self.name = model
        self.client = boto3.client("bedrock-runtime", region_name=region or os.getenv("AWS_REGION", "eu-west-3"))

    def complete(self, messages: list[Message]) -> str:
        system = [{"text": m["content"]} for m in messages if m["role"] == "system"]
        convo = [{"role": m["role"], "content": [{"text": m["content"]}]} for m in messages if m["role"] != "system"]
        r = self.client.converse(modelId=self.name, system=system, messages=convo,
                                 inferenceConfig={"temperature": 0, "maxTokens": 800})
        return r["output"]["message"]["content"][0]["text"]


class Scripted:
    """Returns pre-written answers in order. Lets tests exercise the full agent loop deterministically."""

    def __init__(self, answers: Iterable[str]):
        self.name = "scripted"
        self.answers = list(answers)
        self.calls: list[list[Message]] = []

    def complete(self, messages: list[Message]) -> str:
        self.calls.append(messages)
        if not self.answers:
            raise RuntimeError("Scripted LLM ran out of answers")
        return self.answers.pop(0)


def from_env(spec: str) -> LLM:
    """'ollama:qwen2.5:7b', 'openai:gpt-4o-mini', 'bedrock:anthropic.claude-3-haiku-20240307-v1:0'"""
    kind, _, model = spec.partition(":")
    if kind == "ollama":
        return OpenAICompatible(model, base_url=os.getenv("LLM_BASE_URL", "http://localhost:11434/v1"))
    if kind == "openai":
        return OpenAICompatible(model, base_url="https://api.openai.com/v1", api_key=os.environ["OPENAI_API_KEY"])
    if kind == "bedrock":
        return Bedrock(model)
    raise ValueError(f"unknown backend {kind!r}")
