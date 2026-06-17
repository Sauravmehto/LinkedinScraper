"""GTM Report Generator — upload Excel/CSV → run pipeline → download report."""

from __future__ import annotations

import hashlib
import os
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
REPORT_PATH = DATA_DIR / "GTM_Final_report.xlsx"
MAIN_SCRIPT = REPO_ROOT / "main.py"

st.set_page_config(page_title="GTM Report Generator", page_icon="📊", layout="centered")

# ── session state defaults ────────────────────────────────────────────────────
for _k, _v in {
    "running": False,
    "last_log": "",
    "pipeline_ok": False,
    "file_uploaded": False,   # True only when user uploads in this session
    "last_upload_sig": "",
    "report_key": "",  # changes after each successful run — busts download cache
}.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v


def _upload_sig(name: str, data: bytes) -> str:
    digest = hashlib.sha256(data).hexdigest()[:16]
    return f"{name}:{len(data)}:{digest}"


def _delete_report() -> None:
    if REPORT_PATH.exists():
        try:
            REPORT_PATH.unlink()
        except OSError:
            pass


def _reset() -> None:
    st.session_state.pipeline_ok = False
    st.session_state.last_log = ""
    st.session_state.report_key = ""
    _delete_report()


def _save(uploaded) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if uploaded.name.lower().endswith(".csv"):
        df = pd.read_csv(BytesIO(uploaded.getvalue()), encoding="utf-8")
        df.to_excel(INPUT_PATH, index=False, sheet_name="Sheet1")
    else:
        INPUT_PATH.write_bytes(uploaded.getvalue())


def _run_pipeline() -> tuple[bool, str]:
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    root = str(REPO_ROOT)
    env["PYTHONPATH"] = root if not env.get("PYTHONPATH") else f"{root}{os.pathsep}{env['PYTHONPATH']}"
    proc = subprocess.Popen(
        [sys.executable, str(MAIN_SCRIPT), "run-gtm", "--input", str(INPUT_PATH)],
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
    return proc.returncode == 0 and REPORT_PATH.exists(), "\n".join(lines)


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
            st.session_state.file_uploaded = True
            st.session_state.last_upload_sig = sig
        except Exception as exc:
            st.error(f"Could not read file: {exc}")
            st.session_state.file_uploaded = False
    if st.session_state.file_uploaded:
        st.success(f"File ready: **{uploaded.name}**")
else:
    # User cleared the uploader — disable Run Pipeline again
    if st.session_state.last_upload_sig:
        st.session_state.file_uploaded = False
        st.session_state.last_upload_sig = ""
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
    _delete_report()
    st.session_state.pipeline_ok = False
    st.session_state.report_key = ""
    st.session_state.running = True
    with st.spinner("Running pipeline… this may take 5–15 minutes."):
        ok, log = _run_pipeline()
    st.session_state.running = False
    st.session_state.last_log = log
    st.session_state.pipeline_ok = ok
    if ok and REPORT_PATH.exists():
        st.session_state.report_key = str(REPORT_PATH.stat().st_mtime_ns)
    if ok:
        st.success("Pipeline finished. Download your report below.")
    else:
        st.error("Pipeline failed. See log below.")
    st.rerun()

if st.session_state.last_log:
    with st.expander("Pipeline log", expanded=not st.session_state.pipeline_ok):
        st.code(st.session_state.last_log[-8000:], language=None)

# Step 4 — download (only after successful run this session)
if st.session_state.pipeline_ok and REPORT_PATH.exists() and st.session_state.report_key:
    st.divider()
    st.subheader("Step 4 · Download your report")
    st.download_button(
        "Download GTM_Final_report.xlsx",
        data=REPORT_PATH.read_bytes(),
        file_name="GTM_Final_report.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        type="primary",
        use_container_width=True,
        key=f"report_download_{st.session_state.report_key}",
    )

st.caption("Tip: Close Excel if `GTM_Final_report.xlsx` is open before running.")
