import asyncio
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


async def main():
    async with stdio_client(
    # Executa diretamente com Python para compatibilidade no Windows sem uv CLI
    StdioServerParameters(command="python", args=["-m", "mcp_simple_tool"])
    ) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # List available tools
            #tools = await session.list_tools()
            #print("Tools disponíveis:", tools)

            # Call the fetch tool
            #result = await session.call_tool("fetch", {"url": "https://uol.com.br"})
            #print("Resultado do fetch:", result)

            # Exemplo: chame a ferramenta add_note (descomente para usar)
            note = {
                "content": "Esta é uma nota de teste 2.",
                "title": "Nota de Teste 2",
                "tags": ["teste", "demo", "mcp"]
            }
            #result = await session.call_tool(
            #    "add_note",
            #    {"content": note["content"], "title": note["title"], "tags": note["tags"]}
            # )
            #print("Resultado do add_note:", result)

            # Call the search_notes tool
            search_params = {
                "query": "reunião",
                "title": "reunião",
                "tags": ["reunião"]
            }
            result = await session.call_tool("search_notes", search_params)
            print("Resultado do search_notes:", result)


asyncio.run(main())
