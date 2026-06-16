"""Search query generation for decision-maker discovery."""

from __future__ import annotations

from .types import RoleTarget


def company_variants(company_name: str) -> list[str]:
    base = (company_name or "").strip()
    if not base:
        return []
    variants = {base}
    simplified = (
        base.replace("Inc.", "")
        .replace("LLC", "")
        .replace("Ltd.", "")
        .replace("Limited", "")
        .strip()
    )
    if simplified:
        variants.add(simplified)
    return [v for v in variants if v]


def dedupe_queries(queries: list[str], max_count: int = 0) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for q in queries:
        key = q.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(q.strip())
        if max_count > 0 and len(out) >= max_count:
            break
    return out


def build_role_queries(company_name: str, role_target: RoleTarget) -> list[str]:
    variants = company_variants(company_name) or [company_name]
    role_clause = " OR ".join(f'"{r}"' for r in role_target.expanded_roles[:6])
    company_clause = " OR ".join(f'"{c}"' for c in variants[:2])
    return [
        f"site:linkedin.com/in/ ({company_clause}) ({role_clause})",
        f'site:linkedin.com/in/ "{variants[0]}" "{role_target.primary_role}"',
    ]


def build_named_queries(company_name: str, person_name: str, role_target: RoleTarget) -> list[str]:
    primary = role_target.primary_role
    return [
        f'site:linkedin.com/in/ "{person_name}" "{company_name}" "{primary}"',
        f'site:linkedin.com/in/ "{person_name}" "{company_name}"',
    ]


def build_priority_role_queries(
    company_name: str,
    role_targets: list[RoleTarget],
    *,
    max_roles: int = 3,
) -> list[str]:
    """Fewer, higher-value SERP queries for the free tier."""
    queries: list[str] = []
    roles = role_targets if max_roles <= 0 else role_targets[:max_roles]
    for role in roles:
        queries.extend(build_role_queries(company_name, role)[:1])
    return queries


def build_all_role_queries(company_name: str, role_targets: list[RoleTarget]) -> list[str]:
    """One primary SERP query per role bucket (max coverage mode)."""
    return build_priority_role_queries(company_name, role_targets, max_roles=0)


def build_tavily_people_queries(
    company_name: str,
    role_targets: list[RoleTarget],
    *,
    max_roles: int = 5,
) -> list[str]:
    """Natural-language queries optimized for Tavily people search."""
    variants = company_variants(company_name) or [company_name]
    company = variants[0]
    queries: list[str] = []
    roles = role_targets if max_roles <= 0 else role_targets[:max_roles]
    for role in roles:
        queries.append(f'{company} {role.primary_role} linkedin profile site:linkedin.com/in')
        if role.expanded_roles:
            alt = role.expanded_roles[1] if len(role.expanded_roles) > 1 else role.expanded_roles[0]
            queries.append(f'{company} "{alt}" linkedin')
    return queries
