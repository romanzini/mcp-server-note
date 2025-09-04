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

try:
    from openai import AsyncOpenAI
except Exception:  # pragma: no cover
    AsyncOpenAI = None  # type: ignore

logger = logging.getLogger("mcp_notes.llm")

MAX_INPUT_CHARS = 4000
MAX_PROMPT_CHARS = 8000  # hard cap (antes de truncar)


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
    max_tool_passes: int = 2,
    retries: int = 2,
    _client: Any | None = None,  # para testes/mocks
) -> Tuple[str, List[Dict[str, Any]]]:
    """Conversa com LLM via OpenRouter, suportando chamadas de ferramenta e síntese final.

    Retorna: (texto_final, actions_executadas)
    actions_executadas: lista de {tool, args, result}
    """
    if not user_prompt or not user_prompt.strip():
        raise ValueError("Prompt vazio")
    if len(user_prompt) > MAX_PROMPT_CHARS:
        raise ValueError(f"Prompt excede limite de {MAX_PROMPT_CHARS} caracteres")

    model = model or os.getenv("OPENROUTER_MODEL", "openrouter/openai/gpt-4o-mini")
    client = _client or get_async_client()
    headers = default_headers()

    truncated = False
    user_content = user_prompt.strip()
    if len(user_content) > MAX_INPUT_CHARS:
        truncated = True
        user_content = user_content[:MAX_INPUT_CHARS]
    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]
    tools = tool_schemas()
    actions: List[Dict[str, Any]] = []
    if truncated:
        actions.append({
            "tool": "_system",
            "args": {},
            "result": {"truncated": True, "original_length": len(user_prompt), "used": len(user_content)}
        })

    async def _call_llm(msgs: List[Dict[str, Any]]):
        last_err: Optional[Exception] = None
        for attempt in range(retries + 1):
            try:
                logger.debug("llm_call attempt=%s", attempt)
                return await asyncio.wait_for(
                    client.chat.completions.create(
                        model=model,
                        messages=msgs,
                        tools=tools,  # type: ignore[arg-type]
                        tool_choice="auto",
                        temperature=temperature,
                        max_tokens=max_tokens,
                        extra_headers=headers or None,
                    ),
                    timeout=timeout,
                )
            except Exception as e:  # pragma: no cover
                last_err = e
                status = getattr(e, "status_code", None) or getattr(e, "http_status", None)
                if status in (401, 403):
                    logger.error("auth error calling LLM: %s", e)
                    break  # não adianta retry
                if status == 429:
                    logger.warning("rate limit (429) attempt=%s", attempt)
                # backoff simples
                await asyncio.sleep(min(2 ** attempt, 5))
        if last_err:
            status_code = getattr(last_err, "status_code", None) or getattr(last_err, "http_status", None)
            raw_text = str(last_err)
            lower = raw_text.lower()
            # Detecta página HTML de proxy corporativo (bloqueio) mascarando 403
            if status_code == 403 and ("<html" in lower or "<head" in lower or "bloqueio chat ia" in lower):
                meta = {
                    "error": "HTTP 403 – bloqueado pelo proxy corporativo",
                    "status": 403,
                    "proxy_blocked": True,
                }
                raise RuntimeError(json.dumps(meta, ensure_ascii=False))
            # Envelopa erro genérico
            meta = {
                "error": raw_text[:800],  # limita tamanho
                "type": last_err.__class__.__name__,
                "status": status_code,
            }
            raise RuntimeError(json.dumps(meta, ensure_ascii=False))
        raise RuntimeError("Falha desconhecida na chamada LLM")

    for pass_idx in range(max_tool_passes):
        resp = await _call_llm(messages)
        choice = resp.choices[0]
        msg = choice.message
        tool_calls = getattr(msg, "tool_calls", None)
        content_text = msg.content or ""

        if tool_calls:
            # Executar ferramentas solicitadas
            for tc in tool_calls:
                raw_args = tc.function.arguments
                args: Dict[str, Any]
                if isinstance(raw_args, str):
                    with suppress(Exception):
                        args = json.loads(raw_args)
                    if not isinstance(raw_args, dict):  # fallback
                        args = {} if not isinstance(raw_args, dict) else raw_args  # type: ignore
                else:
                    args = raw_args  # type: ignore
                actions.append({"tool": tc.function.name, "args": args})
                # Adiciona mensagem de ferramenta placeholder; resultado real será anexado externamente
                messages.append(
                    {
                        "role": "assistant",
                        "content": content_text,
                        "tool_calls": [],  # normaliza
                    }
                )
                # O chamador (server) irá realmente executar; aqui não chamamos Supabase diretamente
            # Após tool calls, pediremos síntese final na próxima iteração
            continue
        else:
            # Síntese final encontrada
            return content_text, actions

    # Se saiu do loop sem síntese final, retorna última parcial
    return (messages[-1].get("content") or "", actions)
