MCP Server Note
================

Servidor MCP simples para criar e buscar notas armazenadas no Supabase.

Pré-requisitos
- Python 3.12
- Dependências instaladas no venv

Configuração
1) Crie e ative o venv e instale as dependências (exemplo com pip):
	 - Windows PowerShell:
		 - python -m venv venv
		 - ./venv/Scripts/Activate.ps1
		 - pip install -r requirements.txt
		 - pip install mcp[cli]==1.13.1 python-dotenv supabase starlette uvicorn click anyio httpx truststore

2) Crie um arquivo .env na raiz com:
	 - SUPABASE_URL=https://<seu-projeto>.supabase.co
	 - SUPABASE_KEY=<sua-anon-key>

Execução
- Servidor (stdio):
	- venv/Scripts/python.exe -m mcp_simple_tool.server --transport stdio

- Cliente (inicia o servidor stdio automaticamente):
	- venv/Scripts/python.exe client.py

Ferramentas
- fetch: busca o conteúdo de uma URL.
- add_note: insere uma nota (content, title, tags[])
- search_notes: busca por content/title (ilike) e por tags (overlap em text[])
- notes_chat: interface em linguagem natural; usa OpenRouter para decidir e acionar add_note/search_notes e sintetizar a resposta.

SSL / Proxy corporativo
- Ambiente corporativo pode exigir CA customizado. Duas opções:
	1) truststore (recomendado): já habilitado no server; usa o repositório de CAs do Windows.
	2) Modo inseguro (dev apenas): defina $env:MCP_INSECURE_SKIP_VERIFY="1" antes de rodar.

VS Code MCP (mcp.json)
- Aponte para o Python do venv:
	{
		"servers": {
			"my-mcp-server": {
				"type": "stdio",
				"command": "C:/Projetos/mcp-server-note/venv/Scripts/python.exe",
				"args": ["-m", "mcp_simple_tool", "--transport", "stdio"]
			}
		}
	}

Solução de problemas
- Connection closed: verifique se o server está iniciando (arg initialization_options passado a app.run) e se o comando no mcp.json é válido.
- SSL: use truststore ou MCP_INSECURE_SKIP_VERIFY=1.
- Supabase 22P02 / 42883: garanta que tags seja text[] e use overlaps no filtro; evite ILIKE em arrays.

Logs
- Saída estruturada em JSON no stdout para facilitar análise.
- Nível de log configurável por variável de ambiente (prioridade): MCP_LOG_LEVEL, depois LOG_LEVEL. Valores típicos: DEBUG, INFO, WARNING, ERROR.
	- Exemplo (PowerShell): $env:MCP_LOG_LEVEL = "DEBUG"

OpenRouter (LLM)
- Variáveis no .env:
	- OPENROUTER_API_KEY=<sua api key>
	- OPENROUTER_MODEL=openrouter/openai/gpt-4o-mini (padrão)
	- OPENROUTER_BASE_URL=https://openrouter.ai/api/v1 (opcional)
	- OPENROUTER_REFERER, OPENROUTER_TITLE (opcional: boas práticas)
- Dependência: openai (usado com base_url do OpenRouter)
- Uso via MCP (notes_chat):
	- prompt: instrução em linguagem natural
	- params.temperature (opcional), params.max_tokens (opcional)

$env:MCP_INSECURE_SKIP_VERIFY="1"

C:/Projetos/mcp-server-note/venv/Scripts/python.exe -m mcp_simple_tool.server --transport stdio

