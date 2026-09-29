FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install --no-install-recommends -y ffmpeg \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 lura

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=lura:lura main.py endpoints.py jiosaavn_client.py ./
COPY --chown=lura:lura templates ./templates
COPY --chown=lura:lura static ./static

USER lura
EXPOSE 5100

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "from urllib.request import urlopen; urlopen('http://127.0.0.1:5100/health', timeout=3)"

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "5100", "--proxy-headers"]
