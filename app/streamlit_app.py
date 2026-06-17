"""GTM Report Generator — upload Excel/CSV → run pipeline → download report."""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
from io import BytesIO
from pathlib import Path

import pandas as pd
import streamlit as st

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "data"
SAMPLE_PATH = DATA_DIR / "Sample_file.xlsx"
INPUT_PATH = DATA_DIR / "user_input.xlsx"
LEGACY_REPORT_PATH = DATA_DIR / "GTM_Final_report.xlsx"
MAIN_SCRIPT = REPO_ROOT / "main.py"

st.set_page_config(page_title="GTM Report Generator", page_icon="📊", layout="centered")

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
    stem = Path(filename).stem or "report"
    safe = re.sub(r'[<>:"/\\|?*]', "_", stem).strip() or "report"
    return DATA_DIR / f"{safe}_Final_report.xlsx"


def _report_download_name_for_upload(filename: str) -> str:
    return _report_path_for_upload(filename).name


def _current_report_path() -> Path | None:
    raw = st.session_state.get("report_path") or ""
    return Path(raw) if raw else None


def _delete_report(path: Path | None = None) -> None:
    targets = {LEGACY_REPORT_PATH}
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


def _save(uploaded) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if uploaded.name.lower().endswith(".csv"):
        df = pd.read_csv(BytesIO(uploaded.getvalue()), encoding="utf-8")
        df.to_excel(INPUT_PATH, index=False, sheet_name="Sheet1")
    else:
        INPUT_PATH.write_bytes(uploaded.getvalue())


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


def _run_pipeline(report_path: Path) -> tuple[bool, str, int]:
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    root = str(REPO_ROOT)
    env["PYTHONPATH"] = root if not env.get("PYTHONPATH") else f"{root}{os.pathsep}{env['PYTHONPATH']}"
    proc = subprocess.Popen(
        [
            sys.executable,
            str(MAIN_SCRIPT),
            "run-gtm",
            "--input",
            str(INPUT_PATH),
            "--final-report-output",
            str(report_path),
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
    proc.wait()
    log = "\n".join(lines)
    row_count = _report_row_count(report_path) if report_path.exists() else 0
    ok = proc.returncode == 0 and report_path.exists() and row_count > 0
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
    if sig != st.session_state.last_upload_sig:
        try:
            _reset()
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
        st.success(f"File ready: **{uploaded.name}** → report will be saved as **{out_name}**")
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
        with st.spinner("Running pipeline… this may take 5–15 minutes."):
            ok, log, row_count = _run_pipeline(report_path)
        st.session_state.running = False
        st.session_state.last_log = log
        st.session_state.report_row_count = row_count
        st.session_state.pipeline_ok = ok
        if ok and report_path.exists():
            st.session_state.report_key = str(report_path.stat().st_mtime_ns)
        st.session_state._show_apollo_warning = _apollo_found_no_emails(log)
        st.rerun()

if st.session_state.last_log:
    with st.expander("Pipeline log", expanded=not st.session_state.pipeline_ok):
        st.code(st.session_state.last_log[-8000:], language=None)

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

st.caption("Tip: Close Excel if the report file is open before running.")
