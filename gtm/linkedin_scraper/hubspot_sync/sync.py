"""Sync GTM Excel outputs to HubSpot CRM."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from gtm.linkedin_scraper.people_discovery.types import PersonCandidate

from .client import HubSpotAPIError, HubSpotClient, domain_from_website, validate_crm_api_token


def _auth_hint(status: int) -> str:
    if status == 401:
        return (
            "HubSpot auth failed (401). Use a Private App token (pat-na2-...) in .env — "
            "NOT a Developer Personal Access Key (those cause 'expired 20605 days' errors)."
        )
    return (
        "HubSpot forbidden (403). Add write scopes: crm.objects.contacts.write, "
        "crm.objects.companies.write (your Personal Access Key may be read-only)."
    )
from .loaders import load_companies_from_workbook, load_people_from_workbook
from .mapper import (
    company_properties,
    contact_import_note,
    contact_properties,
)


@dataclass
class HubSpotSyncStats:
    companies_created: int = 0
    companies_updated: int = 0
    companies_skipped: int = 0
    contacts_created: int = 0
    contacts_updated: int = 0
    contacts_skipped_no_email: int = 0
    contacts_skipped_error: int = 0
    associations: int = 0
    notes_created: int = 0
    errors: list[str] = field(default_factory=list)


def sync_to_hubspot(
    *,
    people_path: Path,
    companies_path: Path | None = None,
    access_token: str,
    dry_run: bool = False,
    limit: int = 0,
    lifecycle_stage: str = "lead",
    lead_status: str = "",
    owner_id: str = "",
    person_linkedin_property: str = "",
    company_linkedin_property: str = "",
    skip_notes: bool = False,
    request_delay: float = 0.15,
    timeout: float = 30.0,
    log: Callable[[str], None] | None = None,
) -> HubSpotSyncStats:
    _log = log or (lambda _m: None)
    stats = HubSpotSyncStats()
    client = HubSpotClient(access_token, timeout=timeout, request_delay=request_delay)

    if not client.configured:
        _log("HubSpot sync aborted: missing or invalid HUBSPOT_ACCESS_TOKEN")
        return stats

    token_error = validate_crm_api_token(client._token)
    if token_error:
        _log(token_error)
        return stats

    company_id_by_name: dict[str, str] = {}

    if companies_path and companies_path.exists():
        companies = load_companies_from_workbook(companies_path)
        _log(f"Companies to sync: {len(companies)}")
        for row in companies:
            props = company_properties(
                row,
                extra_props=(
                    {company_linkedin_property: row.company_linkedin}
                    if company_linkedin_property and row.company_linkedin
                    else None
                ),
            )
            domain = domain_from_website(row.website)
            if dry_run:
                _log(f"[dry-run] company: {row.name} ({domain or 'no domain'})")
                stats.companies_created += 1
                company_id_by_name[row.name.lower()] = f"dry-run-{row.name}"
                continue
            try:
                company_id = (
                    client.search_company_by_domain(domain)
                    if domain
                    else None
                ) or client.search_company_by_name(row.name)
                if company_id:
                    client.update_company(company_id, props)
                    stats.companies_updated += 1
                    _log(f"Updated company: {row.name} (id={company_id})")
                else:
                    company_id = client.create_company(props)
                    stats.companies_created += 1
                    _log(f"Created company: {row.name} (id={company_id})")
                if company_id:
                    company_id_by_name[row.name.lower()] = company_id
            except HubSpotAPIError as exc:
                stats.companies_skipped += 1
                stats.errors.append(f"Company {row.name}: {exc}")
                _log(f"Company error {row.name}: {exc}")
                if exc.status in (401, 403):
                    _log(_auth_hint(exc.status))
                    break
    else:
        _log("No companies file — contacts will use company name property only")

    people = load_people_from_workbook(people_path)
    if limit > 0:
        people = people[:limit]
    _log(f"Contacts to sync: {len(people)}")

    for candidate in people:
        email = (candidate.work_email or "").strip().lower()
        if not email or "@" not in email:
            stats.contacts_skipped_no_email += 1
            continue

        props = contact_properties(
            candidate,
            lifecycle_stage=lifecycle_stage,
            lead_status=lead_status,
            owner_id=owner_id,
            person_linkedin_prop=person_linkedin_property,
        )

        if dry_run:
            _log(f"[dry-run] contact: {email} | {candidate.person_name} @ {candidate.company_name}")
            stats.contacts_created += 1
            continue

        try:
            contact_id = client.search_contact_by_email(email)
            if contact_id:
                try:
                    client.update_contact(contact_id, props)
                except HubSpotAPIError as exc:
                    if person_linkedin_property and person_linkedin_property in str(exc):
                        props.pop(person_linkedin_property, None)
                        client.update_contact(contact_id, props)
                    else:
                        raise
                stats.contacts_updated += 1
                _log(f"Updated contact: {email} (id={contact_id})")
            else:
                try:
                    contact_id = client.create_contact(props)
                except HubSpotAPIError as exc:
                    if person_linkedin_property and person_linkedin_property in str(exc):
                        props.pop(person_linkedin_property, None)
                        contact_id = client.create_contact(props)
                    else:
                        raise
                stats.contacts_created += 1
                _log(f"Created contact: {email} (id={contact_id})")

            company_id = company_id_by_name.get((candidate.company_name or "").lower())
            if contact_id and company_id and not company_id.startswith("dry-run"):
                try:
                    client.associate_contact_company(contact_id, company_id)
                    stats.associations += 1
                except HubSpotAPIError as exc:
                    stats.errors.append(f"Associate {email}: {exc}")

            if contact_id and not skip_notes:
                try:
                    client.create_note_for_contact(contact_id, contact_import_note(candidate))
                    stats.notes_created += 1
                except HubSpotAPIError as exc:
                    stats.errors.append(f"Note {email}: {exc}")

        except HubSpotAPIError as exc:
            stats.contacts_skipped_error += 1
            stats.errors.append(f"Contact {email}: {exc}")
            _log(f"Contact error {email}: {exc}")
            if exc.status in (401, 403):
                _log(_auth_hint(exc.status))
                break

    _log(
        "HubSpot sync summary: "
        f"companies +{stats.companies_created} ~{stats.companies_updated} | "
        f"contacts +{stats.contacts_created} ~{stats.contacts_updated} | "
        f"skipped_no_email={stats.contacts_skipped_no_email} "
        f"errors={stats.contacts_skipped_error} associations={stats.associations}"
    )
    return stats
