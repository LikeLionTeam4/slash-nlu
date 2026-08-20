FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN addgroup --system slash \
    && adduser --system --ingroup slash --no-create-home slash

COPY requirements-runtime.txt ./
RUN python -m pip install --no-cache-dir -r requirements-runtime.txt

COPY main.py models.py analyzer.py intents.py summary.py ./
USER slash

EXPOSE 8001

HEALTHCHECK --interval=30s --timeout=3s --start-period=15s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8001/health', timeout=2).read()"]

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]
