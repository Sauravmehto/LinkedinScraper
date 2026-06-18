# GTM Streamlit app — Playwright base image (Chromium pre-installed).
# Local:  docker compose up --build
# Render: runtime docker, dockerfilePath ./docker/streamlit.Dockerfile

FROM mcr.microsoft.com/playwright/python:v1.49.1-noble

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p data output

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

EXPOSE 8501

CMD ["sh", "-c", "streamlit run app/streamlit_app.py --server.port=${PORT:-8501} --server.address=0.0.0.0 --server.headless=true --browser.gatherUsageStats=false"]
