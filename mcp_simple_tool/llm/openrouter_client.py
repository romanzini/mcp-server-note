from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
import os
import asyncio
import logging
import json
from contextlib import suppress
from dotenv import load_dotenv

# Carrega variáveis de ambiente
load_dotenv()

try:  # pragma: no cover - apenas caminho de import
    from openai import AsyncOpenAI
except Exception:  # pragma: no cover
    AsyncOpenAI = None  # type: ignore

logger = logging.getLogger("mcp_notes.llm")

MAX_INPUT_CHARS = 4000
MAX_PROMPT_CHARS = 8000


def get_async_client() -> Any:
    api_key = os.getenv("OPENROUTER_API_KEY")
    base_url = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is not set")
    if AsyncOpenAI is None:
        raise RuntimeError("openai package not installed; run `pip install openai`.")
    return AsyncOpenAI(api_key=api_key, base_url=base_url)


def default_headers() -> Dict[str, str]:
    headers: Dict[str, str] = {}
    referer = os.getenv("OPENROUTER_REFERER")
    title = os.getenv("OPENROUTER_TITLE")
    if referer:
        headers["HTTP-Referer"] = referer
    if title:
        headers["X-Title"] = title
    return headers


def tool_schemas() -> List[Dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": "add_note",
                "description": "Cria uma nota com título, conteúdo e tags.",
                "parameters": {
                    "type": "object",
                    "required": ["content", "title"],
                    "properties": {
                        "content": {"type": "string"},
                        "title": {"type": "string"},
                        "tags": {"type": "array", "items": {"type": "string"}},
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "search_notes",
                "description": "Busca notas por conteúdo, título e/ou tags.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "title": {"type": "string"},
                        "tags": {"type": "array", "items": {"type": "string"}},
                    },
                },
            },
        },
    ]


SYSTEM_PROMPT = (
    "Você é um assistente de notas. Use ferramentas para criar e buscar notas. "
    "Responda em português, de forma curta e clara. Quando buscar notas, apresente um resumo e itens relevantes."
)


async def chat_with_tools(
    user_prompt: str,
    model: Optional[str] = None,
    temperature: float = 0.2,
    max_tokens: int = 400,
    timeout: float = 60.0,
    max_tool_passes: int = 3,
    _client: Any | None = None,
) -> Tuple[str, List[Dict[str, Any]]]:
    """Conversa com LLM permitindo passes de planejamento de ferramentas.

    Retorna (texto_final, ações_planejadas). Cada ação: {tool, args}.
    Em erros de rede/proxy levanta RuntimeError cujo message é JSON com metadados.
    """

    if not user_prompt or not str(user_prompt).strip():
        raise ValueError("prompt vazio")

    model = model or os.getenv("OPENROUTER_MODEL", "openrouter/auto")
    client = _client or get_async_client()

    actions: List[Dict[str, Any]] = []
    user_content = user_prompt
    if len(user_content) > MAX_INPUT_CHARS:
        actions.append(
            {
                "tool": "_system",
                "result": {
                    "truncated": True,
                    "original_chars": len(user_content),
                    "used_chars": MAX_INPUT_CHARS,
                },
            }
        )
        user_content = user_content[:MAX_INPUT_CHARS]

    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT[:MAX_PROMPT_CHARS]},
        {"role": "user", "content": user_content},
    ]

    async def _call_llm(msgs: List[Dict[str, Any]]):
        headers = default_headers()
        last_err: Optional[Exception] = None
        for attempt in range(3):
            try:
                return await client.chat.completions.create(
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    messages=msgs,
                    tools=tool_schemas(),
                    tool_choice="auto",
                    timeout=timeout,
                    extra_headers=headers or None,
                )
            except Exception as e:  # pragma: no cover - ambiente real
                last_err = e
                status = getattr(e, "status_code", None) or getattr(e, "http_status", None)
                if status and status < 500 and status != 429:
                    break  # não adianta retry
                if status == 429:
                    logger.warning("rate limit (429) attempt=%s", attempt)
                await asyncio.sleep(min(2 ** attempt, 5))
        if last_err:
            status_code = getattr(last_err, "status_code", None) or getattr(last_err, "http_status", None)
            raw_text = str(last_err)
            lower = raw_text.lower()
            if status_code == 403 and ("<html" in lower or "<head" in lower or "bloqueio chat ia" in lower):
                meta = {"error": "HTTP 403 – bloqueado pelo proxy corporativo", "status": 403, "proxy_blocked": True}
                raise RuntimeError(json.dumps(meta, ensure_ascii=False))
            cls_name = last_err.__class__.__name__
            if cls_name in ("APIConnectionError", "TimeoutError") or "connection error" in lower:
                meta = {
                    "error": "Falha de conexão com OpenRouter (verifique rede / proxy).",
                    "type": cls_name,
                    "status": status_code,
                    "code": "network_error",
                    "retryable": True,
                }
                raise RuntimeError(json.dumps(meta, ensure_ascii=False))
            meta = {"error": raw_text[:800], "type": cls_name, "status": status_code}
            raise RuntimeError(json.dumps(meta, ensure_ascii=False))
        raise RuntimeError("unexpected: LLM returned neither result nor exception")  # pragma: no cover

    for _ in range(max_tool_passes):
        resp = await _call_llm(messages)
        choice = resp.choices[0]
        msg = choice.message
        tool_calls = getattr(msg, "tool_calls", None)
        content_text = msg.content or ""
        if tool_calls:
            for tc in tool_calls:
                raw_args = tc.function.arguments
                args: Dict[str, Any]
                if isinstance(raw_args, str):
                    parsed: Any = raw_args
                    with suppress(Exception):
                        parsed = json.loads(raw_args)
                    args = parsed if isinstance(parsed, dict) else {}
                else:
                    args = raw_args  # type: ignore
                actions.append({"tool": tc.function.name, "args": args})
            # Adiciona mensagem representando o planejamento (sem executar)
            messages.append({"role": "assistant", "content": content_text})
            continue
        return content_text, actions

    # Excedeu passes sem síntese; devolve última mensagem do usuário (fallback)
    return (messages[-1].get("content") or "", actions)
