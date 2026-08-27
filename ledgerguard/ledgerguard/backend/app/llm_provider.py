"""
Provider-agnostic LLM interface.

Swap backends with one env var (LLM_PROVIDER=ollama|claude|gemini) without
touching any agent/orchestration code. Everything downstream calls
`llm.chat(...)` and `llm.embed(...)` -- it never knows which provider is
behind them.
"""
import os
import json
import time
import httpx
from dotenv import load_dotenv

load_dotenv()

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "ollama")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b-instruct")
OLLAMA_EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
# text-embedding-004 was shut down by Google on Jan 14, 2026.
# gemini-embedding-001 is the current replacement (defaults to 3072 dims;
# we pin it to 768 in embed() below to match the existing pgvector schema).
GEMINI_EMBED_MODEL = os.getenv("GEMINI_EMBED_MODEL", "gemini-embedding-001")


class LLMResponse:
    def __init__(self, text: str, tool_calls: list | None = None, raw: dict | None = None):
        self.text = text
        self.tool_calls = tool_calls or []
        self.raw = raw or {}


class BaseLLM:
    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> LLMResponse:
        raise NotImplementedError

    def embed(self, text: str) -> list[float]:
        raise NotImplementedError


class OllamaLLM(BaseLLM):
    """
    Uses Ollama's /api/chat endpoint. Ollama supports OpenAI-style tool
    definitions for models like qwen2.5 and llama3.1. We ask the model to
    respond in strict JSON when we need a tool call, since small local
    models are more reliable with an explicit JSON contract than with
    native function-calling alone.
    """

    def __init__(self, model: str = OLLAMA_MODEL, base_url: str = OLLAMA_BASE_URL):
        self.model = model
        self.base_url = base_url

    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> LLMResponse:
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": 0.1},
        }
        if tools:
            payload["tools"] = tools

        with httpx.Client(timeout=300.0) as client:
            resp = client.post(f"{self.base_url}/api/chat", json=payload)
            resp.raise_for_status()
            data = resp.json()

        message = data.get("message", {})
        text = message.get("content", "")
        tool_calls = message.get("tool_calls", []) or []

        # Normalize tool_calls into a consistent shape: {name, arguments}
        normalized = []
        for tc in tool_calls:
            fn = tc.get("function", {})
            args = fn.get("arguments", {})
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            normalized.append({"name": fn.get("name"), "arguments": args})

        return LLMResponse(text=text, tool_calls=normalized, raw=data)

    def embed(self, text: str) -> list[float]:
        with httpx.Client(timeout=60.0) as client:
            resp = client.post(
                f"{self.base_url}/api/embeddings",
                json={"model": OLLAMA_EMBED_MODEL, "prompt": text},
            )
            resp.raise_for_status()
            return resp.json()["embedding"]


