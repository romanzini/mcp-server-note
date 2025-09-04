import pytest
import asyncio
from mcp_simple_tool.llm.openrouter_client import chat_with_tools

class DummyResp:
    def __init__(self, content=None, tool_calls=None):
        self.choices = [type('c', (), {'message': type('m', (), {'content': content, 'tool_calls': tool_calls})})]

class DummyToolCall:
    def __init__(self, name, arguments):
        self.function = type('f', (), {'name': name, 'arguments': arguments})

class DummyClient:
    def __init__(self, responses):
        self._responses = responses
        class Chat:
            class Completions:
                def __init__(self, outer):
                    self._outer = outer
                async def create(self, **kwargs):
                    if not self._outer._responses:
                        raise RuntimeError('No more responses')
                    return self._outer._responses.pop(0)
            def __init__(self, outer):
                self.completions = DummyClient.Chat.Completions(outer)
        self.chat = Chat(self)

@pytest.mark.asyncio
async def test_chat_no_tools():
    dummy = DummyClient([DummyResp(content="Olá final")])
    text, acts = await chat_with_tools("Oi", _client=dummy, max_tool_passes=1)
    assert text.startswith("Olá")
    assert acts == []

@pytest.mark.asyncio
async def test_chat_with_tool_and_synthesis():
    # First response calls a tool, second gives final text
    tc = [DummyToolCall("search_notes", '{"query": "python"}')]
    dummy = DummyClient([
        DummyResp(content="Buscando", tool_calls=tc),
        DummyResp(content="Resultado final")
    ])
    text, acts = await chat_with_tools("Procurar notas", _client=dummy, max_tool_passes=2)
    assert text == "Resultado final"
    assert acts and acts[0]['tool'] == 'search_notes'

@pytest.mark.asyncio
async def test_truncation_action():
    long_prompt = 'a' * 5000
    dummy = DummyClient([DummyResp(content="Ok")])
    text, acts = await chat_with_tools(long_prompt, _client=dummy, max_tool_passes=1)
    has_trunc = any(a['tool'] == '_system' and a['result'].get('truncated') for a in acts)
    assert has_trunc
