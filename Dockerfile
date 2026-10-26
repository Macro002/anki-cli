# anki-cli: Anki's engine as a headless, AnkiConnect-compatible server.
#   docker build -t anki-cli .
#   docker run -d -p 8765:8765 -v anki-data:/data -e ANKICLI_API_KEY=change-me anki-cli
FROM python:3.12-slim

RUN useradd --create-home --uid 1000 anki \
    && mkdir /data && chown anki:anki /data
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir . && rm -rf /root/.cache

USER anki
ENV ANKICLI_BASE=/data \
    ANKICLI_HOST=0.0.0.0 \
    ANKICLI_PORT=8765 \
    PYTHONUNBUFFERED=1
VOLUME ["/data"]
EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/health', timeout=4)"
# Set ANKICLI_API_KEY: the container listens on all interfaces.
CMD ["anki-cli", "serve"]
