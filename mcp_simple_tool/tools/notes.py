from supabase import create_client, Client
from dotenv import load_dotenv
import os

# Carregando as variáveis de ambiente do arquivo .env
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


def add_note_tool(content: str, title: str, tags: list[str]):
    """
    Adiciona uma nova nota na tabela 'notes'.
    """
    data = {
        "content": content,
        "title": title,
        "tags": tags,
    }
    response = supabase.table("notes").insert(data).execute()
    return {"status": "success", "inserted": response.data}


def search_notes_tool(query: str, title: str | None = None, tags: list[str] | None = None):
    """
    Busca notas que contenham a palavra-chave em content, title ou tags.
    """
    query_builder = supabase.table("notes").select("*")

    if query:
        query_builder = query_builder.ilike("content", f"%{query}%")
    if title:
        query_builder = query_builder.ilike("title", f"%{title}%")
    if tags:
        # Busca notas que tenham ao menos uma tag em comum com a lista (array overlap)
        # Usa o método overlaps do supabase-py, que formata corretamente para PostgREST
        query_builder = query_builder.overlaps("tags", tags)

    response = query_builder.execute()
    return {"results": response.data}
