"""HubSpot CRM API v3 client (contacts + companies)."""

from __future__ import annotations

import time
from typing import Any
from urllib.parse import urlparse

import httpx

HUBSPOT_API_BASE = "https://api.hubapi.com"


def normalize_hubspot_token(raw: str) -> str:
    token = (raw or "").strip().strip('"').strip("'")
    if not token:
        return ""
    if token.startswith("pat-"):
        return token
    if token.startswith(("na", "eu")) and "-" in token and len(token) < 50:
        return f"pat-{token}"
    return token


def validate_crm_api_token(token: str) -> str | None:
    """
    HubSpot CRM REST API (api.hubapi.com/crm/v3) requires a Private App token (pat-na1-...).
    Developer Personal Access Keys (long base64-like strings) return 401
    'OAuth token expired 20605 days ago' — they are for HubSpot CLI only.
    """
    if not token:
        return "Missing HUBSPOT_ACCESS_TOKEN in .env"
    if not token.startswith("pat-"):
        return (
            "Invalid token type for CRM sync. Developer Personal Access Keys do NOT work "
            "with the Contacts/Companies API.\n"
            "Create a Private App: HubSpot → Settings → Integrations → Private Apps → "
            "Create app → Scopes: crm.objects.contacts.read/write, "
            "crm.objects.companies.read/write → copy token starting with pat-na2- (or pat-na1-)."
        )
    if len(token) < 40:
        return "HUBSPOT_ACCESS_TOKEN looks incomplete. Copy the full Private App / Service Key token (pat-na2-...)."
    return None


def _domain_from_url(website: str) -> str:
    raw = (website or "").strip()
    if not raw:
        return ""
    if not raw.startswith(("http://", "https://")):
        raw = "https://" + raw
    host = urlparse(raw).netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return host


class HubSpotClient:
    def __init__(
        self,
        access_token: str,
        *,
        timeout: float = 30.0,
        request_delay: float = 0.15,
    ) -> None:
        self._token = normalize_hubspot_token(access_token)
        self._timeout = timeout
        self._delay = request_delay
        self._headers = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }

    @property
    def configured(self) -> bool:
        return bool(self._token)

    def _sleep(self) -> None:
        if self._delay > 0:
            time.sleep(self._delay)

    def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict | None = None,
        params: dict | None = None,
    ) -> dict | Any:
        url = f"{HUBSPOT_API_BASE}{path}"
        with httpx.Client(timeout=self._timeout, headers=self._headers) as client:
            resp = client.request(method, url, json=json_body, params=params)
        self._sleep()
        if resp.status_code == 204:
            return {}
        try:
            data = resp.json()
        except ValueError:
            data = {"raw": resp.text}
        if resp.status_code >= 400:
            msg = data.get("message") if isinstance(data, dict) else resp.text
            raise HubSpotAPIError(resp.status_code, str(msg or resp.text), data)
        return data

    def search_contact_by_email(self, email: str) -> str | None:
        body = {
            "filterGroups": [
                {
                    "filters": [
                        {
                            "propertyName": "email",
                            "operator": "EQ",
                            "value": email.lower().strip(),
                        }
                    ]
                }
            ],
            "properties": ["email", "firstname", "lastname"],
            "limit": 1,
        }
        data = self._request("POST", "/crm/v3/objects/contacts/search", json_body=body)
        results = data.get("results") if isinstance(data, dict) else []
        if results and isinstance(results[0], dict):
            return str(results[0].get("id") or "") or None
        return None

    def create_contact(self, properties: dict[str, str]) -> str:
        data = self._request(
            "POST",
            "/crm/v3/objects/contacts",
            json_body={"properties": properties},
        )
        return str(data.get("id") or "")

    def update_contact(self, contact_id: str, properties: dict[str, str]) -> None:
        self._request(
            "PATCH",
            f"/crm/v3/objects/contacts/{contact_id}",
            json_body={"properties": properties},
        )

    def search_company_by_domain(self, domain: str) -> str | None:
        if not domain:
            return None
        body = {
            "filterGroups": [
                {
                    "filters": [
                        {
                            "propertyName": "domain",
                            "operator": "EQ",
                            "value": domain.lower(),
                        }
                    ]
                }
            ],
            "properties": ["name", "domain"],
            "limit": 1,
        }
        data = self._request("POST", "/crm/v3/objects/companies/search", json_body=body)
        results = data.get("results") if isinstance(data, dict) else []
        if results and isinstance(results[0], dict):
            return str(results[0].get("id") or "") or None
        return None

    def search_company_by_name(self, name: str) -> str | None:
        body = {
            "filterGroups": [
                {
                    "filters": [
                        {
                            "propertyName": "name",
                            "operator": "EQ",
                            "value": name.strip(),
                        }
                    ]
                }
            ],
            "properties": ["name"],
            "limit": 1,
        }
        data = self._request("POST", "/crm/v3/objects/companies/search", json_body=body)
        results = data.get("results") if isinstance(data, dict) else []
        if results and isinstance(results[0], dict):
            return str(results[0].get("id") or "") or None
        return None

    def create_company(self, properties: dict[str, str]) -> str:
        data = self._request(
            "POST",
            "/crm/v3/objects/companies",
            json_body={"properties": properties},
        )
        return str(data.get("id") or "")

    def update_company(self, company_id: str, properties: dict[str, str]) -> None:
        self._request(
            "PATCH",
            f"/crm/v3/objects/companies/{company_id}",
            json_body={"properties": properties},
        )

    def associate_contact_company(self, contact_id: str, company_id: str) -> None:
        self._request(
            "PUT",
            f"/crm/v4/objects/contacts/{contact_id}/associations/companies/{company_id}",
            json_body=[
                {
                    "associationCategory": "HUBSPOT_DEFINED",
                    "associationTypeId": 1,
                }
            ],
        )

    def create_note_for_contact(self, contact_id: str, body: str) -> None:
        if not body.strip():
            return
        note = self._request(
            "POST",
            "/crm/v3/objects/notes",
            json_body={
                "properties": {
                    "hs_timestamp": str(int(time.time() * 1000)),
                    "hs_note_body": body.strip()[:65536],
                }
            },
        )
        note_id = str(note.get("id") or "")
        if not note_id:
            return
        self._request(
            "PUT",
            f"/crm/v4/objects/notes/{note_id}/associations/contacts/{contact_id}",
            json_body=[
                {
                    "associationCategory": "HUBSPOT_DEFINED",
                    "associationTypeId": 202,
                }
            ],
        )


class HubSpotAPIError(Exception):
    def __init__(self, status: int, message: str, payload: Any = None) -> None:
        super().__init__(f"HubSpot API {status}: {message}")
        self.status = status
        self.payload = payload


def domain_from_website(website: str) -> str:
    return _domain_from_url(website)
