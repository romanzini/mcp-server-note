import pytest
from fastapi.testclient import TestClient
from mcp_simple_tool.webapp.app import app
from mcp_simple_tool.llm import orchestrator

@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.setenv("AUTH_API_KEY", "k1")

@pytest.fixture
def client():
    return TestClient(app)

def test_network_error_mapping(client, monkeypatch):
    async def fake_chat(prompt, **kw):  # still async to match interface
        raise RuntimeError('{"error":"Falha de conexão","code":"network_error"}')
    monkeypatch.setattr(orchestrator, 'chat_with_tools', fake_chat)
    r = client.post('/api/chat', headers={'x-api-key':'k1'}, json={'message':'oi'})
    assert r.status_code == 502
    data = r.json()
    assert data['code'] == 'network_error'
    assert data['success'] is False