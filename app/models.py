from pydantic import BaseModel
from typing import Optional


class HealthResponse(BaseModel):
    status: str


class ExtractResponse(BaseModel):
    status: str
    source_url: Optional[str] = None
    title: Optional[str] = None
    author: Optional[str] = None
    content: str = ""
    word_count: int = 0
    complete: bool = False
    warning: Optional[str] = None


class ErrorResponse(BaseModel):
    status: str = "error"
    error: str
