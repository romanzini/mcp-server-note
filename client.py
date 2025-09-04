import asyncio
import sys
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


async def main():
    async with stdio_client(
        # Usa o mesmo Python do cliente (venv) para iniciar o servidor no Windows
        StdioServerParameters(command=sys.executable, args=["-m", "mcp_simple_tool", "--transport", "stdio"])
    ) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # List available tools
            #tools = await session.list_tools()
            #print("Tools disponíveis:", tools)

            # Call the fetch tool
            #result = await session.call_tool("fetch", {"url": "https://uol.com.br"})
            #print("Resultado do fetch:", result)

            # Exemplo: Notes Chat (LLM via OpenRouter)
            result = await session.call_tool(
                "notes_chat",
                {"prompt": "Crie uma nota 'Reunião de status' com tags [mcp, trabalho]"}
            )
            print("Resultado do notes_chat:", result)

            # Cria uma nova nota (exemplo direto)
            # note = {
            #     "content": "Nota criada via MCP em execução automática.",
            #     "title": "Nota MCP",
            #     "tags": ["mcp", "demo"]
            # }
            # result = await session.call_tool(
            #     "add_note",
            #     {"content": note["content"], "title": note["title"], "tags": note["tags"]}
            # )
            # print("Resultado do add_note:", result)

            # Call the search_notes tool
            # Opcional: depois pesquise a nota
            #search_params = {
            #     "query": "Nota MCP",
            #     "title": "Nota MCP",
            #     "tags": ["mcp"]
            #}
            #result = await session.call_tool("search_notes", search_params)
            #print("Resultado do search_notes:", result)


asyncio.run(main())
