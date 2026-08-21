from __future__ import annotations

import asyncio
import html
import logging
import os
import re
import secrets
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import httpx
from curl_cffi.requests import AsyncSession


logger = logging.getLogger("medium_backend.extractor")

GRAPHQL_URL = "https://medium.com/_/graphql"
MAX_RESPONSE_BYTES = int(os.getenv("MAX_RESPONSE_BYTES", "5242880"))
UPSTREAM_TIMEOUT_SECONDS = float(os.getenv("UPSTREAM_TIMEOUT_SECONDS", "10"))
MIN_COMPLETE_WORDS = int(os.getenv("MIN_COMPLETE_WORDS", "700"))
MIN_COMPLETE_PARAGRAPHS = int(os.getenv("MIN_COMPLETE_PARAGRAPHS", "5"))


class ExtractorError(Exception):
    pass


class UpstreamTimeout(ExtractorError):
    pass


class ArticleUnavailable(ExtractorError):
    pass


class ResponseTooLarge(ExtractorError):
    pass


@dataclass(frozen=True)
class ExtractedArticle:
    status: str
    source_url: Optional[str]
    title: Optional[str]
    author: Optional[str]
    content: str
    word_count: int
    complete: bool
    warning: Optional[str] = None


FULL_POST_QUERY = """
query FullPostQuery($postId: ID!, $postMeteringOptions: PostMeteringOptions) {
  post(id: $postId) {
    id
    title
    mediumUrl
    isLocked
    readingTime
    previewContent { subtitle }
    creator { name username }
    content(postMeteringOptions: $postMeteringOptions) {
      bodyModel {
        paragraphs {
          id
          name
          text
          type
          markups { type start end href title rel anchorType }
          codeBlockMetadata { lang mode }
        }
      }
      validatedShareKey
    }
  }
}
"""


def _headers() -> Dict[str, str]:
    return {
        "X-APOLLO-OPERATION-ID": secrets.token_hex(32),
        "X-APOLLO-OPERATION-NAME": "FullPostQuery",
        "Accept": "application/json",
        "Accept-Language": "en-US",
        "X-Obvious-CID": "android",
        "X-Xsrf-Token": "1",
        "User-Agent": "AdsBot-Google-Mobile",
        "Cache-Control": "no-cache",
        "Content-Type": "application/json",
    }


async def _read_limited_response(response: httpx.Response) -> bytes:
    chunks: List[bytes] = []
    total = 0
    async for chunk in response.aiter_bytes():
        total += len(chunk)
        if total > MAX_RESPONSE_BYTES:
            raise ResponseTooLarge("Medium response too large")
        chunks.append(chunk)
    return b"".join(chunks)


async def fetch_medium_post(post_id: str, client: Optional[httpx.AsyncClient] = None) -> Dict[str, Any]:
    payload = {
        "operationName": "FullPostQuery",
        "variables": {"postId": post_id, "postMeteringOptions": {}},
        "query": FULL_POST_QUERY,
    }

    if client is not None:
        response = await client.post(GRAPHQL_URL, headers=_headers(), json=payload)
        if response.status_code != 200:
            logger.warning("medium_graphql_non_200 status_code=%s post_id=%s", response.status_code, post_id)
            raise ArticleUnavailable("Unable to retrieve article")

        raw = await _read_limited_response(response)
        return response.json() if not raw else httpx.Response(200, content=raw).json()

    try:
        async with AsyncSession(timeout=UPSTREAM_TIMEOUT_SECONDS) as session:
            response = await session.post(
                GRAPHQL_URL,
                headers=_headers(),
                json=payload,
                timeout=UPSTREAM_TIMEOUT_SECONDS,
                impersonate="chrome110",
            )

        if response.status_code != 200:
            logger.warning("medium_graphql_non_200 status_code=%s post_id=%s", response.status_code, post_id)
            raise ArticleUnavailable("Unable to retrieve article")

        content = response.content
        if len(content) > MAX_RESPONSE_BYTES:
            raise ResponseTooLarge("Medium response too large")
        return response.json()
    except (httpx.TimeoutException, asyncio.TimeoutError) as exc:
        raise UpstreamTimeout("Upstream timeout") from exc
    except ResponseTooLarge:
        raise
    except ArticleUnavailable:
        raise
    except Exception as exc:
        raise ArticleUnavailable("Unable to retrieve article") from exc


