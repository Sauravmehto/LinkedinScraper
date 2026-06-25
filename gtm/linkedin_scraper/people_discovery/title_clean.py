"""Rule-based and Claude-assisted job title cleaning for CRM export."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Callable

from gtm.linkedin_scraper.config import load_fallback_config
from gtm.linkedin_scraper.llm_fallback import llm_call_from_config
from gtm.linkedin_scraper.people_discovery.anthropic_enrich import DEFAULT_MODEL

from .types import PersonCandidate

UNKNOWN_TITLE = "UNKNOWN"

KNOWN_CERTS: tuple[str, ...] = (
    "CFA",
    "CAIA",
    "CPA",
    "CFP",
    "FRM",
    "MBA",
    "PMP",
    "CIMA",
    "CACM",
)

LINKEDIN_RE = re.compile(r"(\s*[-|]\s*LinkedIn\s*)|(\s*\|\s*LinkedIn\b)", re.I)
ELLIPSIS_TAIL = re.compile(r"\s*\.{3}.*$")
ROLE_KEYWORDS = re.compile(
    r"\b(?:"
    r"director|officer|president|vice\s+president|\bvp\b|svp|evp|manager|"
    r"ceo|cfo|cio|coo|cto|leader|head|partner|analyst|controller|"
    r"accountant|advisor|adviser|board\s+member|chief|portfolio|"
    r"acquisitions|capital\s+markets|alternative\s+investment"
    r")\b",
    re.I,
)
ORG_MARKERS = re.compile(
    r"\b(?:investment\s+management|management|capital|partners|holdings|"
    r"advisors|group|llc|inc\.?|corp\.?|company)\b",
    re.I,
)

TITLE_CLEAN_SYSTEM_PROMPT = """You are a data cleaning expert.

Task:
Clean the "Job Title" column and extract ONLY the person's designation/title.

Rules:
1. Remove the person's name.
2. Remove company names.
3. Remove website references such as "LinkedIn", "| LinkedIn", "- LinkedIn".
4. Remove ellipsis (...) and any truncated company text.
5. Keep professional certifications (CFA, CAIA, CPA, etc.) only if they are part of the title.
6. Return ONLY the final job title.
7. Do not include names, companies, or extra text.

If no clear job title exists and the text only contains a company name, return "UNKNOWN".

