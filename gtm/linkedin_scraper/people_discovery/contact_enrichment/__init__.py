"""Phase 3: contact detail enrichment (email, phone)."""

from .orchestrator import EnrichmentStats, enrich_candidates
from .people_excel import (
    load_company_hq_phones,
    load_company_websites,
    read_people_workbook,
    write_people_workbook,
)

__all__ = [
    "EnrichmentStats",
    "enrich_candidates",
    "load_company_hq_phones",
    "load_company_websites",
    "read_people_workbook",
    "write_people_workbook",
]
