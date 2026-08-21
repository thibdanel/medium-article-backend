from __future__ import annotations

import logging
import os

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

from app.extractor import ArticleUnavailable, ResponseTooLarge, UpstreamTimeout, extract_article
from app.models import ErrorResponse, ExtractResponse, HealthResponse
from app.security import InvalidMediumUrl, require_api_key, validate_medium_url


logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("medium_backend")

app = FastAPI(
    title="Medium Article Backend",
    description="Minimal API to extract Medium article text through Freedium-inspired GraphQL parsing.",
    version="0.1.0",
)


@app.exception_handler(HTTPException)
async def http_exception_handler(_, exc: HTTPException):
    if isinstance(exc.detail, dict):
        return JSONResponse(status_code=exc.status_code, content=exc.detail)
    return JSONResponse(status_code=exc.status_code, content={"status": "error", "error": str(exc.detail)})


@app.get("/api/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok")


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

    try:
        article = await extract_article(source_url, post_id)
    except UpstreamTimeout:
        raise HTTPException(status_code=408, detail={"status": "error", "error": "Upstream timeout"})
    except ResponseTooLarge:
        raise HTTPException(status_code=413, detail={"status": "error", "error": "Unable to retrieve article"})
    except ArticleUnavailable:
        raise HTTPException(status_code=502, detail={"status": "error", "error": "Unable to retrieve article"})

    return ExtractResponse(**article.__dict__)
