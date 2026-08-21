import os

import pytest

from app.extractor import extract_article
from app.security import validate_medium_url


TEST_URL = "https://medium.com/data-science-collective/beyond-code-generation-ai-for-the-full-data-science-workflow-ef875dce8453"


@pytest.mark.asyncio
@pytest.mark.skipif(
    os.getenv("RUN_REAL_MEDIUM_TEST") != "1",
    reason="Set RUN_REAL_MEDIUM_TEST=1 to call Medium for the real integration test.",
)
async def test_real_medium_article_extraction():
    source_url, post_id = validate_medium_url(TEST_URL)

    article = await extract_article(source_url, post_id)

    assert article.status in {"ok", "partial"}
    assert article.title
    assert "Beyond Code Generation" in article.title
    assert article.content
    assert article.word_count > 700
    assert len([block for block in article.content.split("\n\n") if block.strip()]) >= 5
    assert article.complete is True
    assert article.warning is None
