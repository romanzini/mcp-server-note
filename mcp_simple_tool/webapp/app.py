from __future__ import annotations
import os, uuid, logging, time, json
from typing import Any, Dict
from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.responses import JSONResponse
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from mcp_simple_tool.llm.orchestrator import run_notes_chat
from mcp_simple_tool.tools.notes import add_note_tool, search_notes_tool
from . import storage

logger = logging.getLogger("mcp_notes.webapp")
if not logger.handlers:
    logging.basicConfig(level=os.getenv("MCP_LOG_LEVEL") or os.getenv("LOG_LEVEL") or "INFO")

app = FastAPI(title="Notes Chat UI")
_SESSIONS: Dict[str, list[dict[str, Any]]] = {}
_RATE_STATE: Dict[str, Dict[str, Any]] = {}

def _init_persistence():  # pragma: no cover
    if os.getenv("DISABLE_PERSISTENCE"):
        return
    db_path = os.getenv("HISTORY_DB_PATH", "chat_history.db")
    try:
        storage.init(db_path)
        logger.info("history persistence enabled path=%s", db_path)
    except Exception:
        logger.exception("failed enabling persistence")

_init_persistence()

def auth_dep(request: Request):
    required = os.getenv("AUTH_API_KEY")
    if not required:
        return
    provided = request.headers.get("x-api-key") or request.query_params.get("api_key")
    if provided != required:
        raise HTTPException(401, detail="unauthorized")

def rate_limit_dep(request: Request):
    limit = int(os.getenv("RATE_LIMIT_PER_MIN", "60"))
    if limit <= 0:
        return
    key_base = request.headers.get("x-api-key") or (request.client.host if request.client else "anon")
    window = int(time.time() // 60)
    key = f"{key_base}:{window}"
    state = _RATE_STATE.get(key)
    if not state:
        _RATE_STATE[key] = {"count": 1}
        return
    state["count"] += 1
    if state["count"] > limit:
        raise HTTPException(429, detail="rate limit exceeded")

class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    session_id: str | None = None
    model: str | None = None
    params: dict[str, Any] | None = None

@app.post("/api/chat")
async def api_chat(req: ChatRequest, _: Any = Depends(auth_dep), __: Any = Depends(rate_limit_dep)):
    if not os.getenv("OPENROUTER_API_KEY"):
        raise HTTPException(400, detail="OPENROUTER_API_KEY não configurada")
    session_id = req.session_id or uuid.uuid4().hex
    history = _SESSIONS.setdefault(session_id, [])
    history.append({"role": "user", "text": req.message})
    storage.save_message(session_id, "user", req.message)
    try:
        payload = await run_notes_chat(
            req.message,
            model=req.model,
            params=req.params or {},
            add_note_func=add_note_tool,
            search_notes_func=search_notes_tool,
        )
    except Exception as e:  # pragma: no cover
        logger.exception("chat error")
        # Tenta decodificar payload JSON do RuntimeError
        body = str(e)
        try:
            meta = json.loads(body)
            if not isinstance(meta, dict):
                raise ValueError
            # Normaliza shape
            meta.setdefault("success", False)
            status = 500
            if meta.get("proxy_blocked"):
                status = 502
            elif meta.get("code") == "network_error":
                status = 502
            elif meta.get("status") in (401, 403):
                status = int(meta.get("status"))
            elif meta.get("status") == 429:
                status = 429
            return JSONResponse(meta, status_code=status)
        except Exception:
            raise HTTPException(500, detail=body)
    history.append({"role": "assistant", "text": payload["text"], "actions": payload["actions"]})
    storage.save_message(session_id, "assistant", payload["text"], payload["actions"])
    return {"session_id": session_id, "response": payload}

@app.get("/api/history")
async def api_history(session_id: str, _: Any = Depends(auth_dep)):
    persisted = storage.load_history(session_id)
    if persisted:
        return {"session_id": session_id, "messages": persisted}
    return {"session_id": session_id, "messages": _SESSIONS.get(session_id, [])}

@app.get("/", response_class=HTMLResponse)
async def index_page():  # pragma: no cover
    index_path = os.path.join(os.path.dirname(__file__), "static", "index.html")
    if not os.path.exists(index_path):
        return HTMLResponse("<h1>Interface não encontrada</h1>", status_code=500)
    with open(index_path, "r", encoding="utf-8") as f:
        return HTMLResponse(f.read())

static_dir = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=static_dir), name="static")

def run():  # pragma: no cover
    import uvicorn
    uvicorn.run("mcp_simple_tool.webapp.app:app", host="127.0.0.1", port=int(os.getenv("FRONTEND_PORT", 9000)), reload=False)

if __name__ == "__main__":  # pragma: no cover
    run()
