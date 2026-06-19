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
    /* Remove Streamlit centered column cap (default max-width: 736px) */
    .stMainBlockContainer,
    .block-container,
    .st-emotion-cache-1w723zb {
        max-width: none !important;
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

st.title("GTM Report Generator")
st.caption("Upload your company list, run the pipeline, then download your HubSpot report.")

# Step 1 — sample download
st.subheader("Step 1 · Download sample file")
if SAMPLE_PATH.exists():
    st.download_button(
        "Download Sample_file.xlsx",
        data=SAMPLE_PATH.read_bytes(),
        file_name="Sample_file.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )
else:
    st.warning("Sample file not found (`data/Sample_file.xlsx`).")

st.divider()

# Step 2 — upload
st.subheader("Step 2 · Upload your company file")
st.caption("Accepted: .xlsx or .csv (UTF-8) · Required column: Official Website")

uploaded = st.file_uploader(
    "Choose file",
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
                    f"Sample upload supports up to {MAX_SAMPLE_COMPANIES} companies only. "
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
            f"File ready: **{uploaded.name}** → download as **{out_name}** "
            f"(pipeline writes `output/final_report.xlsx`)"
        )
else:
    if st.session_state.last_upload_sig:
        st.session_state.file_uploaded = False
        st.session_state.last_upload_sig = ""
        st.session_state.uploaded_filename = ""
        st.session_state.report_path = ""
        st.session_state.report_download_name = ""
        _reset()

st.divider()

# Step 3 — run pipeline
st.subheader("Step 3 · Run pipeline")
if not st.session_state.file_uploaded:
    st.info("Upload a company file above to enable **Run Pipeline**.")
else:
    try:
        from gtm.linkedin_scraper.config import load_fallback_config, missing_enrichment_keys

        _missing_keys = missing_enrichment_keys(load_fallback_config())
        if _missing_keys:
            st.warning(
                "Missing API keys (fewer people/emails): "
                + ", ".join(_missing_keys)
                + ". Add them in `.env` or Render Environment."
            )
    except Exception:
        pass

run_clicked = st.button(
    "Run Pipeline",
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

        st.markdown("**Pipeline log**")
        log_placeholder = st.empty()
        log_placeholder.code("Starting pipeline…\n", language=None)

        def _push_log(text: str) -> None:
            log_placeholder.code(text or "Starting pipeline…\n", language=None)

        with st.status("Running pipeline… this may take 5–15 minutes.", expanded=True):
            ok, log, row_count = _run_pipeline(report_path, on_log_update=_push_log)

        st.session_state.running = False
        st.session_state.last_log = log
        st.session_state.report_row_count = row_count
        st.session_state.pipeline_ok = ok
        if ok and report_path.exists():
            st.session_state.report_key = str(report_path.stat().st_mtime_ns)
        st.session_state._show_apollo_warning = _apollo_found_no_emails(log)
        st.rerun()

if st.session_state.last_log:
    st.markdown("**Pipeline log**")
    st.code(_tail_log(st.session_state.last_log), language=None)

if st.session_state.last_log and not st.session_state.pipeline_ok:
    if st.session_state.get("_show_apollo_warning"):
        st.warning(
            "Apollo found no work emails. Contacts are still included in the report "
            "when available. Verify **APOLLO_API_KEY** is set in Render Environment."
        )
    if st.session_state.report_row_count == 0 and "=== full-intel complete ===" in st.session_state.last_log:
        st.error(
            "Pipeline finished but the report has **0 contacts**. "
            "Check the pipeline log for details."
        )
    elif not st.session_state.pipeline_ok:
        st.error("Pipeline failed or produced no report. See log above.")

if st.session_state.pipeline_ok:
    report_path = _current_report_path()
    download_name = st.session_state.report_download_name or "Final_report.xlsx"
    if report_path and report_path.exists() and st.session_state.report_key:
        st.success(
            f"Pipeline finished. **{st.session_state.report_row_count}** contact(s) in "
            f"**{download_name}**."
        )
        if st.session_state.get("_show_apollo_warning"):
            st.warning(
                "Apollo found no work emails for this run. Report includes contacts "
                "without email. Verify **APOLLO_API_KEY** on Render for email enrichment."
            )

# Step 4 — download (only after successful run with data)
report_path = _current_report_path()
if (
    st.session_state.pipeline_ok
    and report_path is not None
    and report_path.exists()
    and st.session_state.report_key
    and st.session_state.report_row_count > 0
):
    download_name = st.session_state.report_download_name or report_path.name
    st.divider()
    st.subheader("Step 4 · Download your report")
    st.caption(f"{st.session_state.report_row_count} contact(s) in this file")
    st.download_button(
        f"Download {download_name}",
        data=report_path.read_bytes(),
        file_name=download_name,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        type="primary",
        use_container_width=True,
        key=f"report_download_{st.session_state.report_key}",
    )
