import pytest
from unittest.mock import patch, MagicMock
from app.main import app 

@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client

def test_health_endpoint(client):
    """Test the simple /health route."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json == {"status": "ok"}

@patch("app.main.get_cluster_state")
@patch("app.main.summarize_with_claude")
def test_summarize_endpoint(mock_summarize, mock_get_state, client):
    """Test the /summarize route using mocks."""
    # Setup the mock return values
    mock_get_state.return_value = ([], [])
    mock_summarize.return_value = "Everything looks good."

    response = client.get("/summarize")
    
    assert response.status_code == 200
    assert response.json["total_pods"] == 0
    assert response.json["summary"] == "Everything looks good."
    mock_summarize.assert_called_once()