Return valid JSON only:
{"rows": [{"original": "<input>", "cleaned_job_title": "<cleaned title>"}]}
Never return explanations."""


@dataclass
class TitleCleanStats:
    candidates_in: int = 0
    cleaned: int = 0
    unknown: int = 0
    anthropic_calls: int = 0
    results: list[dict[str, str]] = field(default_factory=list)


def _collapse_ws(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def _remove_linkedin(text: str) -> str:
    cleaned = LINKEDIN_RE.sub("", text)
    return cleaned.strip(" -|")


def _strip_ellipsis(text: str) -> str:
    return ELLIPSIS_TAIL.sub("", (text or "").strip()).strip()


def _strip_leading_name(text: str, person_name: str) -> str:
    raw = (text or "").strip()
    name = (person_name or "").strip()
    if not raw or not name:
        return raw
    if raw.casefold().startswith(name.casefold()):
        return raw[len(name) :].lstrip(" ,-|").strip()
    first = name.split()[0] if name.split() else ""
    if first and len(first) > 2 and raw.casefold().startswith(first.casefold()):
        remainder = raw[len(first) :].lstrip(" ,-|").strip()
        if remainder and not remainder[0].islower():
            return remainder
    return raw


def _segment_is_name_only(segment: str, person_name: str) -> bool:
    seg = _collapse_ws(segment)
    name = _collapse_ws(person_name)
    if not seg or not name:
        return False
    if seg.casefold() == name.casefold():
        return True
    stripped = _strip_leading_name(seg, name)
    return not stripped


def _is_certificates_only(text: str) -> bool:
    temp = (text or "").strip()
    if not temp:
        return False
    for cert in KNOWN_CERTS:
        temp = re.sub(rf"\b{re.escape(cert)}\b", "", temp, flags=re.I)
    temp = re.sub(r"[,|\s\-]+", "", temp)
    return len(temp) == 0


def _normalize_cert_list(text: str) -> str:
    found: list[str] = []
    for cert in KNOWN_CERTS:
        if re.search(rf"\b{re.escape(cert)}\b", text or "", flags=re.I):
            found.append(cert)
    return ", ".join(dict.fromkeys(found))


def _company_tokens(company_name: str) -> set[str]:
    name = (company_name or "").strip()
    if not name:
        return set()
    tokens = {name.casefold()}
    for part in re.split(r"[\s,|/]+", name):
        part = part.strip()
        if len(part) > 3:
            tokens.add(part.casefold())
    return tokens


def _is_company_segment(segment: str, company_name: str) -> bool:
    seg = _strip_ellipsis(_collapse_ws(segment))
    if not seg:
        return True
    company_tokens = _company_tokens(company_name)
    seg_cf = seg.casefold()
    if company_tokens and any(token in seg_cf for token in company_tokens):
        return not ROLE_KEYWORDS.search(seg)
    if not ROLE_KEYWORDS.search(seg) and ORG_MARKERS.search(seg):
        return True
    return False


def _is_company_only(segment: str, company_name: str) -> bool:
    seg = _strip_ellipsis(_collapse_ws(segment))
    if not seg:
        return True
    return _is_company_segment(seg, company_name) and not ROLE_KEYWORDS.search(seg)


def _truncate_at_company(title_part: str, company_name: str) -> str:
    part = _strip_ellipsis(_collapse_ws(title_part))
    if not part:
        return ""
    company_tokens = _company_tokens(company_name)
    if "|" in part:
        pipe_parts = [p.strip() for p in part.split("|")]
        kept: list[str] = []
        for piece in pipe_parts:
            piece = _strip_ellipsis(piece)
            if not piece:
                continue
            if _is_company_segment(piece, company_name):
                break
            kept.append(piece)
        return " | ".join(kept).strip()
    if "," in part:
        comma_parts = [p.strip() for p in part.split(",")]
        kept = []
        for piece in comma_parts:
            piece = _strip_ellipsis(piece)
            if not piece:
                continue
            piece_cf = piece.casefold()
            if company_tokens and any(token in piece_cf for token in company_tokens):
                if not ROLE_KEYWORDS.search(piece):
                    break
            if _is_company_only(piece, company_name):
                break
            kept.append(piece)
        return ", ".join(kept).strip()
    if _is_company_only(part, company_name):
        return ""
    return part


def clean_job_title_deterministic(
    job_title: str,
    *,
    person_name: str = "",
    company_name: str = "",
) -> str:
    """Apply rule-based cleaning; return title or UNKNOWN."""
    original = _collapse_ws(job_title)
    if not original:
        return UNKNOWN_TITLE

    text = _remove_linkedin(original)
    text = _collapse_ws(text)
    if not text:
        return UNKNOWN_TITLE

    dash_parts = [_strip_ellipsis(p.strip()) for p in re.split(r"\s+-\s+", text)]
    dash_parts = [p for p in dash_parts if p]
    if not dash_parts:
        return UNKNOWN_TITLE

    first_raw = dash_parts[0]
    first = _strip_leading_name(first_raw, person_name)
    first = _strip_ellipsis(first)

    cert_prefix = ""
    role_segments: list[str]

    if _segment_is_name_only(first_raw, person_name):
        role_segments = dash_parts[1:]
        if _is_certificates_only(first):
            cert_prefix = _normalize_cert_list(first)
    elif _is_certificates_only(first):
        cert_prefix = _normalize_cert_list(first)
        role_segments = dash_parts[1:]
    elif first and not _is_company_only(first, company_name):
        if len(dash_parts) == 1:
            role_segments = [first]
        else:
            role_segments = dash_parts[1:]
            if ROLE_KEYWORDS.search(first):
                role_segments = [first] + role_segments
    else:
        role_segments = dash_parts[1:] if len(dash_parts) > 1 else []

    while role_segments and _is_company_segment(role_segments[-1], company_name):
        role_segments.pop()

    if not role_segments:
        if cert_prefix:
            return UNKNOWN_TITLE
        if first and not _is_company_only(first, company_name):
            body = _truncate_at_company(first, company_name)
            return body or UNKNOWN_TITLE
        return UNKNOWN_TITLE

    role_body = role_segments[0] if len(role_segments) == 1 else " - ".join(role_segments)
    role_body = _truncate_at_company(role_body, company_name)
    role_body = _collapse_ws(role_body)

    if not role_body or _is_company_only(role_body, company_name):
        return UNKNOWN_TITLE

    if cert_prefix:
        return f"{cert_prefix} - {role_body}"
    return role_body


def clean_job_title(
    job_title: str,
    *,
    person_name: str = "",
    company_name: str = "",
) -> dict[str, str]:
    """Return JSON-shaped result for one title."""
    original = (job_title or "").strip()
    cleaned = clean_job_title_deterministic(
        original,
        person_name=person_name,
        company_name=company_name,
    )
    return {"original": original, "cleaned_job_title": cleaned}


def _needs_anthropic_retry(cleaned: str, original: str) -> bool:
    if cleaned == UNKNOWN_TITLE:
        return bool(original.strip())
    if len(cleaned) > 100:
        return True
    if "linkedin" in cleaned.casefold():
        return True
    if "..." in cleaned:
        return True
    if original.count(" - ") >= 2 and cleaned.count(" - ") >= 2:
        return True
    return False


def _parse_title_clean_json(text: str) -> list[dict[str, str]]:
    text = (text or "").strip()
    if not text:
        return []
    if "```" in text:
        match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
        if match:
            text = match.group(1).strip()
    try:
        data = json.loads(text)
        if isinstance(data, dict) and isinstance(data.get("rows"), list):
            rows = data["rows"]
        elif isinstance(data, list):
            rows = data
        else:
            return []
        out: list[dict[str, str]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            original = str(row.get("original") or "").strip()
            cleaned = str(
                row.get("cleaned_job_title") or row.get("job_title") or ""
            ).strip()
            if original:
                out.append(
                    {
                        "original": original,
                        "cleaned_job_title": cleaned or UNKNOWN_TITLE,
                    }
                )
        return out
    except json.JSONDecodeError:
        return []


def clean_job_titles_with_llm(
    items: list[dict[str, str]],
    *,
    cfg,
    timeout: float = 45.0,
    batch_size: int = 30,
    log: Callable | None = None,
) -> dict[str, str]:
    """Batch-clean titles via LLM fallback chain; key = original title string."""
    _log = log or (lambda _m: None)
    if not items:
        return {}

    results: dict[str, str] = {}
    chunk_size = max(1, batch_size)

    for start in range(0, len(items), chunk_size):
        chunk = items[start : start + chunk_size]
        payload = {
            "job_titles": [
                {
                    "original": row.get("original", ""),
                    "person_name": row.get("person_name", ""),
                    "company_name": row.get("company_name", ""),
                }
                for row in chunk
            ]
        }
        text = llm_call_from_config(
            cfg,
            system=TITLE_CLEAN_SYSTEM_PROMPT,
            user_content=json.dumps(payload, ensure_ascii=False),
            max_tokens=4096,
            timeout=timeout,
            log=_log,
        )
        if not text:
            continue

        for row in _parse_title_clean_json(text):
            original = row["original"]
            cleaned = row.get("cleaned_job_title") or UNKNOWN_TITLE
            results[original] = cleaned

    return results


def clean_job_titles_with_anthropic(
    items: list[dict[str, str]],
    *,
    api_key: str,
    model: str = DEFAULT_MODEL,
    timeout: float = 45.0,
    batch_size: int = 30,
) -> dict[str, str]:
    """Backwards-compatible wrapper — delegates to the LLM fallback chain."""
    from gtm.linkedin_scraper.config import FallbackConfig

    cfg = FallbackConfig(
        brave_api_key=None,
        serper_api_key=None,
        tavily_api_key=None,
        apollo_api_key=None,
        anthropic_api_key=api_key,
        anthropic_model=model,
    )
    return clean_job_titles_with_llm(items, cfg=cfg, timeout=timeout, batch_size=batch_size)


def _with_title(candidate: PersonCandidate, title: str) -> PersonCandidate:
    cleaned = (title or "").strip() or UNKNOWN_TITLE
    return PersonCandidate(
        company_name=candidate.company_name,
        company_type=candidate.company_type,
        company_linkedin=candidate.company_linkedin,
        company_website=candidate.company_website,
        role_target=candidate.role_target,
        person_name=candidate.person_name,
        person_title=cleaned,
        linkedin_in_url=candidate.linkedin_in_url,
        source=candidate.source,
        snippet=candidate.snippet,
        score=candidate.score,
        confidence=candidate.confidence,
        notes=candidate.notes,
        work_email=candidate.work_email,
        personal_email=candidate.personal_email,
        email_status=candidate.email_status,
        email_confidence=candidate.email_confidence,
        direct_dial=candidate.direct_dial,
        hq_phone=candidate.hq_phone,
        ir_email=candidate.ir_email,
        ir_phone=candidate.ir_phone,
        phone_source=candidate.phone_source,
        phone_status=candidate.phone_status,
        city=candidate.city,
        state=candidate.state,
        country=candidate.country,
    )


def clean_candidates_job_titles(
    candidates: list[PersonCandidate],
    *,
    api_key: str | None = None,
    model: str | None = None,
    enable_anthropic: bool = True,
    timeout: float = 45.0,
    log: Callable[[str], None] | None = None,
) -> tuple[list[PersonCandidate], TitleCleanStats]:
    """Clean person_title on all candidates; optional LLM retry for hard rows."""
    _log = log or (lambda _msg: None)
    stats = TitleCleanStats(candidates_in=len(candidates))

    cfg = load_fallback_config()

    deterministic: list[dict[str, str]] = []
    retry_queue: list[dict[str, str]] = []

    for candidate in candidates:
        original = (candidate.person_title or "").strip()
        result = clean_job_title(
            original,
            person_name=candidate.person_name,
            company_name=candidate.company_name,
        )
        deterministic.append(result)
        if _needs_anthropic_retry(result["cleaned_job_title"], original):
            retry_queue.append(
                {
                    "original": original,
                    "person_name": candidate.person_name,
                    "company_name": candidate.company_name,
                }
            )

    llm_map: dict[str, str] = {}
    if enable_anthropic and retry_queue:
        llm_map = clean_job_titles_with_llm(
            retry_queue,
            cfg=cfg,
            timeout=timeout,
            log=_log,
        )
        stats.anthropic_calls = 1 if llm_map else 0

    out: list[PersonCandidate] = []
    for candidate, result in zip(candidates, deterministic, strict=True):
        original = result["original"]
        cleaned = llm_map.get(original) or result["cleaned_job_title"]
        if cleaned == UNKNOWN_TITLE:
            stats.unknown += 1
        elif cleaned != original:
            stats.cleaned += 1
        stats.results.append({"original": original, "cleaned_job_title": cleaned})
        out.append(_with_title(candidate, cleaned))

    _log(
        "Title clean: "
        f"in={stats.candidates_in} updated={stats.cleaned} "
        f"unknown={stats.unknown} anthropic_retry={len(retry_queue)}"
    )
    return out, stats
