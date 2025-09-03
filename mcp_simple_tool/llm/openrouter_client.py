from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
import os
import asyncio
import logging

try:
    from openai import AsyncOpenAI
except Exception:  # pragma: no cover
    AsyncOpenAI = None  # type: ignore

logger = logging.getLogger("mcp_notes.llm")


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
) -> Tuple[str, List[Dict[str, Any]]]:
    """Conversa com LLM via OpenRouter, permitindo chamadas de ferramenta.

    Retorna: (texto_final, actions_executadas)
    actions_executadas: lista de {tool, args, result}
    """
    model = model or os.getenv("OPENROUTER_MODEL", "openrouter/openai/gpt-4o-mini")
    client = get_async_client()
    headers = default_headers()

    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]
    tools = tool_schemas()
    actions: List[Dict[str, Any]] = []

    # Uma iteração de tool-call + resposta final costuma bastar
    resp = await client.chat.completions.create(
        model=model,
        messages=messages,
        tools=tools,  # type: ignore[arg-type]
        tool_choice="auto",
        temperature=temperature,
        max_tokens=max_tokens,
        extra_headers=headers or None,
    )

    choice = resp.choices[0]
    msg = choice.message
    tool_calls = getattr(msg, "tool_calls", None)
    final_text = msg.content or ""

    if tool_calls:
        # Retorna instrução para o chamador executar ferramentas; a síntese final será feita depois
        return final_text, [
            {
                "id": tc.id,
                "tool": tc.function.name,
                "args": tc.function.arguments,
            }
            for tc in tool_calls
        ]

    return final_text, actions
