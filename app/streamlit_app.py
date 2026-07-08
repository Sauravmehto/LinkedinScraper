"""GTM Report Generator — upload Excel/CSV → run pipeline → download report."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import time
from collections.abc import Callable
from io import BytesIO
from pathlib import Path

import pandas as pd
import streamlit as st

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "data"
OUTPUT_DIR = REPO_ROOT / "output"
SAMPLE_PATH = DATA_DIR / "Sample_file.xlsx"
INPUT_PATH = DATA_DIR / "user_input.xlsx"
FINAL_REPORT_PATH = OUTPUT_DIR / "final_report.xlsx"
LEGACY_REPORT_PATH = DATA_DIR / "GTM_Final_report.xlsx"
MAIN_SCRIPT = REPO_ROOT / "main.py"
LOG_TAIL_CHARS = 12_000
DEBUG_LOG_PATH = REPO_ROOT / "output" / "debug-5e088b.log"
DEBUG_SESSION_ID = "5e088b"
MAX_SAMPLE_COMPANIES = 5
CACHE_DIR = REPO_ROOT / "output" / "cache" / "people"

st.set_page_config(page_title="GTM Report Generator", page_icon="📊", layout="wide")

st.markdown(
    """
    <style>
    /* Compact layout for non-technical users */
    .stMainBlockContainer,
    .block-container,
    .st-emotion-cache-1w723zb {
        padding-top: 0.75rem !important;
        padding-right: 0.75rem !important;
        padding-bottom: 0.75rem !important;
        padding-left: 0.75rem !important;
        max-width: none !important;
    }

    div[data-testid="stVerticalBlock"] > div {
        gap: 0.5rem !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ── session state defaults ────────────────────────────────────────────────────
for _k, _v in {
    "running": False,
    "last_log": "",
    "pipeline_ok": False,
    "file_uploaded": False,
    "last_upload_sig": "",
    "uploaded_filename": "",
    "report_path": "",
    "report_download_name": "",
    "report_key": "",
    "report_row_count": 0,
}.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v


def _upload_sig(name: str, data: bytes) -> str:
    digest = hashlib.sha256(data).hexdigest()[:16]
    return f"{name}:{len(data)}:{digest}"


def _report_path_for_upload(filename: str) -> Path:
    return FINAL_REPORT_PATH


def _report_download_name_for_upload(filename: str) -> str:
    stem = Path(filename).stem or "report"
    safe = re.sub(r'[<>:"/\\|?*]', "_", stem).strip() or "report"
    return f"{safe}_final_report.xlsx"


def _debug_log(
    *,
    hypothesis_id: str,
    location: str,
    message: str,
    data: dict,
    run_id: str = "pre-fix",
) -> None:
    payload = {
        "sessionId": DEBUG_SESSION_ID,
        "runId": run_id,
        "hypothesisId": hypothesis_id,
        "location": location,
        "message": message,
        "data": data,
        "timestamp": int(time.time() * 1000),
    }
    try:
        with DEBUG_LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=True) + "\n")
    except Exception:
        pass


def _current_report_path() -> Path | None:
    raw = st.session_state.get("report_path") or ""
    return Path(raw) if raw else None


def _delete_report(path: Path | None = None) -> None:
    targets = {LEGACY_REPORT_PATH, FINAL_REPORT_PATH}
    if path is not None:
        targets.add(path)
    current = _current_report_path()
    if current is not None:
        targets.add(current)
    for target in targets:
        if target.exists():
            try:
                target.unlink()
            except OSError:
                pass


def _reset() -> None:
    st.session_state.pipeline_ok = False
    st.session_state.last_log = ""
    st.session_state.report_key = ""
    st.session_state.report_row_count = 0
    _delete_report()


def _clear_people_cache() -> int:
    if not CACHE_DIR.exists():
        return 0
    removed = 0
    for path in CACHE_DIR.rglob("*"):
        if path.is_file():
            try:
                path.unlink()
                removed += 1
            except OSError:
                pass
    return removed


