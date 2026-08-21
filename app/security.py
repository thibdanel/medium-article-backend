from __future__ import annotations

import ipaddress
import os
import re
from typing import Optional, Tuple
from urllib.parse import urlparse

from fastapi import Header, HTTPException


ALLOWED_MEDIUM_HOSTS = {
    "medium.com",
    "towardsdatascience.com",
    "levelup.gitconnected.com",
    "betterprogramming.pub",
    "uxdesign.cc",
    "writingcooperative.com",
    "entrepreneurshandbook.co",
    "betterhumans.pub",
    "itnext.io",
    "ai.plainenglish.io",
    "python.plainenglish.io",
    "javascript.plainenglish.io",
    "blog.stackademic.com",
    "generativeai.pub",
}

LOCAL_HOSTNAMES = {"localhost", "localhost.localdomain"}
POST_ID_PATTERN = re.compile(r"^[A-Za-z0-9]{8,12}$")
PUBLIC_POST_ID_PATTERN = re.compile(r"^[0-9a-f]{12}$", re.IGNORECASE)


class InvalidMediumUrl(ValueError):
    pass


def _normalize_host(host: Optional[str]) -> str:
    if not host:
        raise InvalidMediumUrl("Invalid Medium URL")

    host = host.rstrip(".").lower()
    if host.startswith("www."):
        host = host[4:]
    return host


def _reject_local_or_ip_host(host: str) -> None:
    if host in LOCAL_HOSTNAMES or host.endswith(".localhost"):
        raise InvalidMediumUrl("Invalid Medium URL")

    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return

    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    ):
        raise InvalidMediumUrl("Invalid Medium URL")

    raise InvalidMediumUrl("Invalid Medium URL")


def _is_allowed_medium_host(host: str) -> bool:
    return host == "medium.com" or host.endswith(".medium.com") or host in ALLOWED_MEDIUM_HOSTS


def _is_public_medium_host(host: str) -> bool:
    return host == "medium.com" or host.endswith(".medium.com")


def validate_medium_url(url: str) -> Tuple[str, str]:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise InvalidMediumUrl("Invalid Medium URL")

    host = _normalize_host(parsed.hostname)
    _reject_local_or_ip_host(host)

    if not _is_allowed_medium_host(host):
        raise InvalidMediumUrl("Invalid Medium URL")

    post_id = extract_post_id(parsed.path)
    if not post_id:
        raise InvalidMediumUrl("Invalid Medium URL")

    clean_url = parsed._replace(query="", fragment="").geturl()
    return clean_url, post_id


def validate_public_medium_url(url: str) -> Tuple[str, str, str]:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise InvalidMediumUrl("Invalid Medium URL")

    host = _normalize_host(parsed.hostname)
    _reject_local_or_ip_host(host)

    if not _is_public_medium_host(host):
        raise InvalidMediumUrl("Invalid Medium URL")

    post_id = extract_post_id(parsed.path)
    if not post_id:
        raise InvalidMediumUrl("Invalid Medium URL")

    clean_url = parsed._replace(query="", fragment="").geturl()
    return clean_url, post_id, host


def validate_public_post_id(post_id: str) -> str:
    if not PUBLIC_POST_ID_PATTERN.fullmatch(post_id or ""):
        raise InvalidMediumUrl("Invalid Medium post ID")
    return post_id.lower()


def extract_post_id(path: str) -> Optional[str]:
    if path.startswith("/p/"):
        candidate = path.rsplit("/p/", 1)[1].strip("/").split("/", 1)[0]
    else:
        slug = path.strip("/").split("/")[-1]
        candidate = slug.rsplit("-", 1)[-1]

    if POST_ID_PATTERN.fullmatch(candidate or ""):
        return candidate
    return None


def require_api_key(x_api_key: Optional[str] = Header(default=None, alias="X-API-Key")) -> None:
    expected = os.getenv("API_KEY")
    if not expected:
        raise HTTPException(status_code=500, detail={"status": "error", "error": "API key not configured"})

    if not x_api_key or x_api_key != expected:
        raise HTTPException(status_code=401, detail={"status": "error", "error": "Invalid API key"})
