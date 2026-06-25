"""Configuration helpers for optional fallback APIs."""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

ENV_PATH = Path(__file__).resolve().parents[2] / ".env"

# Company LinkedIn fallbacks after Step 3 (team pages → Tavily → Apollo).
DEFAULT_FALLBACK_STEPS: tuple[int, ...] = (7, 8, 9)

# People discovery sources for run-gtm / max coverage (Bing + paid APIs).
RECOMMENDED_PEOPLE_SOURCES: tuple[str, ...] = ("bing", "serper", "apollo")

# Max mode: run Serper/Apollo/Tavily unless this many scored profiles already exist.
MAX_MODE_MIN_BEFORE_SERPER = 8
MAX_MODE_MIN_BEFORE_APOLLO = 8
MAX_MODE_MIN_BEFORE_TAVILY = 5
MAX_MODE_SERPER_QUERIES = 8
MAX_MODE_TAVILY_QUERIES = 8
MAX_MODE_FREE_QUERIES_PER_COMPANY = 24


@dataclass(frozen=True)
class FallbackConfig:
    brave_api_key: str | None
    serper_api_key: str | None
    tavily_api_key: str | None
    apollo_api_key: str | None
    firecrawl_api_key: str | None = None
    proxycurl_api_key: str | None = None
    rocketreach_api_key: str | None = None
    anthropic_api_key: str | None = None
    anthropic_model: str | None = None
    # ---- LLM fallback providers ----
    gemini_api_key: str | None = None
    gemini_model: str | None = None
    groq_api_key: str | None = None
    groq_model: str | None = None
    mistral_api_key: str | None = None
    mistral_model: str | None = None
    cloudflare_api_token: str | None = None
    cloudflare_account_id: str | None = None
    cloudflare_model: str | None = None
    # --------------------------------
    hubspot_access_token: str | None = None
    hubspot_contact_owner_id: str | None = None
    hubspot_lifecycle_stage: str | None = None
    hubspot_lead_status: str | None = None
    hubspot_person_linkedin_property: str | None = None
    hubspot_company_linkedin_property: str | None = None
    apollo_webhook_url: str | None = None
    apollo_phone_poll_timeout: float = 120.0
    apollo_phone_poll_interval: float = 5.0