def extract_text_from_post_data(post_data: Dict[str, Any], source_url: Optional[str]) -> ExtractedArticle:
    post = post_data.get("data", {}).get("post")
    if not post:
        raise ArticleUnavailable("Unable to retrieve article")

    title = _clean_text(post.get("title"))
    source_url = source_url or _clean_text(post.get("mediumUrl"))
    creator = post.get("creator") or {}
    author = _clean_text(creator.get("name")) or _clean_text(creator.get("username"))

    body_model = (post.get("content") or {}).get("bodyModel") or {}
    paragraphs = body_model.get("paragraphs") or []

    text_blocks = _paragraphs_to_text_blocks(paragraphs, title)
    content = "\n\n".join(text_blocks).strip()
    word_count = count_words(content)
    paragraph_count = sum(1 for block in text_blocks if count_words(block) >= 5)

    complete, warning = assess_completeness(
        title=title,
        content=content,
        word_count=word_count,
        paragraph_count=paragraph_count,
        raw_paragraph_count=len(paragraphs),
    )

    return ExtractedArticle(
        status="ok" if complete else "partial",
        source_url=source_url,
        title=title,
        author=author,
        content=content,
        word_count=word_count,
        complete=complete,
        warning=warning,
    )


def _paragraphs_to_text_blocks(paragraphs: List[Dict[str, Any]], title: Optional[str]) -> List[str]:
    blocks: List[str] = []
    list_buffer: List[str] = []

    def flush_list() -> None:
        nonlocal list_buffer
        if list_buffer:
            blocks.append("\n".join(f"- {item}" for item in list_buffer))
            list_buffer = []

    for index, paragraph in enumerate(paragraphs):
        paragraph_type = paragraph.get("type")
        text = _clean_text(paragraph.get("text"))
        if not text:
            continue

        if index <= 3 and title and _similar(text, title) > 0.9:
            continue

        if paragraph_type in {"P", "H2", "H3", "H4", "BQ", "PQ", "PRE"}:
            flush_list()
            blocks.append(text)
        elif paragraph_type in {"ULI", "OLI"}:
            list_buffer.append(text)

    flush_list()
    return blocks


def _clean_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = html.unescape(str(value))
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def _similar(left: str, right: str) -> float:
    left_words = set(left.lower().split())
    right_words = set(right.lower().split())
    if not left_words or not right_words:
        return 0.0
    return len(left_words & right_words) / max(len(left_words), len(right_words))


def count_words(text: str) -> int:
    return len(re.findall(r"\b[\w'-]+\b", text))


def assess_completeness(
    *,
    title: Optional[str],
    content: str,
    word_count: int,
    paragraph_count: int,
    raw_paragraph_count: int,
) -> Tuple[bool, Optional[str]]:
    if not content.strip():
        return False, "Extraction possibly incomplete: empty content"
    if paragraph_count < 2:
        return False, "Extraction possibly incomplete: too few paragraphs"
    if word_count < 120:
        return False, "Extraction possibly incomplete: content too short"
    if title and word_count <= count_words(title) + 80:
        return False, "Extraction possibly incomplete: only title or preview text found"
    if raw_paragraph_count < MIN_COMPLETE_PARAGRAPHS or word_count < MIN_COMPLETE_WORDS:
        return False, "Extraction possibly incomplete"
    return True, None


async def extract_article(source_url: Optional[str], post_id: str) -> ExtractedArticle:
    started = time.perf_counter()
    try:
        post_data = await fetch_medium_post(post_id)
        article = extract_text_from_post_data(post_data, source_url)
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        logger.info(
            "extract_success url=%s duration_ms=%s word_count=%s complete=%s",
            source_url,
            elapsed_ms,
            article.word_count,
            article.complete,
        )
        return article
    except Exception:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        logger.info("extract_error url=%s duration_ms=%s", source_url, elapsed_ms)
        raise
