from typing import Any
import anyio
import click
import mcp.types as types
from mcp.server.lowlevel import Server
from mcp.shared._httpx_utils import create_mcp_http_client
from starlette.requests import Request

# importa as funções utilitárias que falam com o Supabase
from mcp_simple_tool.tools.notes import add_note_tool, search_notes_tool


async def fetch_website(url: str) -> list[types.ContentBlock]:
    headers = {"User-Agent": "MCP Test Server (github.com/modelcontextprotocol/python-sdk)"}
    async with create_mcp_http_client(headers=headers) as client:
        response = await client.get(url)
        response.raise_for_status()
        return [types.TextContent(type="text", text=response.text)]


@click.command()
@click.option("--port", default=8000, help="Port to listen on for SSE")
@click.option(
    "--transport",
    type=click.Choice(["stdio", "sse"]),
    default="stdio",
    help="Transport type",
)
def main(port: int, transport: str) -> int:
    app = Server("mcp-note-server")

    # -------------------------------
    # Ferramenta: fetch
    # -------------------------------
    #@app.call_tool()
    #async def fetch_tool(name: str, arguments: dict[str, Any]) -> list[types.ContentBlock]:
    #    if name != "fetch":
    #        raise ValueError(f"Unknown tool: {name}")
    #    if "url" not in arguments:
    #        raise ValueError("Missing required argument 'url'")
    #    return await fetch_website(arguments["url"])

    # -------------------------------
    # Ferramenta: add_note
    # -------------------------------
    @app.call_tool()
    async def tools(name: str, arguments: dict[str, Any]) -> list[types.ContentBlock]:
        if name != "add_note":
            raise ValueError(f"Unknown tool: {name}")

        content = arguments.get("content")
        title = arguments.get("title")
        tags = arguments.get("tags", [])

        result = add_note_tool(content, title, tags)
        return [types.TextContent(type="text", text=str(result))]

    # -------------------------------
    # Ferramenta: search_notes
    # -------------------------------
    #@app.call_tool()
    #async def search_notes_handler(name: str, arguments: dict[str, Any]) -> list[types.ContentBlock]:
    #    if name != "search_notes":
    #        raise ValueError(f"Unknown tool: {name}")

    #    query = arguments.get("query")
    #    title = arguments.get("title")
    #    tags = arguments.get("tags", [])

    #    result = search_notes_tool(query, title, tags)
    #    return [types.TextContent(type="text", text=str(result))]

    # -------------------------------
    # Lista de ferramentas disponíveis
    # -------------------------------
    @app.list_tools()
    async def list_tools() -> list[types.Tool]:
        return [
            types.Tool(
                name="fetch",
                title="Website Fetcher",
                description="Fetches a website and returns its content",
                inputSchema={
                    "type": "object",
                    "required": ["url"],
                    "properties": {
                        "url": {"type": "string", "description": "URL to fetch"}
                    },
                },
            ),
            types.Tool(
                name="add_note",
                title="Add Note",
                description="Adiciona uma nova nota no Supabase",
                inputSchema={
                    "type": "object",
                    "required": ["content", "title", "tags"],
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

    # -------------------------------
    # Inicialização do transporte
    # -------------------------------
    if transport == "sse":
        from mcp.server.sse import SseServerTransport
        from starlette.applications import Starlette
        from starlette.responses import Response
        from starlette.routing import Mount, Route

        sse = SseServerTransport("/messages/")

        async def handle_sse(request: Request):
            async with sse.connect_sse(request.scope, request.receive, request._send) as streams:  # type: ignore[reportPrivateUsage]
                await app.run(streams[0], streams[1], app.create_initialization_options())
            return Response()

        starlette_app = Starlette(
            debug=True,
            routes=[
                Route("/sse", endpoint=handle_sse, methods=["GET"]),
                Mount("/messages/", app=sse.handle_post_message),
            ],
        )

        import uvicorn
        uvicorn.run(starlette_app, host="127.0.0.1", port=port)
    else:
        from mcp.server.stdio import stdio_server

        async def arun():
            async with stdio_server() as streams:
                await app.run(streams[0], streams[1], app.create_initialization_options())

        anyio.run(arun)

    return 0
