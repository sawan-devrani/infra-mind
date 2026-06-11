import pytest
from unittest.mock import patch, MagicMock
import os

# Mock the environment variable BEFORE importing the app
with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "fake-key"}):
    from app.main import app

@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client

def test_health_endpoint(client):
    response = client.get("/health")
    assert response.status_code == 200