class ClaudeLLM(BaseLLM):
    """Fallback provider -- same interface, used if Ollama is unavailable
    or tool-calling reliability is a problem during demo prep."""

    def __init__(self, model: str = "claude-sonnet-4-6"):
        self.model = model
        if not ANTHROPIC_API_KEY:
            raise RuntimeError("ANTHROPIC_API_KEY not set but LLM_PROVIDER=claude")

    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> LLMResponse:
        headers = {
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        payload = {
            "model": self.model,
            "max_tokens": 1024,
            "messages": messages,
        }
        if tools:
            payload["tools"] = tools

        with httpx.Client(timeout=120.0) as client:
            resp = client.post(
                "https://api.anthropic.com/v1/messages", headers=headers, json=payload
            )
            resp.raise_for_status()
            data = resp.json()

        text_parts = []
        tool_calls = []
        for block in data.get("content", []):
            if block["type"] == "text":
                text_parts.append(block["text"])
            elif block["type"] == "tool_use":
                tool_calls.append({"name": block["name"], "arguments": block["input"]})

        return LLMResponse(text="".join(text_parts), tool_calls=tool_calls, raw=data)

    def embed(self, text: str) -> list[float]:
        raise NotImplementedError(
            "Claude fallback doesn't do embeddings -- keep Ollama's "
            "nomic-embed-text for RAG even if chat falls back to Claude."
        )


class GeminiLLM(BaseLLM):
    """
    Uses Google's Generative Language API (generativelanguage.googleapis.com).
    Gemini's function-calling format differs from OpenAI/Ollama's, so we
    translate our OpenAI-style TOOL_SCHEMAS into Gemini's functionDeclarations
    format on the fly -- the agent/tools.py definitions don't need to change.

    Auth: Google is migrating from "Standard" API keys (AIzaSy...) to new
    "Auth" keys (AQ.Ab...). Auth keys must be sent via the x-goog-api-key
    HTTP header -- they are rejected if passed as a ?key= query param, which
    is why both chat() and embed() use headers here instead.

    Embeddings: text-embedding-004 was shut down by Google on Jan 14, 2026.
    gemini-embedding-001 is the current model; it defaults to 3072 output
    dimensions, so embed() explicitly requests 768 to match the pgvector
    column size defined in models.py (ContractChunk.embedding = Vector(768)).
    """

    def __init__(self, model: str = GEMINI_MODEL):
        self.model = model
        if not GEMINI_API_KEY:
            raise RuntimeError("GEMINI_API_KEY not set but LLM_PROVIDER=gemini")
        self.base_url = "https://generativelanguage.googleapis.com/v1beta"

    def _to_gemini_tools(self, tools: list[dict]) -> list[dict]:
        declarations = []
        for t in tools:
            fn = t.get("function", t)  # tolerate either OpenAI-wrapped or bare
            declarations.append({
                "name": fn["name"],
                "description": fn.get("description", ""),
                "parameters": fn.get("parameters", {"type": "object", "properties": {}}),
            })
        return [{"functionDeclarations": declarations}]

    def _to_gemini_contents(self, messages: list[dict]) -> tuple[str | None, list[dict]]:
        """Gemini takes system instructions separately from the turn history,
        and uses role 'model' instead of 'assistant'."""
        system_instruction = None
        contents = []
        for m in messages:
            role = m["role"]
            text = m["content"]
            if role == "system":
                system_instruction = text
                continue
            gemini_role = "model" if role == "assistant" else "user"
            contents.append({"role": gemini_role, "parts": [{"text": text}]})
        return system_instruction, contents

    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> LLMResponse:
        system_instruction, contents = self._to_gemini_contents(messages)

        payload = {"contents": contents}
        if system_instruction:
            payload["systemInstruction"] = {"parts": [{"text": system_instruction}]}
        if tools:
            payload["tools"] = self._to_gemini_tools(tools)

        url = f"{self.base_url}/models/{self.model}:generateContent"
        headers = {"x-goog-api-key": GEMINI_API_KEY, "Content-Type": "application/json"}

        with httpx.Client(timeout=60.0) as client:
            resp = client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()

        candidate = data.get("candidates", [{}])[0]
        parts = candidate.get("content", {}).get("parts", [])

        text_parts = []
        tool_calls = []
        for part in parts:
            if "text" in part:
                text_parts.append(part["text"])
            elif "functionCall" in part:
                fc = part["functionCall"]
                tool_calls.append({"name": fc.get("name"), "arguments": fc.get("args", {})})

        return LLMResponse(text="".join(text_parts), tool_calls=tool_calls, raw=data)

    def embed(self, text: str) -> list[float]:
        url = f"{self.base_url}/models/{GEMINI_EMBED_MODEL}:embedContent"
        headers = {"x-goog-api-key": GEMINI_API_KEY, "Content-Type": "application/json"}
        payload = {
            "model": f"models/{GEMINI_EMBED_MODEL}",
            "content": {"parts": [{"text": text}]},
            "outputDimensionality": 768,
        }
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
        return data["embedding"]["values"]


def get_llm() -> BaseLLM:
    if LLM_PROVIDER == "claude":
        return ClaudeLLM()
    if LLM_PROVIDER == "gemini":
        return GeminiLLM()
    return OllamaLLM()


def resilient_chat(messages: list[dict], tools: list[dict] | None = None, max_retries: int = 2) -> LLMResponse:
    """Wraps the configured provider's chat() with retry + automatic fallback.

    On transient errors (timeouts, rate limits, momentary API issues), retries
    the primary provider with exponential backoff. If the primary provider is
    still failing after retries and isn't already Ollama, falls back to local
    Ollama so the agent can still complete the investigation instead of the
    whole request failing outright.
    """
    primary = get_llm()
    last_err: Exception | None = None

    for attempt in range(max_retries):
        try:
            return primary.chat(messages, tools=tools)
        except Exception as e:
            last_err = e
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)  # 1s, then 2s

    if LLM_PROVIDER != "ollama":
        try:
            fallback = OllamaLLM()
            return fallback.chat(messages, tools=tools)
        except Exception as fallback_err:
            raise last_err or fallback_err

    raise last_err