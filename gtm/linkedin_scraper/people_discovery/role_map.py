"""Role maps and role expansion engine by company type."""

from __future__ import annotations

from .types import CompanyType, RoleTarget

ROLE_MAP_BY_TYPE: dict[CompanyType, list[str]] = {
    "PE": ["Managing Director", "Operating Partner", "Portfolio Operations", "CFO", "COO"],
    "REIT": ["CFO", "Asset Manager", "Fund Manager", "Investor Relations", "Acquisitions Director"],
    "HEDGE_FUND": ["CIO", "Portfolio Manager", "Risk Manager", "COO", "CFO"],
    "VC": ["Partner", "Managing Director", "Principal", "CFO", "COO"],
    "FAMILY_OFFICE": ["CIO", "COO", "CFO", "Investment Director", "Portfolio Manager"],
    "UNKNOWN": ["CFO", "COO", "Managing Director", "Partner", "Investor Relations"],
}

MAX_COVERAGE_ROLES: list[str] = [
    "Managing Director",
    "Partner",
    "CIO",
    "CFO",
    "CTO",
    "COO",
    "Investor Relations",
    "Fund Accounting",
    "Portfolio Operations",
    "Technology and Data",
    "Principal",
    "Director",
    "Operating Partner",
    "Portfolio Manager",
    "Investment Director",
]

ROLE_VARIATIONS: dict[str, list[str]] = {
    "CFO": [
        "CFO",
        "Chief Financial Officer",
        "Finance Director",
        "Head of Finance",
        "Controller",
        "Treasurer",
        "Principal Accounting Officer",
    ],
    "COO": [
        "COO",
        "Chief Operating Officer",
        "Operating Partner",
        "Head of Operations",
        "Operations Director",
    ],
    "CIO": [
        "CIO",
        "Chief Investment Officer",
        "Investment Director",
        "Head of Investment",
        "Investment Technology",
    ],
    "CTO": ["CTO", "Chief Technology Officer", "Head of Engineering", "Technology Director"],
    "Investor Relations": [
        "Investor Relations",
        "Head of IR",
        "Investor Relations Director",
        "IR Manager",
    ],
    "Portfolio Operations": [
        "Portfolio Operations",
        "Value Creation",
        "Portfolio Management",
        "Operations Director",
    ],
    "Fund Accounting": [
        "Fund Accounting",
        "Fund Accountant",
        "Accounting Director",
        "Head of Fund Accounting",
    ],
    "Technology and Data": [
        "Head of Data",
        "Data Director",
        "Technology Director",
        "Investment Technology",
        "Chief Data Officer",
    ],
    "Managing Director": ["Managing Director", "MD", "Executive Director"],
    "Operating Partner": ["Operating Partner", "Partner, Operations", "Operations Partner"],
    "Partner": ["Partner", "General Partner", "Investment Partner"],
    "Principal": ["Principal", "Investment Principal"],
    "Director": ["Director", "Senior Director", "Director of Investments"],
    "Asset Manager": ["Asset Manager", "Head of Asset Management"],
    "Fund Manager": ["Fund Manager", "Portfolio Manager"],
    "Acquisitions Director": ["Acquisitions Director", "Head of Acquisitions"],
    "Portfolio Manager": ["Portfolio Manager", "PM"],
    "Risk Manager": ["Risk Manager", "Head of Risk"],
    "Investment Director": ["Investment Director", "Director, Investments"],
}


def expand_roles(company_type: CompanyType, *, max_coverage: bool = False) -> list[RoleTarget]:
    if max_coverage:
        role_names = list(dict.fromkeys(MAX_COVERAGE_ROLES + ROLE_MAP_BY_TYPE.get(company_type, [])))
    else:
        role_names = ROLE_MAP_BY_TYPE.get(company_type, ROLE_MAP_BY_TYPE["UNKNOWN"])

    targets: list[RoleTarget] = []
    for role in role_names:
        expanded = ROLE_VARIATIONS.get(role, [role])
        unique = list(dict.fromkeys(expanded))
        targets.append(RoleTarget(primary_role=role, expanded_roles=unique))
    return targets
