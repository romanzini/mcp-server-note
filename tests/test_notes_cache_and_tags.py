import time
from mcp_simple_tool.tools import notes


def test_tag_sanitization_and_dedup():
    raw = ["  python  ", "python", "PyThon!!", "with space", "toolong" + "x"*100, "valid-tag", "INVALID!*&"]
    sanitized = notes._sanitize_tags(raw)  # type: ignore
    # deve manter ordem das versões válidas normalizadas e sem duplicar
    assert sanitized[0] == "python" and sanitized.count("python") == 1
    assert all(len(t) <= 40 for t in sanitized)
    assert all(all(c.isalnum() or c in "-_" for c in t) for t in sanitized)


def test_search_cache_cycle(monkeypatch):
    class DummyResp:
        def __init__(self, data):
            self.data = data
            self.__dict__['error'] = None

    calls = {"count": 0}

    class DummyTable:
        def __init__(self):
            self._filters = []
        def select(self, _):
            return self
        def ilike(self, *a, **k):
            return self
        def overlaps(self, *a, **k):
            return self
        def execute(self):
            calls['count'] += 1
            return DummyResp([{"id": 1, "title": "t"}])

    class DummyClient:
        def table(self, _):
            return DummyTable()

    monkeypatch.setattr(notes, 'supabase', DummyClient())

    # Primeira chamada (miss)
    r1 = notes.search_notes_tool("q", None, ["tag"])  # type: ignore
    assert r1['data']['cached'] is False
    assert calls['count'] == 1
    # Segunda (hit)
    r2 = notes.search_notes_tool("q", None, ["tag"])  # type: ignore
    assert r2['data']['cached'] is True
    assert calls['count'] == 1

    # Invalidação via add_note
    monkeypatch.setattr(notes, 'supabase', DummyClient())
    class DummyInsertTable(DummyTable):
        def insert(self, data):
            class Exec:
                data = [{"id": 99}]
                __dict__ = {"error": None}
                def execute(self_inner):
                    return self_inner
            return Exec()
    class DummyClient2(DummyClient):
        def table(self, name):
            return DummyInsertTable()
    monkeypatch.setattr(notes, 'supabase', DummyClient2())
    notes.add_note_tool("c", "t", ["tag"])  # type: ignore

    # Após invalidação, nova busca deve ser miss novamente
    monkeypatch.setattr(notes, 'supabase', DummyClient())
    r3 = notes.search_notes_tool("q", None, ["tag"])  # type: ignore
    assert r3['data']['cached'] is False
    assert calls['count'] == 2
