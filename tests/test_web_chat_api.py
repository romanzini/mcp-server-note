import pytest
import httpx
from mcp_simple_tool.webapp.app import app

@pytest.fixture
async def async_client():
    async with httpx.AsyncClient(app=app, base_url="http://test") as client:
        yield client

def test_chat_endpoint_no_tools(monkeypatch, async_client):
    async def fake_chat(prompt, **kwargs):  # mantém assinatura async
        return ("Resposta direta", [])
    from mcp_simple_tool.llm import orchestrator
    monkeypatch.setattr(orchestrator, 'chat_with_tools', fake_chat)
    r = async_client.post('/api/chat', json={"message": "Olá"})
    assert r.status_code == 200
    data = r.json()
    assert data['response']['text'].startswith('Resposta')
    assert data['response']['actions'] == []

def test_chat_endpoint_with_tool(monkeypatch, async_client):
    calls = {"count": 0}
    async def fake_chat(prompt, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            return ("Draft", [{"tool": "search_notes", "args": {"query": "abc"}}])
        return ("Finalizado", [])
    def fake_search(query, title, tags):
        return {"success": True, "data": {"results": [{"id": 1, "title": "a"}]}}
    from mcp_simple_tool.llm import orchestrator
    monkeypatch.setattr(orchestrator, 'chat_with_tools', fake_chat)
    monkeypatch.setattr('mcp_simple_tool.webapp.app.search_notes_tool', fake_search)
    r = async_client.post('/api/chat', json={"message": "Buscar nota"})
    assert r.status_code == 200
    data = r.json()
    assert data['response']['actions']
    assert data['response']['synthesized'] is True
    assert data['response']['text'] == 'Finalizado'