def _save(uploaded) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if uploaded.name.lower().endswith(".csv"):
        df = pd.read_csv(BytesIO(uploaded.getvalue()), encoding="utf-8")
        df.to_excel(INPUT_PATH, index=False, sheet_name="Sheet1")
    else:
        INPUT_PATH.write_bytes(uploaded.getvalue())


def _company_count_from_upload(raw: bytes, filename: str) -> int:
    if filename.lower().endswith(".csv"):
        df = pd.read_csv(BytesIO(raw), encoding="utf-8")
    else:
        df = pd.read_excel(BytesIO(raw))
    if df.empty:
        return 0
    cols = {str(c).strip().casefold(): c for c in df.columns}
    if "company name" in cols:
        col = cols["company name"]
    else:
        col = df.columns[0]
    return int(df[col].astype(str).str.strip().ne("").sum())


def _report_row_count(path: Path) -> int:
    try:
        df = pd.read_excel(path)
        if df.empty:
            return 0
        return int(df.dropna(how="all").shape[0])
    except Exception:
        return 0


def _apollo_found_no_emails(log: str) -> bool:
    return bool(re.search(r"Contact enrichment done:\s*work_email=0\b", log))


def _tail_log(text: str) -> str:
    if len(text) <= LOG_TAIL_CHARS:
        return text
    return "…\n" + text[-LOG_TAIL_CHARS:]


