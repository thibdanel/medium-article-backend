from app.extractor import assess_completeness, extract_text_from_post_data


def test_empty_extraction_detected():
    complete, warning = assess_completeness(
        title="A title",
        content="",
        word_count=0,
        paragraph_count=0,
        raw_paragraph_count=0,
    )

    assert complete is False
    assert "empty content" in warning


def test_partial_extraction_detected():
    complete, warning = assess_completeness(
        title="A title",
        content="Only a short preview paragraph.",
        word_count=5,
        paragraph_count=1,
        raw_paragraph_count=1,
    )

    assert complete is False
    assert warning


def test_post_data_to_plain_text_complete():
    paragraphs = [{"type": "P", "text": "This is paragraph number %s with useful article text." % i} for i in range(120)]
    post_data = {
        "data": {
            "post": {
                "title": "Article title",
                "mediumUrl": "https://medium.com/example/article-abcdef1234",
                "creator": {"name": "Author"},
                "content": {"bodyModel": {"paragraphs": paragraphs}},
            }
        }
    }

    article = extract_text_from_post_data(post_data, "https://medium.com/example/article-abcdef1234")

    assert article.status == "ok"
    assert article.complete is True
    assert article.author == "Author"
    assert article.word_count >= 700
    assert "paragraph number 10" in article.content
