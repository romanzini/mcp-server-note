import os
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

@pytest.fixture(autouse=True)
def _base_env(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("AUTH_API_KEY", "k1")
    monkeypatch.setenv("DISABLE_PERSISTENCE", "1")

