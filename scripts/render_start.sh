#!/usr/bin/env bash
# Render start script — installs Chromium without root, then launches Streamlit.
set -euo pipefail

export PLAYWRIGHT_BROWSERS_PATH="${PLAYWRIGHT_BROWSERS_PATH:-/opt/render/project/src/.playwright-browsers}"

if [ ! -d "$PLAYWRIGHT_BROWSERS_PATH" ] || [ -z "$(find "$PLAYWRIGHT_BROWSERS_PATH" -mindepth 1 -print -quit 2>/dev/null || true)" ]; then
  echo "Playwright browsers not found — installing chromium (no system deps)..."
  python -m playwright install chromium
fi

exec streamlit run app/streamlit_app.py \
  --server.port="${PORT}" \
  --server.address=0.0.0.0 \
  --server.headless=true \
  --browser.gatherUsageStats=false
