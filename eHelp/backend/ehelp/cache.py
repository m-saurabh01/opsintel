"""HTTP caching utilities for eHelp API responses."""
from fastapi import Response
from datetime import datetime, timedelta
from hashlib import md5
import json

def set_cache_headers(response: Response, max_age: int = 3600, public: bool = False):
    """Add Cache-Control and ETag headers to response."""
    cache_control = f"max-age={max_age}"
    if public:
        cache_control = f"public, {cache_control}"
    else:
        cache_control = f"private, {cache_control}"
    
    response.headers["Cache-Control"] = cache_control
    response.headers["Vary"] = "Accept-Encoding"
    
    # Add Expires header for older clients
    expires = datetime.utcnow() + timedelta(seconds=max_age)
    response.headers["Expires"] = expires.strftime("%a, %d %b %Y %H:%M:%S GMT")

def set_etag(response: Response, content: str):
    """Calculate and set ETag header."""
    etag = md5(content.encode()).hexdigest()
    response.headers["ETag"] = f'"{etag}"'

def should_use_cache(request_headers: dict, etag: str) -> bool:
    """Check if request includes If-None-Match (304 Not Modified)."""
    if_none_match = request_headers.get("if-none-match", "")
    return if_none_match == f'"{etag}"'

# Cache TTL defaults (seconds)
CACHE_STATIC = 31536000  # 1 year (assets with content hashing)
CACHE_API_DEFAULT = 300  # 5 minutes
CACHE_SEARCH = 60  # 1 minute (search results, more volatile)
CACHE_DOC_META = 3600  # 1 hour (document metadata)
CACHE_PREVIEW = 86400  # 24 hours (file previews)
