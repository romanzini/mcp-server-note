import os, tempfile, pytest, httpx
from mcp_simple_tool.webapp.app import app
from mcp_simple_tool.llm import orchestrator

@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("AUTH_API_KEY", "secret")
    monkeypatch.setenv("RATE_LIMIT_PER_MIN", "2")
    fd, path = tempfile.mkstemp(prefix="hist", suffix=".db")
    os.close(fd)
    monkeypatch.setenv("HISTORY_DB_PATH", path)
    yield
    try: os.remove(path)
    except OSError: pass

@pytest.fixture
async def async_client():
    async with httpx.AsyncClient(app=app, base_url="http://test") as client:
        yield client

def test_auth_required(async_client):
    r = async_client.post("/api/chat", json={"message": "oi"})
    assert r.status_code == 401
    async def fake_chat(prompt, **kw): return ("ok", [])
    orchestrator.chat_with_tools = fake_chat  # type: ignore
    r2 = async_client.post("/api/chat", headers={"x-api-key": "secret"}, json={"message": "oi"})
    assert r2.status_code == 200

def test_rate_limit(async_client):
    async def fake_chat(prompt, **kw): return ("resp", [])
    orchestrator.chat_with_tools = fake_chat  # type: ignore
    h = {"x-api-key": "secret"}
    async_client.post("/api/chat", headers=h, json={"message": "a"})
    async_client.post("/api/chat", headers=h, json={"message": "b"})
    r3 = async_client.post("/api/chat", headers=h, json={"message": "c"})
    assert r3.status_code == 429

def test_persistence_history(async_client):
    async def fake_chat(prompt, **kw): return (f"eco:{prompt}", [])
    orchestrator.chat_with_tools = fake_chat  # type: ignore
    h = {"x-api-key": "secret"}
    async_client.post("/api/chat", headers=h, json={"message": "primeira"})
    async_client.post("/api/chat", headers=h, json={"message": "segunda"})
    sid = async_client.post("/api/chat", headers=h, json={"message": "terceira"}).json()["session_id"]
    hist = async_client.get(f"/api/history?session_id={sid}", headers=h)
    assert hist.status_code == 200
    data = hist.json()
    assert len(data["messages"]) >= 6
