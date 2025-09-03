from supabase import create_client, Client
from dotenv import load_dotenv
import os
import logging
from typing import Any, Dict, List, Optional

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

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


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
        data = {"content": content, "title": title, "tags": tags}
        logger.info("add_note: inserting note title=%s tags=%s", title, tags)
        response = supabase.table("notes").insert(data).execute()
        # Alguns drivers retornam erro em atributo; se houver, devolve padronizado
        resp_dict = getattr(response, "__dict__", {})
        if resp_dict.get("error"):
            err = resp_dict["error"]
            logger.error("add_note: insert error: %s", err)
            # Pode ser dict ou str
            if isinstance(err, dict):
                return _err(err.get("message", str(err)), err.get("code"), err.get("details"))
            return _err(str(err))
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
        qb = supabase.table("notes").select("*")
        if query:
            qb = qb.ilike("content", f"%{query}%")
        if title:
            qb = qb.ilike("title", f"%{title}%")
        if tags:
            # Overlap de arrays para coluna text[]
            qb = qb.overlaps("tags", tags)

        logger.info("search_notes: query=%s title=%s tags=%s", query, title, tags)
        response = qb.execute()
        resp_dict = getattr(response, "__dict__", {})
        if resp_dict.get("error"):
            err = resp_dict["error"]
            logger.error("search_notes: query error: %s", err)
            if isinstance(err, dict):
                return _err(err.get("message", str(err)), err.get("code"), err.get("details"))
            return _err(str(err))
        return _ok({"results": response.data})
    except Exception as e:
        logger.exception("search_notes: exception while querying")
        return _err(str(e))
