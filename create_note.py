import asyncio
import sys
from datetime import datetime
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

NOTE_CONTENT = "Exemplo de criação de nota via MCP server."
NOTE_TAGS = ["mcp", "exemplo"]

async def main():
    title = f"Nota via MCP {datetime.utcnow().isoformat(timespec='seconds')}"
    async with stdio_client(
        StdioServerParameters(command=sys.executable, args=["-m", "mcp_simple_tool", "--transport", "stdio"])
    ) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            payload = {
                "content": NOTE_CONTENT,
                "title": title,
                "tags": NOTE_TAGS,
            }
            result = await session.call_tool("add_note", payload)
            print("Nota criada:")
            print(result)

if __name__ == "__main__":
    asyncio.run(main())
