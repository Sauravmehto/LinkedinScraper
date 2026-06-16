"""Data contracts for decision-maker discovery."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

CompanyType = Literal["PE", "REIT", "HEDGE_FUND", "VC", "FAMILY_OFFICE", "UNKNOWN"]
Confidence = Literal["HIGH", "MEDIUM", "LOW"]


@dataclass(frozen=True)
class CompanyContext:
    row_idx: int
    name: str
    website: str
    company_linkedin: str
    company_type: CompanyType


@dataclass(frozen=True)
class RoleTarget:
    primary_role: str
    expanded_roles: list[str]


@dataclass(frozen=True)
class PersonCandidate:
    company_name: str
    company_type: CompanyType
    company_linkedin: str
    role_target: str
    person_name: str
    person_title: str
    linkedin_in_url: str
    source: str
    snippet: str
    score: int
    confidence: Confidence
    notes: str = ""
    company_website: str = ""
    work_email: str = ""
    email_status: str = ""
    email_confidence: str = ""
    direct_dial: str = ""
    hq_phone: str = ""
    ir_email: str = ""
    ir_phone: str = ""
    phone_source: str = ""
    phone_status: str = ""
    city: str = ""
    state: str = ""
    country: str = ""


@dataclass(frozen=True)
class RawProfileHit:
    url: str
    source: str
    title: str = ""
    snippet: str = ""
    confidence_hint: float = 0.0
    person_name: str = ""
    email: str = ""
    direct_dial: str = ""
    hq_phone: str = ""
    phone_source: str = ""


@dataclass
class DiscoveryStats:
    companies_checked: int = 0
    companies_with_candidates: int = 0
    candidates_total: int = 0
    cache_hits: int = 0
    by_source: dict[str, int] = field(default_factory=dict)

    def bump_source(self, source: str) -> None:
        self.by_source[source] = self.by_source.get(source, 0) + 1