def _run_pipeline(
    report_path: Path,
    *,
    on_log_update: Callable[[str], None] | None = None,
) -> tuple[bool, str, int]:
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    root = str(REPO_ROOT)
    env["PYTHONPATH"] = root if not env.get("PYTHONPATH") else f"{root}{os.pathsep}{env['PYTHONPATH']}"
    playwright_ver = ""
    try:
        import importlib.metadata as _md

        playwright_ver = _md.version("playwright")
    except Exception:
        playwright_ver = "unknown"
    pw_path = env.get("PLAYWRIGHT_BROWSERS_PATH", "")
    pw_entries: list[str] = []
    if pw_path and Path(pw_path).exists():
        pw_entries = sorted([p.name for p in Path(pw_path).glob("chromium*")])[:8]
    # region agent log
    _debug_log(
        hypothesis_id="H1_H2",
        location="app/streamlit_app.py:_run_pipeline:start",
        message="Pipeline subprocess starting",
        data={
            "python": sys.version.split()[0],
            "playwright_version": playwright_ver,
            "playwright_browsers_path": pw_path,
            "playwright_path_exists": bool(pw_path and Path(pw_path).exists()),
            "chromium_entries": pw_entries,
            "report_path": str(report_path),
        },
    )
    # endregion
    proc = subprocess.Popen(
        [
            sys.executable,
            str(MAIN_SCRIPT),
            "run-gtm",
            "--input",
            str(INPUT_PATH),
            "--final-report-output",
            str(FINAL_REPORT_PATH),
            "--no-final-report-require-email",
            "--refresh-cache",
            "--people-sources", "bing,serper,apollo,tavily",
        ],
        cwd=REPO_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    lines: list[str] = []
    assert proc.stdout is not None
    for line in proc.stdout:
        lines.append(line.rstrip("\n"))
        if "BrowserType.launch:" in line or "Looks like Playwright was just updated" in line:
            # region agent log
            _debug_log(
                hypothesis_id="H3",
                location="app/streamlit_app.py:_run_pipeline:stdout",
                message="Playwright launch error observed in pipeline output",
                data={"line": line.rstrip("\n")},
            )
            # endregion
        if on_log_update:
            on_log_update(_tail_log("\n".join(lines)))
    proc.wait()
    log = "\n".join(lines)
    row_count = _report_row_count(report_path) if report_path.exists() else 0
    ok = proc.returncode == 0 and report_path.exists() and row_count > 0
    # region agent log
    _debug_log(
        hypothesis_id="H1_H3",
        location="app/streamlit_app.py:_run_pipeline:end",
        message="Pipeline subprocess finished",
        data={
            "returncode": proc.returncode,
            "report_exists": report_path.exists(),
            "row_count": row_count,
            "ok": ok,
        },
    )
    # endregion
    return ok, log, row_count


# ── UI ────────────────────────────────────────────────────────────────────────

st.title("GTM Contact Builder")
st.caption(
    "Upload company websites and generate a HubSpot-ready decision-maker list with titles and LinkedIn data."
)

hero_a, hero_b, hero_c = st.columns(3)
hero_a.info("**Input**\n\nCompany list (`.xlsx` / `.csv`)")
hero_b.info("**Output**\n\nHubSpot import file (`final_report.xlsx`)")
hero_c.info("**Typical Runtime**\n\n~5 to 15 minutes")

if st.session_state.running:
    st.warning("Status: Generating contacts... please keep this tab open.")
elif st.session_state.pipeline_ok and st.session_state.report_row_count > 0:
    st.success(f"Status: Report ready ({st.session_state.report_row_count} contacts).")
elif st.session_state.file_uploaded:
    st.info("Status: File uploaded. Click **Generate My Contact List** to start.")
else:
    st.info("Status: Waiting for file upload.")

left_col, right_col = st.columns([2, 1], gap="small")

with right_col:
    st.subheader("How GTM Works")
    st.markdown(
        "- Finds company LinkedIn pages from your website list\n"
        "- Discovers decision-makers from search + team pages\n"
        "- Enriches contacts and cleans titles\n"
        "- Exports in HubSpot import format"
    )
    st.subheader("Required Columns")
    st.markdown(
        "- `Company Name`\n"
        "- `Official Website`\n"
        "- Optional: `Company_LinkedIn_URL`"
    )
    st.caption("Upload limit in UI: up to 5 companies per run.")

    st.subheader("Common Notes")
    st.markdown(
        "- Not every contact will have email/phone\n"
        "- Data quality depends on source/API availability\n"
        "- You can open **Technical Log** only if needed"
    )

with left_col:
    st.subheader("1) Upload Company File")
    dl_col, _ = st.columns([1, 1], gap="small")
    with dl_col:
        if SAMPLE_PATH.exists():
            st.download_button(
                "Download Sample File",
                data=SAMPLE_PATH.read_bytes(),
                file_name="Sample_file.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )
        else:
            st.warning("Sample file not found (`data/Sample_file.xlsx`).")

    st.caption(
        "Accepted: `.xlsx` or `.csv` (UTF-8) | Required: `Official Website` | "
        "Optional: `Company_LinkedIn_URL`"
    )

    uploaded = st.file_uploader(
        "Upload company file",
        type=["xlsx", "csv"],
        label_visibility="collapsed",
        disabled=st.session_state.running,
    )

    if uploaded is not None:
        raw = uploaded.getvalue()
        sig = _upload_sig(uploaded.name, raw)
        company_rows = -1
        try:
            company_rows = _company_count_from_upload(raw, uploaded.name)
        except Exception:
            company_rows = -1
        # region agent log
        _debug_log(
            hypothesis_id="H4",
            location="app/streamlit_app.py:upload",
            message="Upload received",
            data={
                "filename": uploaded.name,
                "size": uploaded.size,
                "company_rows": company_rows,
                "over_limit_5": company_rows > 5,
            },
        )
        # endregion
        if sig != st.session_state.last_upload_sig:
            try:
                _reset()
                if company_rows > MAX_SAMPLE_COMPANIES:
                    st.error(
                        f"This UI supports up to {MAX_SAMPLE_COMPANIES} companies per run. "
                        f"Found: {company_rows}. Please upload 5 or fewer."
                    )
                    st.session_state.file_uploaded = False
                    st.session_state.last_upload_sig = ""
                    st.session_state.uploaded_filename = ""
                    st.session_state.report_path = ""
                    st.session_state.report_download_name = ""
                    st.stop()
                removed_cache = _clear_people_cache()
                # region agent log
                _debug_log(
                    hypothesis_id="H2",
                    location="app/streamlit_app.py:upload:cache_clear",
                    message="Cleared people cache on new upload",
                    data={"removed_files": removed_cache, "cache_dir": str(CACHE_DIR)},
                )
                # endregion
                _save(uploaded)
                report_path = _report_path_for_upload(uploaded.name)
                st.session_state.file_uploaded = True
                st.session_state.last_upload_sig = sig
                st.session_state.uploaded_filename = uploaded.name
                st.session_state.report_path = str(report_path)
                st.session_state.report_download_name = _report_download_name_for_upload(uploaded.name)
            except Exception as exc:
                st.error(f"Could not read file: {exc}")
                st.session_state.file_uploaded = False
        if st.session_state.file_uploaded:
            out_name = st.session_state.report_download_name or _report_download_name_for_upload(uploaded.name)
            st.success(
                f"File ready: **{uploaded.name}** | Output will be **{out_name}** "
                "(saved as `output/final_report.xlsx`)."
            )
            try:
                from gtm.linkedin_scraper.validators.input_upload import validate_workbook as _validate_wb

                _val_results = _validate_wb(INPUT_PATH, log=lambda _: None)
                _any_warn = any(r.has_warnings for r in _val_results)
                if _any_warn:
                    with st.expander("Input checks (warnings)", expanded=True):
                        for rv in _val_results:
                            if not rv.has_warnings:
                                continue
                            col_a, col_b, col_c = st.columns([2, 3, 3])
                            col_a.write(f"**Row {rv.row_num}** {rv.company_name}")
                            col_b.write(rv.website_warning or "OK")
                            col_c.write(rv.linkedin_warning or "OK")
                            if rv.linkedin_corrected_to:
                                col_c.caption(f"Will use: {rv.linkedin_corrected_to}")
                else:
                    st.caption("Input checks passed: URLs look good.")
            except Exception:
                pass
    else:
        if st.session_state.last_upload_sig:
            st.session_state.file_uploaded = False
            st.session_state.last_upload_sig = ""
            st.session_state.uploaded_filename = ""
            st.session_state.report_path = ""
            st.session_state.report_download_name = ""
            _reset()

    st.subheader("2) Check API Readiness")
    if not st.session_state.file_uploaded:
        st.info("Upload a file first to continue.")
    else:
        try:
            from gtm.linkedin_scraper.config import (
                available_llm_providers,
                load_fallback_config,
                missing_enrichment_keys,
            )

            _cfg = load_fallback_config()
            _missing_keys = missing_enrichment_keys(_cfg)
            _llm_providers = available_llm_providers(_cfg)

            with st.expander("Pre-flight checklist", expanded=not _llm_providers):
                def _status_icon(ok: bool) -> str:
                    return "✅" if ok else "⚠️"

                _checks = [
                    ("Apollo (emails/phones)", bool(_cfg.apollo_api_key)),
                    ("Serper (people discovery)", bool(_cfg.serper_api_key)),
                    ("Tavily (people/company fallback)", bool(_cfg.tavily_api_key)),
                    ("Firecrawl (team pages)", bool(_cfg.firecrawl_api_key)),
                    ("Anthropic Claude", bool(_cfg.anthropic_api_key)),
                    ("Gemini (LLM fallback)", bool(_cfg.gemini_api_key)),
                    ("Groq (LLM fallback)", bool(_cfg.groq_api_key)),
                    ("Mistral (LLM fallback)", bool(_cfg.mistral_api_key)),
                    (
                        "Cloudflare AI (LLM fallback)",
                        bool(_cfg.cloudflare_api_token and _cfg.cloudflare_account_id),
                    ),
                ]

                _col1, _col2, _col3 = st.columns(3)
                for _i, (_label, _ok) in enumerate(_checks):
                    _col = [_col1, _col2, _col3][_i % 3]
                    _col.write(f"{_status_icon(_ok)} {_label}")

                if _llm_providers:
                    st.caption(f"LLM chain active: {' -> '.join(_llm_providers)}")
                else:
                    st.warning(
                        "No LLM keys configured. Final report will use deterministic mapping."
                    )

                if _missing_keys:
                    st.caption(
                        "Missing recommended keys: "
                        + ", ".join(_missing_keys)
                        + " (still works, but with weaker coverage)."
                    )

        except Exception:
            pass

    st.subheader("3) Generate Contacts")
    run_clicked = st.button(
        "Generate My Contact List",
        type="primary",
        disabled=not st.session_state.file_uploaded or st.session_state.running,
        use_container_width=True,
    )

    if run_clicked:
        report_path = _current_report_path()
        if report_path is None:
            st.error("No report path set. Please upload your file again.")
        else:
            _delete_report(report_path)
            st.session_state.pipeline_ok = False
            st.session_state.report_key = ""
            st.session_state.report_row_count = 0
            st.session_state.running = True
            st.session_state.last_log = ""

            st.markdown("**Run Progress**")
            log_placeholder = st.empty()
            log_placeholder.code("Starting pipeline...\n", language=None)

            def _push_log(text: str) -> None:
                log_placeholder.code(text or "Starting pipeline...\n", language=None)

            with st.status("Generating contacts... this may take 5 to 15 minutes.", expanded=True):
                ok, log, row_count = _run_pipeline(report_path, on_log_update=_push_log)

            st.session_state.running = False
            st.session_state.last_log = log
            st.session_state.report_row_count = row_count
            st.session_state.pipeline_ok = ok
            if ok and report_path.exists():
                st.session_state.report_key = str(report_path.stat().st_mtime_ns)
            st.session_state._show_apollo_warning = _apollo_found_no_emails(log)
            st.rerun()

    if st.session_state.last_log and not st.session_state.pipeline_ok:
        if st.session_state.get("_show_apollo_warning"):
            st.warning(
                "Apollo found no work emails. Report may include contacts without email."
            )
        if (
            st.session_state.report_row_count == 0
            and "=== full-intel complete ===" in st.session_state.last_log
        ):
            st.error("Pipeline finished but report has 0 contacts. Check Technical Log.")
        else:
            st.error("Pipeline failed or produced no report.")

    if st.session_state.pipeline_ok:
        report_path = _current_report_path()
        download_name = st.session_state.report_download_name or "Final_report.xlsx"
        if report_path and report_path.exists() and st.session_state.report_key:
            st.success(
                f"Done! **{st.session_state.report_row_count}** contacts are ready in **{download_name}**."
            )
            if st.session_state.get("_show_apollo_warning"):
                st.warning(
                    "Apollo returned no work emails in this run. Contacts are still included."
                )

    # Step 4 — download
    report_path = _current_report_path()
    if (
        st.session_state.pipeline_ok
        and report_path is not None
        and report_path.exists()
        and st.session_state.report_key
        and st.session_state.report_row_count > 0
    ):
        download_name = st.session_state.report_download_name or report_path.name
        st.subheader("4) Download HubSpot File")
        st.caption(f"{st.session_state.report_row_count} contacts in this file.")
        st.download_button(
            "Download HubSpot Report (.xlsx)",
            data=report_path.read_bytes(),
            file_name=download_name,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary",
            use_container_width=True,
            key=f"report_download_{st.session_state.report_key}",
        )

    if st.session_state.last_log:
        with st.expander("Technical Log (for debugging only)", expanded=False):
            st.code(_tail_log(st.session_state.last_log), language=None)
