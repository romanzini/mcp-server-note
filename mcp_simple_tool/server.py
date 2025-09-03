from __future__ import annotations

from typing import Any, List
import os
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
            prompt = (arguments or {}).get("prompt")
            model = (arguments or {}).get("model")
            params = (arguments or {}).get("params") or {}
            temperature = float(params.get("temperature", 0.2))
            max_tokens = int(params.get("max_tokens", 400))

            text, tool_calls = await chat_with_tools(prompt, model=model, temperature=temperature, max_tokens=max_tokens)

            actions: list[dict[str, Any]] = []
            if tool_calls:
                for call in tool_calls:
                    tool = call.get("tool")
                    args = call.get("args") or {}
                    if tool == "add_note":
                        res = add_note_tool(args.get("content"), args.get("title"), args.get("tags") or [])
                        actions.append({"tool": tool, "args": args, "result": res})
                    elif tool == "search_notes":
                        res = search_notes_tool(args.get("query"), args.get("title"), args.get("tags") or [])
                        actions.append({"tool": tool, "args": args, "result": res})
                    else:
                        actions.append({"tool": tool, "args": args, "result": {"success": False, "error": "tool not supported"}})

            payload = {"success": True, "text": text, "actions": actions}
            return [types.TextContent(type="text", text=str(payload))]
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
        return [
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
                                "max_tokens": {"type": "integer"}
                            }
                        }
                    }
                }
            ),
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