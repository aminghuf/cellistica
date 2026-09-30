FROM python:3.12.14-slim-trixie

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DATA_DIR=/data

WORKDIR /srv
COPY requirements.txt requirements-dev.txt constraints.txt ./
# Dev deps (pytest, httpx) are small and let the tests run inside the container.
RUN pip install -c constraints.txt -r requirements-dev.txt

RUN useradd --create-home --uid 10001 app \
 && mkdir -p /data && chown app:app /data
COPY --chown=app:app . .

USER app
# music21 wants a writable home for its user settings.
ENV HOME=/home/app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --start-interval=2s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4)"
CMD ["uvicorn", "cello.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
