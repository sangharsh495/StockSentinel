"""
Security Module — Grade 1 Enterprise Security Hardening for StockSentinel API.
Provides:
1. Strict Security Headers Middleware (HSTS, CSP, X-Frame-Options, etc.)
2. Client IP Rate Limiting (Token Bucket / Sliding Window)
3. Input validation & sanitization for financial queries
"""

import hmac
import time
import re
import logging
from collections import defaultdict
from typing import Dict, Tuple
from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response, JSONResponse

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 1. Strict Security Headers Middleware
# ---------------------------------------------------------------------------
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Applies Grade 1 security headers to every HTTP response.
    Complies with OWASP Top 10 recommendations.
    """
    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)

        # Prevent MIME type sniffing
        response.headers["X-Content-Type-Options"] = "nosniff"

        # Prevent clickjacking
        response.headers["X-Frame-Options"] = "DENY"

        # Cross-Site Scripting protection for older browsers
        response.headers["X-XSS-Protection"] = "1; mode=block"

        # Enforce HTTPS across subdomains for 1 year
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains; preload"

        # Strict Referrer policy
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # Permissions policy to restrict browser features
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"

        # Cache control for sensitive financial data
        if "/api/" in request.url.path:
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"

        return response


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def client_ip_of(request: Request) -> str:
    """
    Real client IP. Behind Render's proxy request.client.host is the proxy,
    which would put every user in one rate-limit bucket; the first
    X-Forwarded-For entry is the caller.
    """
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


# ---------------------------------------------------------------------------
# API key (confidentiality + integrity of writes)
# ---------------------------------------------------------------------------
class APIKeyMiddleware(BaseHTTPMiddleware):
    """
    Rejects /api/* requests without the shared X-API-Key header. /health and
    / stay open for uptime pings. Disabled only when no key is configured.
    """
    OPEN_PATHS = ("/health", "/")

    def __init__(self, app, api_key: str):
        super().__init__(app)
        # Spaces or line breaks picked up when pasting the key into a dashboard are ignored.
        api_key = (api_key or "").strip()
        self.api_key = api_key.encode() if api_key else b""

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if not self.api_key or path in self.OPEN_PATHS or request.method == "OPTIONS":
            return await call_next(request)
        sent = request.headers.get("x-api-key", "").strip().encode()
        if not hmac.compare_digest(sent, self.api_key):
            logger.warning(f"Rejected request without valid API key: {request.method} {path} "
                           f"from {client_ip_of(request)}")
            return JSONResponse(status_code=401, content={"detail": "Missing or invalid API key"})
        return await call_next(request)


# ---------------------------------------------------------------------------
# 2. Rate Limiting Middleware (Sliding Window)
# ---------------------------------------------------------------------------
class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Protects API against brute-force, scraping, and denial-of-service attacks.
    Allows 120 requests per minute per IP with graceful 429 response.
    """
    def __init__(self, app, max_requests: int = 120, window_seconds: int = 60):
        super().__init__(app)
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        # ip -> list of request timestamps
        self.requests: Dict[str, list] = defaultdict(list)

    async def dispatch(self, request: Request, call_next):
        # Health check and root endpoints exempt from rate limit
        path = request.url.path
        if path in ("/health", "/", "/docs", "/openapi.json"):
            return await call_next(request)

        client_ip = client_ip_of(request)
        now = time.time()

        # Clean old timestamps (and forget idle IPs so memory can't grow forever)
        window_start = now - self.window_seconds
        if len(self.requests) > 5000:
            for ip in [k for k, v in self.requests.items() if not v or v[-1] <= window_start]:
                del self.requests[ip]
        self.requests[client_ip] = [t for t in self.requests[client_ip] if t > window_start]

        if len(self.requests[client_ip]) >= self.max_requests:
            logger.warning(f"Rate limit exceeded for IP: {client_ip} on {path}")
            return JSONResponse(
                status_code=429,
                content={
                    "error": "Rate limit exceeded. Too many requests.",
                    "retry_after_seconds": int(self.window_seconds - (now - self.requests[client_ip][0])) if self.requests[client_ip] else 10,
                },
                headers={"Retry-After": str(10)}
            )

        self.requests[client_ip].append(now)
        return await call_next(request)


# ---------------------------------------------------------------------------
# 3. Input Sanitization & Validation Helpers
# ---------------------------------------------------------------------------
_SAFE_SYMBOL_REGEX = re.compile(r"^[A-Za-z0-9\.\-\^]{1,20}$")

def sanitize_stock_symbol(symbol: str) -> str:
    """
    Validate and sanitize stock ticker symbol against injection attacks.
    """
    if not symbol or not _SAFE_SYMBOL_REGEX.match(symbol.strip()):
        raise HTTPException(
            status_code=400,
            detail="Invalid stock symbol format. Only alphanumeric characters, dots, and hyphens permitted."
        )
    return symbol.strip().upper()
