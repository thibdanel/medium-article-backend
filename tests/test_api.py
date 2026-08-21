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


def test_public_extract_accepts_valid_medium_url_without_api_key(client, monkeypatch):
    async def fake_extract(source_url, post_id):
        assert source_url == TEST_URL
        assert post_id == "ef875dce8453"
        return ExtractedArticle(
            status="ok",
            source_url=source_url,
            title="Beyond Code Generation: AI for the Full Data Science Workflow",
            author="Test Author",
            content="word " * 1939,
            word_count=1939,
            complete=True,
        )

    monkeypatch.setattr("app.main.extract_article", fake_extract)

    response = client.get("/api/public/extract", params={"url": TEST_URL})

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["complete"] is True
    assert payload["content"]
    assert payload["word_count"] == 1939


def test_public_extract_refuses_non_medium_url(client):
    response = client.get("/api/public/extract", params={"url": "https://example.com/article-ef875dce8453"})

    assert response.status_code == 400
    assert response.json() == {"status": "error", "error": "Invalid Medium URL"}


@pytest.mark.parametrize(
    "url",
    [
        "http://medium.com/post-title-ef875dce8453",
        "https://localhost/post-title-ef875dce8453",
        "https://127.0.0.1/post-title-ef875dce8453",
        "https://169.254.169.254/post-title-ef875dce8453",
        "https://10.0.0.1/post-title-ef875dce8453",
    ],
)
def test_public_extract_refuses_local_or_internal_urls(client, url):
    response = client.get("/api/public/extract", params={"url": url})

    assert response.status_code == 400
    assert response.json()["error"] == "Invalid Medium URL"


def test_public_extract_respects_rate_limit(client, monkeypatch):
    async def fake_extract(source_url, post_id):
        return ExtractedArticle(
            status="ok",
            source_url=source_url,
            title="Title",
            author="Author",
            content="word " * 800,
            word_count=800,
            complete=True,
        )

    monkeypatch.setattr("app.main.extract_article", fake_extract)
    monkeypatch.setattr("app.main.PUBLIC_RATE_LIMIT_REQUESTS", 2)

    assert client.get("/api/public/extract", params={"url": TEST_URL}).status_code == 200
    assert client.get("/api/public/extract", params={"url": TEST_URL}).status_code == 200

    response = client.get("/api/public/extract", params={"url": TEST_URL})

    assert response.status_code == 429
    assert response.json() == {"status": "error", "error": "Rate limit exceeded"}
    assert response.headers["Retry-After"]


def test_public_extract_returns_complete_article(client, monkeypatch):
    content = "\n\n".join(f"Paragraph {index} with enough words for complete extraction." for index in range(180))

    async def fake_extract(source_url, post_id):
        return ExtractedArticle(
            status="ok",
            source_url=source_url,
            title="Complete Article",
            author="Author",
            content=content,
            word_count=1440,
            complete=True,
        )

    monkeypatch.setattr("app.main.extract_article", fake_extract)

    response = client.get("/api/public/extract", params={"url": TEST_URL})

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["complete"] is True
    assert payload["warning"] is None
    assert payload["content"] == content


def test_public_extract_enforces_response_size_limit(client, monkeypatch):
    async def fake_extract(source_url, post_id):
        return ExtractedArticle(
            status="ok",
            source_url=source_url,
            title="Large Article",
            author="Author",
            content="x" * 11,
            word_count=1,
            complete=True,
        )

    monkeypatch.setattr("app.main.extract_article", fake_extract)
    monkeypatch.setattr("app.main.PUBLIC_MAX_CONTENT_CHARS", 10)

    response = client.get("/api/public/extract", params={"url": TEST_URL})

    assert response.status_code == 413
    assert response.json() == {"status": "error", "error": "Article content exceeds public response size limit"}


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
