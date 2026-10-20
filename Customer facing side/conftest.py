"""Shared fixtures. pytest loads this automatically for every test file."""
import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    """Calls the app in memory – no server needs to be running."""
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def complete_form():
    """A fully filled-in Windows intake form, exactly as the browser would post it."""
    return {
        "category": "windows",
        "affected_ci": "winprd-app01",
        "environment": "prod",
        "symptom": "unreachable",
        "started_at": "2026-10-13T08:30",      # datetime-local format, no seconds
        "recent_changes": "no",
        "change_details": "",
        "business_impact": "high",
        "description": "Server not responding to ping or RDP since 08:30.",
    }
