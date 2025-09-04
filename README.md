## MCP Server Note

Servidor MCP + API web para criação, busca e chat inteligente sobre notas (Supabase + OpenRouter).

### Visão Geral
Componentes:
- Ferramentas MCP: `add_note`, `search_notes`, (opcional) `notes_chat`.
- Orquestrador LLM multi‑pass (`run_notes_chat`): planejamento → execução de ferramentas → síntese final.
- API Web (FastAPI) com histórico (SQLite), autenticação por API key, rate limiting e interface HTML simples.
- Tratamento de erros de rede / proxy com códigos diferenciados.

### Pré‑requisitos
- Python >= 3.12
- Chaves Supabase (se quiser persistência real de notas) e OpenRouter (para LLM real).

### Instalação
```powershell
python -m venv venv
./venv/Scripts/Activate.ps1
pip install -e .
```

Arquivo `.env` (exemplo mínimo):
```
SUPABASE_URL=https://<seu-projeto>.supabase.co
SUPABASE_KEY=<anon-key>
OPENROUTER_API_KEY=<sua-key>
ENABLE_NOTES_CHAT=1
```

### Executar (MCP stdio)
```powershell
venv/Scripts/python.exe -m mcp_simple_tool.server --transport stdio
```

Cliente de exemplo:
```powershell
venv/Scripts/python.exe client.py
```

### API Web / UI
Iniciar:
```powershell
python -m mcp_simple_tool.webapp.app
```
Variáveis úteis: `FRONTEND_PORT`, `AUTH_API_KEY`, `RATE_LIMIT_PER_MIN`, `HISTORY_DB_PATH`.

Endpoints:
- `POST /api/chat`  { message, session_id?, model?, params? }
- `GET  /api/history?session_id=...`

### Persistência de Histórico (SQLite)
- Ativa por padrão (`chat_history.db`).
- `HISTORY_DB_PATH` para custom path.
- `DISABLE_PERSISTENCE=1` para desativar.

### Autenticação & Rate Limit
- `AUTH_API_KEY` exige header `x-api-key` (ou `?api_key=`).
- `RATE_LIMIT_PER_MIN` (default 60) por chave/IP.

### Variáveis de Ambiente (Resumo)
| Variável | Função |
|----------|--------|
| SUPABASE_URL / SUPABASE_KEY | Credenciais Supabase |
| OPENROUTER_API_KEY | Chave LLM (obrigatória para uso real) |
| OPENROUTER_MODEL | Modelo (default auto) |
| OPENROUTER_BASE_URL | Endpoint OpenRouter (default oficial) |
| OPENROUTER_REFERER / OPENROUTER_TITLE | Header de boas práticas |
| ENABLE_NOTES_CHAT | Ativa ferramenta de chat no MCP |
| MCP_LOG_LEVEL / LOG_LEVEL | Nível de log (DEBUG, INFO, ...) |
| HISTORY_DB_PATH | Caminho SQLite de histórico |
| DISABLE_PERSISTENCE | Desliga histórico se definido |
| AUTH_API_KEY | Protege endpoints web |
| RATE_LIMIT_PER_MIN | Limite por minuto |
| FRONTEND_PORT | Porta interface web |
| MCP_INSECURE_SKIP_VERIFY | Pular verificação TLS (dev) |

### Fluxo LLM (Multi‑Pass)
1. Passo de planejamento: modelo pode sugerir `tool_calls`.
2. Execução real das ferramentas (fora do modelo).
3. Passo de síntese final (sem novas ferramentas) consolidando resultados (máx 10 notas para economizar tokens).
4. Resposta final: `{ text, actions, synthesized }`.

### Cache & Tags
- Cache in‑memory para `search_notes` (TTL 30s) por (query, title, tags).
- `add_note` invalida totalmente o cache.
- Tags sanitizadas (trim, <=40 chars, charset `[A-Za-z0-9-_]`, sem duplicatas mantendo ordem).

### Tratamento de Erros (Web)
| Situação | HTTP | JSON adicional |
|----------|------|----------------|
| Proxy corporativo bloqueando (403 com HTML) | 502 | `proxy_blocked: true` |
| Falha de rede/conexão | 502 | `code: "network_error"` |
| Rate limit interno LLM (429) | 429 | `status: 429` |
| Genérico LLM | 500 | `error` truncado |

### Logs
- JSON estruturado no stdout.
- Ajuste nível via `MCP_LOG_LEVEL` (preferência) ou `LOG_LEVEL`.

### VS Code (mcp.json)
```json
{
	"servers": {
		"notes-mcp": {
			"type": "stdio",
			"command": "C:/Projetos/mcp-server-note/venv/Scripts/python.exe",
			"args": ["-m", "mcp_simple_tool.server", "--transport", "stdio"]
		}
	}
}
```

### Testes
Rodar tudo:
```powershell
pytest -q
```
Principais arquivos:
- `tests/test_openrouter_client.py` (multi‑pass + truncation)
- `tests/test_notes_cache_and_tags.py` (cache / tags)
- `tests/test_web_chat_api.py` (chat + síntese) *usa httpx.AsyncClient*
- `tests/test_web_chat_security_persistence.py` (auth, rate limit, histórico)
- `tests/test_error_mapping.py` (mapeamento network/proxy) *pode stubbar orchestrator*

### Exemplo Rápido (PowerShell)
```powershell
$env:OPENROUTER_API_KEY = "xxxx"
$env:ENABLE_NOTES_CHAT = "1"
python -m mcp_simple_tool.server --transport stdio
```

### Solução de Problemas
- "Connection closed": verifique comando no `mcp.json` e variáveis obrigatórias.
- Erros SSL corporativo: usar store do sistema (truststore) ou `MCP_INSECURE_SKIP_VERIFY=1` (apenas dev).
- 403 HTML: proxy bloqueando → resposta 502 com `proxy_blocked`.
- `network_error`: ver rede/proxy antes de repetir.
- Supabase erros de operador: certificar coluna `tags` tipo `text[]` e uso de `overlaps`.

### Segurança
Não reutilize a mesma `AUTH_API_KEY` em produção sem rotação. Considere adaptar para JWT / OAuth se expor publicamente.

### Roadmap (Ideias Futuras)
- Streaming (SSE/WebSocket) de tokens/síntese.
- Rotação de histórico / tamanho máximo.
- Policies de retry configuráveis.
- Indexação full‑text opcional.

---
Projeto em evolução – contribuições e melhorias são bem‑vindas.