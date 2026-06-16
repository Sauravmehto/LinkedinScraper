"""Build HubSpot CD-style final_report.xlsx from pipeline outputs."""

from .build import (
    DEFAULT_OUTPUT,
    DEFAULT_TEMPLATE,
    GTM_FINAL_REPORT_OUTPUT,
    GTM_FINAL_TEMPLATE,
    build_final_report,
    resolve_template_path,
)
from .merge import FinalReportStats

__all__ = [
    "DEFAULT_OUTPUT",
    "DEFAULT_TEMPLATE",
    "GTM_FINAL_REPORT_OUTPUT",
    "GTM_FINAL_TEMPLATE",
    "FinalReportStats",
    "build_final_report",
    "resolve_template_path",
]
