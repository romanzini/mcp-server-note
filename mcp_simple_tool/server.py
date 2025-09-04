from __future__ import annotations

from typing import Any, List
import os
import json
import logging
import ssl
import anyio
import httpx
import click

import mcp.types as types
from mcp.server.lowlevel import Server

# Opcional: usar repositório de certificados do Windows
try:
    import truststore  # type: ignore
    truststore.inject_into_ssl()
except Exception:
    pass

# Funções utilitárias (Supabase)
from mcp_simple_tool.tools.notes import add_note_tool, search_notes_tool
from mcp_simple_tool.llm.openrouter_client import chat_with_tools

logger = logging.getLogger("mcp_notes.server")
if not logger.handlers:
    logging.basicConfig(level=os.getenv("MCP_LOG_LEVEL") or os.getenv("LOG_LEVEL") or "INFO")


def _env_flag(name: str) -> bool:
    return os.getenv(name, "").lower() in ("1", "true", "yes", "on")


def notes_chat_enabled() -> bool:
    # Requer ENABLE_NOTES_CHAT e API key presente
    return _env_flag("ENABLE_NOTES_CHAT") and bool(os.getenv("OPENROUTER_API_KEY"))


async def fetch_website(url: str) -> List[types.ContentBlock]:
    headers = {"User-Agent": "MCP Test Server (github.com/modelcontextprotocol/python-sdk)"}
    insecure = os.getenv("MCP_INSECURE_SKIP_VERIFY", "").lower() in ("1", "true", "yes")
    verify: bool | ssl.SSLContext = False if insecure else True

    async with httpx.AsyncClient(headers=headers, verify=verify, follow_redirects=True, timeout=30) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return [types.TextContent(type="text", text=resp.text)]


