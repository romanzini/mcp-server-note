from supabase import create_client, Client
from dotenv import load_dotenv
import os
import logging
from typing import Any, Dict, List, Optional, Tuple
import time

class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        from datetime import datetime
        import json

        payload = {
            "ts": datetime.utcfromtimestamp(record.created).isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "module": record.module,
            "func": record.funcName,
            "line": record.lineno,
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def _configure_logger() -> logging.Logger:
    level_name = (os.getenv("MCP_LOG_LEVEL") or os.getenv("LOG_LEVEL") or "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    logger = logging.getLogger("mcp_notes")
    logger.setLevel(level)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setLevel(level)
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
    # Evita duplicar logs em loggers pais
    logger.propagate = False
    return logger


logger = _configure_logger()

# Carrega variáveis de ambiente
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase: Any | None = None  # permite monkeypatch em testes

# Lazy init do cliente Supabase para evitar custo em import/tests sem credenciais
def _init_client() -> Client:
    existing = globals().get('supabase')
    # Aceita dummies injetados em testes (qualquer objeto com 'table')
    if existing is not None and hasattr(existing, 'table'):
        return existing  # type: ignore
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise RuntimeError("Supabase credentials not configured (defina SUPABASE_URL e SUPABASE_KEY)")
    globals()['supabase'] = create_client(SUPABASE_URL, SUPABASE_KEY)
    return globals()['supabase']  # type: ignore

# Cache simples para consultas search_notes
_SEARCH_CACHE: Dict[Tuple[Any, Any, Tuple[str, ...]], Dict[str, Any]] = {}
_CACHE_TTL_SECONDS = 30

_TAG_MAX_LEN = 40
_TAG_ALLOWED_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_")

def _sanitize_tags(tags: List[str]) -> List[str]:
    sanitized: List[str] = []
    for t in tags:
        if not t:
            continue
        t = t.strip()
        if not t:
            continue
        # Limite de tamanho
        if len(t) > _TAG_MAX_LEN:
            t = t[:_TAG_MAX_LEN]
        # Filtra caracteres
        filtered = ''.join(ch for ch in t if ch in _TAG_ALLOWED_CHARS)
        if filtered:
            sanitized.append(filtered)
    # Remove duplicatas preservando ordem
    seen = set()
    uniq: List[str] = []
    for x in sanitized:
        if x not in seen:
            seen.add(x)
            uniq.append(x)
    return uniq


def _ok(data: Any) -> Dict[str, Any]:
    return {"success": True, "data": data}


def _err(message: str, code: Optional[str] = None, details: Any = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"success": False, "error": message}
    if code:
        payload["code"] = code
    if details is not None:
        payload["details"] = details
    return payload


def add_note_tool(content: str, title: str, tags: List[str]) -> Dict[str, Any]:
    """
    Adiciona uma nova nota na tabela 'notes'.
    Retorna: { success: bool, data?: any, error?: str, code?: str, details?: any }
    """
    try:
        tags = _sanitize_tags(tags or [])
        data = {"content": content, "title": title, "tags": tags}
        logger.info("add_note: inserting note title=%s tags=%s", title, tags)
        client = _init_client()
        response = client.table("notes").insert(data).execute()
        resp_dict = getattr(response, "__dict__", {})
        if resp_dict.get("error"):
            err = resp_dict["error"]
            logger.error("add_note: insert error: %s", err)
            if isinstance(err, dict):
                return _err(err.get("message", str(err)), err.get("code"), err.get("details"))
            return _err(str(err))
        if _SEARCH_CACHE:
            _SEARCH_CACHE.clear()
            logger.debug("add_note: cache search_notes invalidated")
        return _ok({"inserted": response.data})
    except Exception as e:
        logger.exception("add_note: exception while inserting")
        return _err(str(e))


def search_notes_tool(
    query: Optional[str], title: Optional[str] = None, tags: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Busca notas que contenham a palavra-chave em content, title ou tags.
    Retorna: { success: bool, data?: any, error?: str, code?: str, details?: any }
    """
    try:
        stags = _sanitize_tags(tags or [])
        cache_key = (query, title, tuple(stags))
        now = time.time()
        cached = _SEARCH_CACHE.get(cache_key)
        if cached and (now - cached.get("_ts", 0) < _CACHE_TTL_SECONDS):
            logger.debug("search_notes: cache hit query=%s title=%s tags=%s", query, title, stags)
            return _ok({"results": cached["results"], "cached": True})
        client = _init_client()
        qb = client.table("notes").select("*")
        if query:
            qb = qb.ilike("content", f"%{query}%")
        if title:
            qb = qb.ilike("title", f"%{title}%")
        if stags:
            qb = qb.overlaps("tags", stags)
        logger.info("search_notes: query=%s title=%s tags=%s", query, title, stags)
        response = qb.execute()
        resp_dict = getattr(response, "__dict__", {})
        if resp_dict.get("error"):
            err = resp_dict["error"]
            logger.error("search_notes: query error: %s", err)
            if isinstance(err, dict):
                return _err(err.get("message", str(err)), err.get("code"), err.get("details"))
            return _err(str(err))
        _SEARCH_CACHE[cache_key] = {"results": response.data, "_ts": now}
        return _ok({"results": response.data, "cached": False})
    except Exception as e:
        logger.exception("search_notes: exception while querying")
        return _err(str(e))
