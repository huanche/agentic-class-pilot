FROM python:3.11-slim-bookworm
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1 \
    HF_HOME=/tmp/huggingface XDG_CACHE_HOME=/tmp/cache NUMBA_CACHE_DIR=/tmp/numba
WORKDIR /opt/hojo
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 libsndfile1 ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt ./
RUN pip install --disable-pip-version-check -r requirements.txt
COPY download_models.py ./
# Use the exact model revisions validated locally; no floating weights on rebuild.
RUN mkdir -p /opt/hojo/bundle \
    && printf '%s' c3cf21c77dc04b220aa4dabe20fc59e66a2a5485 > /opt/hojo/bundle/40m-revision.txt \
    && printf '%s' d9c02af95496b6363b44944326d71491ab8905b0 > /opt/hojo/bundle/80m-revision.txt \
    && python download_models.py --root /opt/hojo/bundle --models 40m 80m \
    && rm -rf /tmp/huggingface
COPY server.py MODEL-NOTICE.txt ./
RUN mkdir -p /runtime && chown 10001:10001 /runtime
USER 10001:10001
HEALTHCHECK --interval=20s --timeout=3s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:13306/health',timeout=2).read()"
# Host networking keeps this internal service on loopback; no public port.
ENTRYPOINT ["python", "/opt/hojo/server.py", "--root", "/runtime", "--model-root", "/opt/hojo/bundle", "--threads", "1"]
