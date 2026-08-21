from __future__ import annotations

import logging
import os
import time
from collections import defaultdict, deque
from typing import Deque

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from app.extractor import ArticleUnavailable, ResponseTooLarge, UpstreamTimeout, extract_article
from app.models import ErrorResponse, ExtractResponse, HealthResponse
from app.security import InvalidMediumUrl, require_api_key, validate_medium_url, validate_public_medium_url


logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("medium_backend")

PUBLIC_RATE_LIMIT_REQUESTS = int(os.getenv("PUBLIC_RATE_LIMIT_REQUESTS", "20"))
PUBLIC_RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("PUBLIC_RATE_LIMIT_WINDOW_SECONDS", "3600"))
PUBLIC_MAX_CONTENT_CHARS = int(os.getenv("PUBLIC_MAX_CONTENT_CHARS", "200000"))

app = FastAPI(
    title="Medium Article Backend",
    description="Minimal API to extract Medium article text through Freedium-inspired GraphQL parsing.",
    version="0.1.0",
)
app.state.public_rate_limits = defaultdict(deque)


@app.exception_handler(HTTPException)
async def http_exception_handler(_, exc: HTTPException):
    if isinstance(exc.detail, dict):
        return JSONResponse(status_code=exc.status_code, content=exc.detail, headers=exc.headers)
    return JSONResponse(
        status_code=exc.status_code,
        content={"status": "error", "error": str(exc.detail)},
        headers=exc.headers,
    )


@app.get("/api/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok")


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _check_public_rate_limit(request: Request) -> None:
    now = time.monotonic()
    client_ip = _client_ip(request)
    bucket: Deque[float] = app.state.public_rate_limits[client_ip]
    cutoff = now - PUBLIC_RATE_LIMIT_WINDOW_SECONDS

    while bucket and bucket[0] <= cutoff:
        bucket.popleft()

    if len(bucket) >= PUBLIC_RATE_LIMIT_REQUESTS:
        retry_after = max(1, int(PUBLIC_RATE_LIMIT_WINDOW_SECONDS - (now - bucket[0])))
        raise HTTPException(
            status_code=429,
            detail={"status": "error", "error": "Rate limit exceeded"},
            headers={"Retry-After": str(retry_after)},
        )

    bucket.append(now)


async def _extract_response(source_url: str, post_id: str) -> ExtractResponse:
    try:
        article = await extract_article(source_url, post_id)
    except UpstreamTimeout:
        raise HTTPException(status_code=408, detail={"status": "error", "error": "Upstream timeout"})
    except ResponseTooLarge:
        raise HTTPException(status_code=413, detail={"status": "error", "error": "Unable to retrieve article"})
    except ArticleUnavailable:
        raise HTTPException(status_code=502, detail={"status": "error", "error": "Unable to retrieve article"})

    return ExtractResponse(**article.__dict__)


@app.get(
    "/api/extract",
    response_model=ExtractResponse,
    responses={
        400: {"model": ErrorResponse},
        401: {"model": ErrorResponse},
        408: {"model": ErrorResponse},
        413: {"model": ErrorResponse},
        502: {"model": ErrorResponse},
    },
)
async def extract(
    url: str = Query(..., min_length=10),
    _: None = Depends(require_api_key),
) -> ExtractResponse:
    try:
        source_url, post_id = validate_medium_url(url)
    except InvalidMediumUrl:
        logger.info("extract_rejected invalid_url=%s", url)
        raise HTTPException(status_code=400, detail={"status": "error", "error": "Invalid Medium URL"})

    logger.info("extract_requested url=%s", source_url)

    return await _extract_response(source_url, post_id)


@app.get(
    "/api/public/extract",
    response_model=ExtractResponse,
    responses={
        400: {"model": ErrorResponse},
        408: {"model": ErrorResponse},
        413: {"model": ErrorResponse},
        429: {"model": ErrorResponse},
        502: {"model": ErrorResponse},
    },
)
async def public_extract(
    request: Request,
    url: str = Query(..., min_length=10),
) -> ExtractResponse:
    started = time.perf_counter()
    domain = "unknown"
    status = "error"
    word_count = 0

    try:
        _check_public_rate_limit(request)
        source_url, post_id, domain = validate_public_medium_url(url)
        article = await _extract_response(source_url, post_id)

        if len(article.content) > PUBLIC_MAX_CONTENT_CHARS:
            raise HTTPException(
                status_code=413,
                detail={"status": "error", "error": "Article content exceeds public response size limit"},
            )

        status = article.status
        word_count = article.word_count
        return article
    except InvalidMediumUrl:
        status = "invalid_url"
        raise HTTPException(status_code=400, detail={"status": "error", "error": "Invalid Medium URL"})
    except HTTPException as exc:
        status = str(exc.status_code)
        raise
    finally:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        logger.info(
            "public_extract endpoint=/api/public/extract domain=%s duration_ms=%s status=%s word_count=%s",
            domain,
            elapsed_ms,
            status,
            word_count,
        )