def _load_dotenv_file(path: Path = ENV_PATH) -> None:
    """Load KEY=VALUE lines into process env when .env exists."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def load_fallback_config() -> FallbackConfig:
    _load_dotenv_file()
    return FallbackConfig(
        brave_api_key=os.getenv("BRAVE_API_KEY"),
        serper_api_key=os.getenv("SERPER_API_KEY"),
        tavily_api_key=os.getenv("TAVILY_API_KEY"),
        apollo_api_key=os.getenv("APOLLO_API_KEY"),
        firecrawl_api_key=os.getenv("FIRECRAWL_API_KEY"),
        proxycurl_api_key=os.getenv("PROXYCURL_API_KEY"),
        rocketreach_api_key=os.getenv("ROCKETREACH_API_KEY"),
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY"),
        anthropic_model=os.getenv("ANTHROPIC_MODEL") or "claude-sonnet-4-5-20250929",
        gemini_api_key=os.getenv("GOOGLE_AI_API_KEY") or os.getenv("GEMINI_API_KEY"),
        gemini_model=os.getenv("GEMINI_MODEL") or "gemini-2.0-flash",
        groq_api_key=os.getenv("GROQ_API_KEY"),
        groq_model=os.getenv("GROQ_MODEL") or "llama-3.3-70b-versatile",
        mistral_api_key=os.getenv("MISTRAL_API_KEY"),
        mistral_model=os.getenv("MISTRAL_MODEL") or "mistral-medium-latest",
        cloudflare_api_token=os.getenv("CLOUDFLARE_API_TOKEN"),
        cloudflare_account_id=os.getenv("CLOUDFLARE_ACCOUNT_ID"),
        cloudflare_model=os.getenv("CLOUDFLARE_MODEL") or "@cf/meta/llama-3.1-8b-instruct",
        hubspot_access_token=_normalize_hubspot_token_env(os.getenv("HUBSPOT_ACCESS_TOKEN")),
        hubspot_contact_owner_id=os.getenv("HUBSPOT_CONTACT_OWNER_ID"),
        hubspot_lifecycle_stage=os.getenv("HUBSPOT_LIFECYCLE_STAGE") or "lead",
        hubspot_lead_status=os.getenv("HUBSPOT_LEAD_STATUS") or "",
        hubspot_person_linkedin_property=os.getenv("HUBSPOT_PROP_PERSON_LINKEDIN") or "",
        hubspot_company_linkedin_property=os.getenv("HUBSPOT_PROP_COMPANY_LINKEDIN") or "",
        apollo_webhook_url=os.getenv("APOLLO_WEBHOOK_URL"),
        apollo_phone_poll_timeout=float(os.getenv("APOLLO_PHONE_POLL_TIMEOUT") or "120"),
        apollo_phone_poll_interval=float(os.getenv("APOLLO_PHONE_POLL_INTERVAL") or "5"),
    )


def _normalize_hubspot_token_env(raw: str | None) -> str | None:
    if not raw:
        return None
    token = raw.strip().strip('"').strip("'")
    if not token:
        return None
    if token.startswith("pat-"):
        return token
    if token.startswith(("na", "eu")) and "-" in token:
        return f"pat-{token}"
    return token


def resolve_default_people_sources() -> tuple[str, ...]:
    """Bing + configured paid sources (Serper, Apollo). Tavily is a separate fallback."""
    cfg = load_fallback_config()
    sources: list[str] = ["bing"]
    if cfg.serper_api_key:
        sources.append("serper")
    if cfg.apollo_api_key:
        sources.append("apollo")
    return tuple(sources)


def missing_enrichment_keys(cfg: FallbackConfig | None = None) -> list[str]:
    """Return env var names for recommended API keys that are not configured."""
    c = cfg or load_fallback_config()
    checks: tuple[tuple[str | None, str], ...] = (
        (c.serper_api_key, "SERPER_API_KEY"),
        (c.tavily_api_key, "TAVILY_API_KEY"),
        (c.apollo_api_key, "APOLLO_API_KEY"),
        (c.anthropic_api_key, "ANTHROPIC_API_KEY"),
        (c.firecrawl_api_key, "FIRECRAWL_API_KEY"),
    )
    return [label for value, label in checks if not value]


def available_llm_providers(cfg: FallbackConfig | None = None) -> list[str]:
    """Return ordered list of LLM provider names that have API keys configured."""
    c = cfg or load_fallback_config()
    providers = []
    if c.anthropic_api_key:
        providers.append("Anthropic")
    if c.gemini_api_key:
        providers.append("Gemini")
    if c.groq_api_key:
        providers.append("Groq")
    if c.mistral_api_key:
        providers.append("Mistral")
    if c.cloudflare_api_token and c.cloudflare_account_id:
        providers.append("Cloudflare")
    return providers


def log_recommended_stack_status(log: Callable[[str], None] = print) -> None:
    """Log the active discovery stack and warn about missing API keys."""
    log("--- Recommended discovery stack ---")
    log(
        "Company: Steps 1-3 (httpx + Playwright) -> fallbacks "
        f"{','.join(map(str, DEFAULT_FALLBACK_STEPS))} (team pages, Tavily, Apollo)"
    )
    log(
        "People: team pages -> Firecrawl -> Playwright -> Bing -> Serper -> "
        "Apollo -> Tavily -> Anthropic -> Apollo contact enrichment"
    )
    missing = missing_enrichment_keys()
    if missing:
        log(f"Missing API keys (fewer people/emails): {', '.join(missing)}")
    else:
        log("All recommended API keys are configured.")
