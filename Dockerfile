FROM docker-hub.artifactory.trusted.visa.com/python:3.12-slim

WORKDIR /app

COPY requirements.txt .
ARG PIP_INDEX_URL
RUN pip install --no-cache-dir \
    --trusted-host artifactory.trusted.visa.com \
    --index-url "${PIP_INDEX_URL}" \
    -r requirements.txt

COPY backend/ ./backend/
COPY frontend/ ./frontend/
COPY streamlit_app.py .

ENV PYTHONUNBUFFERED=1

EXPOSE 8501

CMD ["streamlit", "run", "streamlit_app.py", \
     "--server.port=8501", \
     "--server.address=0.0.0.0", \
     "--server.headless=true", \
     "--browser.gatherUsageStats=false"]
