"""Simple GTM report UI: upload Excel → run-gtm → download final report."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import streamlit as st

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "data"
INPUT_PATH = DATA_DIR / "Sample_file.xlsx"
REPORT_PATH = DATA_DIR / "GTM_Final_report.xlsx"
MAIN_SCRIPT = REPO_ROOT / "main.py"

st.set_page_config(page_title="GTM Report Generator", page_icon="📊", layout="centered")

st.title("GTM Report Generator")
st.caption("Upload your company list, run the pipeline, download the HubSpot report.")

if "running" not in st.session_state:
    st.session_state.running = False
if "last_log" not in st.session_state:
    st.session_state.last_log = ""
if "pipeline_ok" not in st.session_state:
    st.session_state.pipeline_ok = False


def _run_pipeline() -> tuple[bool, str]:
    cmd = [
        sys.executable,
        str(MAIN_SCRIPT),
        "run-gtm",
        "--input",
        str(INPUT_PATH),
    ]
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    root = str(REPO_ROOT)
    env["PYTHONPATH"] = root if not env.get("PYTHONPATH") else f"{root}{os.pathsep}{env['PYTHONPATH']}"

    proc = subprocess.Popen(
        cmd,
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
    log_text = "\n".join(lines)
    ok = proc.returncode == 0 and REPORT_PATH.exists()
    return ok, log_text


if "saved_file" not in st.session_state:
    st.session_state.saved_file = False


uploaded = st.file_uploader("Upload Excel file (.xlsx)", type=["xlsx"])

if uploaded is not None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    INPUT_PATH.write_bytes(uploaded.getvalue())
    st.session_state.saved_file = True
    st.success(f"Saved as `{INPUT_PATH.name}`")
elif INPUT_PATH.exists():
    st.session_state.saved_file = True

has_input = st.session_state.saved_file and INPUT_PATH.exists()

run_clicked = st.button(
    "Run Pipeline",
    type="primary",
    disabled=st.session_state.running or not has_input,
    use_container_width=True,
)

if run_clicked:
    if not INPUT_PATH.exists():
        st.error("Upload a file first.")
    else:
        st.session_state.running = True
        st.session_state.pipeline_ok = False
        with st.spinner("Running pipeline… this may take several minutes."):
            ok, log = _run_pipeline()
        st.session_state.running = False
        st.session_state.last_log = log
        st.session_state.pipeline_ok = ok
        if ok:
            st.success("Pipeline finished.")
        else:
            st.error("Pipeline failed. See log below.")
        st.rerun()

if st.session_state.last_log:
    with st.expander("Pipeline log", expanded=not st.session_state.pipeline_ok):
        st.code(st.session_state.last_log[-8000:], language=None)

if REPORT_PATH.exists():
    st.download_button(
        label="Download GTM_Final_report.xlsx",
        data=REPORT_PATH.read_bytes(),
        file_name="GTM_Final_report.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        type="primary",
        use_container_width=True,
    )
elif not st.session_state.running:
    st.info("Run the pipeline to generate the report.")

st.caption("Close Excel if `GTM_Final_report.xlsx` is open before running.")
