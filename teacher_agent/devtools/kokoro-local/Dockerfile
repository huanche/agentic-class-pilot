FROM python:3.11-slim-bookworm

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 HF_HOME=/runtime/cache/huggingface XDG_CACHE_HOME=/runtime/cache
WORKDIR /opt/kokoro
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 libespeak-ng1 ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt ./
RUN pip install --disable-pip-version-check -r requirements.txt
COPY download_models.py ./
RUN python download_models.py --root /opt/kokoro \
    && python -c "import urllib.request; urllib.request.urlretrieve('https://www.apache.org/licenses/LICENSE-2.0.txt', '/opt/kokoro/MODEL-LICENSE.txt')"
COPY server.py listen.html MODEL-NOTICE.txt narration-smoke.txt ./
RUN mkdir -p /runtime && chown 10001:10001 /runtime
USER 10001:10001
EXPOSE 13305
HEALTHCHECK --interval=15s --timeout=3s --start-period=90s --retries=4 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:13305/health',timeout=2).read()"
ENTRYPOINT ["python", "/opt/kokoro/server.py", "--root", "/runtime", "--model-dir", "/opt/kokoro/models", "--host", "0.0.0.0", "--threads", "1"]
