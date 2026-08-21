import pytest

from app.extractor import ExtractedArticle, UpstreamTimeout


TEST_URL = "https://medium.com/data-science-collective/beyond-code-generation-ai-for-the-full-data-science-workflow-ef875dce8453"


def test_health_returns_200(client):
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_non_medium_url_rejected(client, auth_headers):
    response = client.get("/api/extract", params={"url": "https://example.com/article"}, headers=auth_headers)

    assert response.status_code == 400
    assert response.json() == {"status": "error", "error": "Invalid Medium URL"}


def test_valid_medium_url_accepted(client, auth_headers, monkeypatch):
    async def fake_extract(source_url, post_id):
        assert source_url == TEST_URL
        assert post_id == "ef875dce8453"
        return ExtractedArticle(
            status="ok",
            source_url=source_url,
            title="Beyond Code Generation: AI for the Full Data Science Workflow",
            author="Test Author",
            content="word " * 800,
            word_count=800,
            complete=True,
        )

    monkeypatch.setattr("app.main.extract_article", fake_extract)

    response = client.get("/api/extract", params={"url": TEST_URL}, headers=auth_headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["complete"] is True
    assert payload["word_count"] == 800


def test_timeout_handled(client, auth_headers, monkeypatch):
    async def fake_extract(source_url, post_id):
        raise UpstreamTimeout("Upstream timeout")

    monkeypatch.setattr("app.main.extract_article", fake_extract)

    response = client.get("/api/extract", params={"url": TEST_URL}, headers=auth_headers)

    assert response.status_code == 408
    assert response.json() == {"status": "error", "error": "Upstream timeout"}


def test_auth_required(client):
    response = client.get("/api/extract", params={"url": TEST_URL})

    assert response.status_code == 401
    assert response.json() == {"status": "error", "error": "Invalid API key"}


@pytest.mark.parametrize(
    "url",
    [
        "http://medium.com/post-title-ef875dce8453",
        "https://localhost/post-title-ef875dce8453",
        "https://127.0.0.1/post-title-ef875dce8453",
        "https://169.254.169.254/post-title-ef875dce8453",
    ],
)
def test_ssrf_style_urls_rejected(client, auth_headers, url):
    response = client.get("/api/extract", params={"url": url}, headers=auth_headers)

    assert response.status_code == 400
    assert response.json()["error"] == "Invalid Medium URL"