@click.command()
@click.option("--port", default=8000, help="Port to listen on for SSE")
@click.option("--transport", type=click.Choice(["stdio", "sse"]), default="stdio", help="Transport type")
def main(port: int, transport: str) -> int:
    app = Server("mcp-note-server")

    # Handler único de ferramentas
    @app.call_tool()
    async def handle_tools(name: str, arguments: dict[str, Any]) -> List[types.ContentBlock]:
        if name == "notes_chat":
            if not notes_chat_enabled():
                return [types.TextContent(type="text", text=json.dumps({"success": False, "error": "notes_chat desabilitado (defina ENABLE_NOTES_CHAT=1 e OPENROUTER_API_KEY)"}))]
            try:
                prompt = (arguments or {}).get("prompt")
                model = (arguments or {}).get("model")
                params = (arguments or {}).get("params") or {}
                temperature = float(params.get("temperature", 0.2))
                max_tokens = int(params.get("max_tokens", 400))
                timeout_seconds = float(params.get("timeout_seconds", 60))

                if not prompt or not str(prompt).strip():
                    raise ValueError("prompt vazio")

                # 1ª passada: planejar + possivelmente solicitar ferramentas
                draft_text, planned_actions = await chat_with_tools(
                    prompt,
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    timeout=timeout_seconds,
                )
                logger.debug("notes_chat draft_text=%s planned_actions=%s", draft_text[:120], planned_actions)

                executed: list[dict[str, Any]] = []
                # Executar ações planejadas
                for act in planned_actions:
                    tool = act.get("tool")
                    args = act.get("args") or {}
                    if tool == "add_note":
                        res = add_note_tool(args.get("content"), args.get("title"), args.get("tags") or [])
                    elif tool == "search_notes":
                        res = search_notes_tool(args.get("query"), args.get("title"), args.get("tags") or [])
                        # Limita resultados para reduzir tokens (top 10)
                        try:
                            if res.get("success") and isinstance(res.get("data"), dict):
                                results = res["data"].get("results")
                                if isinstance(results, list) and len(results) > 10:
                                    res["data"]["results"] = results[:10]
                                    res["data"]["truncated_results"] = True
                        except Exception:  # pragma: no cover
                            pass
                    else:
                        res = {"success": False, "error": "tool not supported"}
                    executed.append({"tool": tool, "args": args, "result": res})

                final_text = draft_text
                synthesized = False
                if executed:
                    # 2ª passada: síntese final considerando resultados
                    # Monta contexto compacto
                    ctx_parts = []
                    for ex in executed:
                        res = ex["result"]
                        res_str = json.dumps(res, ensure_ascii=False)[:800]
                        ctx_parts.append(f"Ferramenta={ex['tool']}: args={json.dumps(ex['args'], ensure_ascii=False)} resultado={res_str}")
                    tool_context = "\n".join(ctx_parts)
                    synth_prompt = (
                        f"O usuário pediu: {prompt}\n\n"
                        f"Resultados das ferramentas executadas:\n{tool_context}\n\n"
                        "Produza uma resposta final concisa em português para o usuário, incorporando os dados relevantes."
                    )
                    final_text, _ = await chat_with_tools(
                        synth_prompt,
                        model=model,
                        temperature=0.2,  # menor variação na síntese
                        max_tokens=max_tokens,
                        timeout=timeout_seconds,
                        max_tool_passes=1,  # não precisamos de novas ferramentas
                    )
                    synthesized = True

                payload = {
                    "success": True,
                    "text": final_text,
                    "actions": executed,
                    "synthesized": synthesized,
                }
                return [types.TextContent(type="text", text=json.dumps(payload, ensure_ascii=False))]
            except Exception as e:  # pragma: no cover
                logger.exception("notes_chat error")
                return [types.TextContent(type="text", text=json.dumps({"success": False, "error": str(e)}))]
        if name == "fetch":
            url = arguments.get("url")
            if not url:
                raise ValueError("Missing required argument 'url'")
            return await fetch_website(url)

        if name == "add_note":
            content = arguments.get("content")
            title = arguments.get("title")
            tags = arguments.get("tags", [])
            if content is None or title is None:
                raise ValueError("Missing required 'content' or 'title'")
            result = add_note_tool(content, title, tags)
            return [types.TextContent(type="text", text=str(result))]

        if name == "search_notes":
            query = arguments.get("query")
            title = arguments.get("title")
            tags = arguments.get("tags", [])
            result = search_notes_tool(query, title, tags)
            return [types.TextContent(type="text", text=str(result))]

        raise ValueError(f"Unknown tool: {name}")

    # Lista de ferramentas
    @app.list_tools()
    async def list_tools() -> List[types.Tool]:
        tools: List[types.Tool] = []
        if notes_chat_enabled():
            tools.append(
                types.Tool(
                    name="notes_chat",
                    title="Notes Chat",
                    description="Interaja em linguagem natural para criar e buscar notas (usa LLM OpenRouter).",
                    inputSchema={
                        "type": "object",
                        "required": ["prompt"],
                        "properties": {
                            "prompt": {"type": "string", "description": "Instrução do usuário"},
                            "model": {"type": "string", "description": "ID do modelo no OpenRouter"},
                            "params": {
                                "type": "object",
                                "properties": {
                                    "temperature": {"type": "number"},
                                    "max_tokens": {"type": "integer"},
                                    "timeout_seconds": {"type": "number", "description": "Timeout por chamada (default 60)"},
                                },
                            },
                        },
                    },
                )
            )
        # Sempre disponíveis
        tools.extend(
            [
                types.Tool(
                    name="fetch",
                    title="Website Fetcher",
                    description="Fetches a website and returns its content",
                    inputSchema={
                        "type": "object",
                        "required": ["url"],
                        "properties": {"url": {"type": "string", "description": "URL to fetch"}},
                    },
                ),
                types.Tool(
                    name="add_note",
                    title="Add Note",
                    description="Adiciona uma nova nota no Supabase",
                    inputSchema={
                        "type": "object",
                        "required": ["content", "title"],
                        "properties": {
                            "content": {"type": "string", "description": "Conteúdo da nota"},
                            "title": {"type": "string", "description": "Título da nota"},
                            "tags": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Lista de tags associadas à nota",
                            },
                        },
                    },
                ),
                types.Tool(
                    name="search_notes",
                    title="Search Notes",
                    description="Busca notas no Supabase",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "Texto a ser buscado"},
                            "title": {"type": "string", "description": "Título a ser buscado"},
                            "tags": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Lista de tags para filtrar notas",
                            },
                        },
                    },
                ),
            ]
        )
        return tools

    if transport == "sse":
        # Modo SSE opcional (requer starlette e uvicorn)
        from mcp.server.sse import SseServerTransport
        from starlette.applications import Starlette
        from starlette.requests import Request
        from starlette.responses import Response
        from starlette.routing import Mount, Route
        import uvicorn

        sse = SseServerTransport("/messages/")

        async def handle_sse(request: Request):
            async with sse.connect_sse(request.scope, request.receive, request._send) as streams:
                await app.run(streams[0], streams[1], app.create_initialization_options())
            return Response()

        starlette_app = Starlette(
            debug=True,
            routes=[Route("/sse", endpoint=handle_sse, methods=["GET"]), Mount("/messages/", app=sse.handle_post_message)],
        )
        uvicorn.run(starlette_app, host="127.0.0.1", port=port)
    else:
        from mcp.server.stdio import stdio_server

        async def arun():
            async with stdio_server() as (read, write):
                await app.run(read, write, app.create_initialization_options())

        anyio.run(arun)

    return 0


if __name__ == "__main__":
    main()