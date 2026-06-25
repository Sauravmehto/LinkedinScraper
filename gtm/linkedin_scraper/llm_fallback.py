"""Unified LLM caller with automatic provider fallback.

Priority order:
  1. Anthropic (Claude)
  2. Google Gemini (AI Studio)
  3. Groq
  4. Mistral
  5. Cloudflare Workers AI

Each provider is tried only when the previous one fails with a
credit/quota/auth error or returns no usable content.
Network timeouts always bubble up immediately (no silent retry on a
different provider — the caller can retry if needed).
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

import httpx

from gtm.linkedin_scraper.scrapers.http_client import DEFAULT_HEADERS

LogFn = Callable[[str], None]

_ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
_ANTHROPIC_VERSION = "2023-06-01"

_GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
_MISTRAL_API_URL = "https://api.mistral.ai/v1/chat/completions"

_GEMINI_API_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)
_CF_AI_URL = (
    "https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/{model}"
)

ANTHROPIC_DEFAULT_MODEL = "claude-sonnet-4-5-20250929"
ANTHROPIC_FALLBACK_MODELS = (
    "claude-sonnet-4-5-20250929",
    "claude-3-5-sonnet-latest",
    "claude-3-5-haiku-latest",
)
GEMINI_DEFAULT_MODEL = "gemini-2.0-flash"
GROQ_DEFAULT_MODEL = "llama-3.3-70b-versatile"
MISTRAL_DEFAULT_MODEL = "mistral-medium-latest"
CF_DEFAULT_MODEL = "@cf/meta/llama-3.1-8b-instruct"

_CREDIT_STATUS_CODES = {400, 402, 429}


def _is_credit_error(exc: httpx.HTTPStatusError) -> bool:
    if exc.response.status_code in _CREDIT_STATUS_CODES:
        body = ""
        try:
            body = exc.response.text.lower()
        except Exception:
            pass
        credit_phrases = ("credit", "quota", "billing", "insufficient_quota", "rate_limit", "overloaded")
        return any(p in body for p in credit_phrases) or exc.response.status_code == 402
    return False


def _extract_text_from_anthropic(data: dict) -> str:
    parts = [
        b.get("text", "")
        for b in (data.get("content") or [])
        if isinstance(b, dict) and b.get("type") == "text"
    ]
    return "\n".join(parts).strip()


def _extract_text_from_openai(data: dict) -> str:
    choices = data.get("choices") or []
    if not choices:
        return ""
    return (choices[0].get("message") or {}).get("content") or ""


def _extract_text_from_gemini(data: dict) -> str:
    candidates = data.get("candidates") or []
    if not candidates:
        return ""
    parts = (candidates[0].get("content") or {}).get("parts") or []
    return "\n".join(p.get("text", "") for p in parts if isinstance(p, dict)).strip()


def _call_anthropic(
    *,
    api_key: str,
    system: str,
    user_content: str,
    model: str,
    max_tokens: int,
    timeout: float,
    log: LogFn,
) -> str | None:
    """Try each Anthropic model in fallback order. Returns text or None."""
    candidates = list(dict.fromkeys([model, *ANTHROPIC_FALLBACK_MODELS]))
    headers_http = {
        **DEFAULT_HEADERS,
        "x-api-key": api_key,
        "anthropic-version": _ANTHROPIC_VERSION,
        "content-type": "application/json",
    }
    body: dict[str, Any] = {
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": user_content}],
    }
    for candidate in candidates:
        body["model"] = candidate
        try:
            with httpx.Client(timeout=timeout, headers=headers_http) as client:
                resp = client.post(_ANTHROPIC_API_URL, json=body)
                resp.raise_for_status()
            if candidate != model:
                log(f"LLM: Anthropic fallback model used: {candidate}")
            return _extract_text_from_anthropic(resp.json())
        except httpx.HTTPStatusError as exc:
            body_txt = ""
            try:
                body_txt = exc.response.text[:200]
            except Exception:
                pass
            log(f"LLM: Anthropic {candidate} HTTP {exc.response.status_code}: {body_txt}")
            if exc.response.status_code == 404:
                continue
            return None
        except (httpx.HTTPError, OSError) as exc:
            log(f"LLM: Anthropic error: {exc}")
            return None
    return None


def _call_gemini(
    *,
    api_key: str,
    system: str,
    user_content: str,
    model: str,
    max_tokens: int,
    timeout: float,
    log: LogFn,
) -> str | None:
    url = _GEMINI_API_URL.format(model=model)
    combined = f"{system}\n\n{user_content}" if system else user_content
    body: dict[str, Any] = {
        "contents": [{"parts": [{"text": combined}]}],
        "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0.1},
    }
    params = {"key": api_key}
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(url, json=body, params=params)
            resp.raise_for_status()
        return _extract_text_from_gemini(resp.json())
    except httpx.HTTPStatusError as exc:
        body_txt = ""
        try:
            body_txt = exc.response.text[:200]
        except Exception:
            pass
        log(f"LLM: Gemini HTTP {exc.response.status_code}: {body_txt}")
        return None
    except (httpx.HTTPError, OSError) as exc:
        log(f"LLM: Gemini error: {exc}")
        return None


def _call_openai_compat(
    *,
    api_key: str,
    base_url: str,
    model: str,
    system: str,
    user_content: str,
    max_tokens: int,
    timeout: float,
    provider_name: str,
    log: LogFn,
) -> str | None:
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": user_content})
    body: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.1,
    }
    headers_http = {
        **DEFAULT_HEADERS,
        "Authorization": f"Bearer {api_key}",
        "content-type": "application/json",
    }
    try:
        with httpx.Client(timeout=timeout, headers=headers_http) as client:
            resp = client.post(base_url, json=body)
            resp.raise_for_status()
        return _extract_text_from_openai(resp.json())
    except httpx.HTTPStatusError as exc:
        body_txt = ""
        try:
            body_txt = exc.response.text[:200]
        except Exception:
            pass
        log(f"LLM: {provider_name} HTTP {exc.response.status_code}: {body_txt}")
        return None
    except (httpx.HTTPError, OSError) as exc:
        log(f"LLM: {provider_name} error: {exc}")
        return None


def _call_cloudflare(
    *,
    api_token: str,
    account_id: str,
    model: str,
    system: str,
    user_content: str,
    max_tokens: int,
    timeout: float,
    log: LogFn,
) -> str | None:
    url = _CF_AI_URL.format(account_id=account_id, model=model)
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": user_content})
    body: dict[str, Any] = {
        "messages": messages,
        "max_tokens": max_tokens,
    }
    headers_http = {
        **DEFAULT_HEADERS,
        "Authorization": f"Bearer {api_token}",
        "content-type": "application/json",
    }
    try:
        with httpx.Client(timeout=timeout, headers=headers_http) as client:
            resp = client.post(url, json=body)
            resp.raise_for_status()
        data = resp.json()
        result = (data.get("result") or {})
        return result.get("response") or ""
    except httpx.HTTPStatusError as exc:
        body_txt = ""
        try:
            body_txt = exc.response.text[:200]
        except Exception:
            pass
        log(f"LLM: Cloudflare HTTP {exc.response.status_code}: {body_txt}")
        return None
    except (httpx.HTTPError, OSError) as exc:
        log(f"LLM: Cloudflare error: {exc}")
        return None


def llm_call(
    *,
    system: str,
    user_content: str,
    anthropic_api_key: str | None = None,
    anthropic_model: str = ANTHROPIC_DEFAULT_MODEL,
    gemini_api_key: str | None = None,
    gemini_model: str = GEMINI_DEFAULT_MODEL,
    groq_api_key: str | None = None,
    groq_model: str = GROQ_DEFAULT_MODEL,
    mistral_api_key: str | None = None,
    mistral_model: str = MISTRAL_DEFAULT_MODEL,
    cloudflare_api_token: str | None = None,
    cloudflare_account_id: str | None = None,
    cloudflare_model: str = CF_DEFAULT_MODEL,
    max_tokens: int = 8192,
    timeout: float = 90.0,
    log: LogFn | None = None,
) -> str | None:
    """Try providers in order; return first non-empty text response."""
    _log = log or (lambda _m: None)

    if anthropic_api_key:
        text = _call_anthropic(
            api_key=anthropic_api_key,
            system=system,
            user_content=user_content,
            model=anthropic_model,
            max_tokens=max_tokens,
            timeout=timeout,
            log=_log,
        )
        if text:
            return text
        _log("LLM: Anthropic unavailable; trying Gemini")

    if gemini_api_key:
        text = _call_gemini(
            api_key=gemini_api_key,
            system=system,
            user_content=user_content,
            model=gemini_model,
            max_tokens=min(max_tokens, 8192),
            timeout=timeout,
            log=_log,
        )
        if text:
            _log("LLM: Gemini responded")
            return text
        _log("LLM: Gemini unavailable; trying Groq")

    if groq_api_key:
        text = _call_openai_compat(
            api_key=groq_api_key,
            base_url=_GROQ_API_URL,
            model=groq_model,
            system=system,
            user_content=user_content,
            max_tokens=min(max_tokens, 8000),
            timeout=timeout,
            provider_name="Groq",
            log=_log,
        )
        if text:
            _log("LLM: Groq responded")
            return text
        _log("LLM: Groq unavailable; trying Mistral")

    if mistral_api_key:
        text = _call_openai_compat(
            api_key=mistral_api_key,
            base_url=_MISTRAL_API_URL,
            model=mistral_model,
            system=system,
            user_content=user_content,
            max_tokens=min(max_tokens, 8000),
            timeout=timeout,
            provider_name="Mistral",
            log=_log,
        )
        if text:
            _log("LLM: Mistral responded")
            return text
        _log("LLM: Mistral unavailable; trying Cloudflare")

    if cloudflare_api_token and cloudflare_account_id:
        text = _call_cloudflare(
            api_token=cloudflare_api_token,
            account_id=cloudflare_account_id,
            model=cloudflare_model,
            system=system,
            user_content=user_content,
            max_tokens=min(max_tokens, 4096),
            timeout=timeout,
            log=_log,
        )
        if text:
            _log("LLM: Cloudflare responded")
            return text
        _log("LLM: Cloudflare unavailable")

    _log("LLM: all providers exhausted — using deterministic fallback")
    return None


def llm_call_from_config(
    cfg,
    *,
    system: str,
    user_content: str,
    max_tokens: int = 8192,
    timeout: float = 90.0,
    log: LogFn | None = None,
) -> str | None:
    """Convenience wrapper that reads keys from FallbackConfig."""
    return llm_call(
        system=system,
        user_content=user_content,
        anthropic_api_key=getattr(cfg, "anthropic_api_key", None),
        anthropic_model=getattr(cfg, "anthropic_model", None) or ANTHROPIC_DEFAULT_MODEL,
        gemini_api_key=getattr(cfg, "gemini_api_key", None),
        gemini_model=getattr(cfg, "gemini_model", None) or GEMINI_DEFAULT_MODEL,
        groq_api_key=getattr(cfg, "groq_api_key", None),
        groq_model=getattr(cfg, "groq_model", None) or GROQ_DEFAULT_MODEL,
        mistral_api_key=getattr(cfg, "mistral_api_key", None),
        mistral_model=getattr(cfg, "mistral_model", None) or MISTRAL_DEFAULT_MODEL,
        cloudflare_api_token=getattr(cfg, "cloudflare_api_token", None),
        cloudflare_account_id=getattr(cfg, "cloudflare_account_id", None),
        cloudflare_model=getattr(cfg, "cloudflare_model", None) or CF_DEFAULT_MODEL,
        max_tokens=max_tokens,
        timeout=timeout,
        log=log,
    )
