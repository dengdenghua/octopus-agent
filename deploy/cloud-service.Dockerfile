FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /service

RUN pip install --no-cache-dir "fastapi>=0.115,<1" "uvicorn>=0.30,<1" "cryptography>=43,<47"
COPY runtime/__init__.py /service/runtime/__init__.py
COPY runtime/cloud_edge /service/runtime/cloud_edge

RUN useradd --system --uid 10001 cloudsvc && mkdir -p /data && chown cloudsvc:cloudsvc /data
USER cloudsvc

EXPOSE 8090
CMD ["python", "-m", "uvicorn", "runtime.cloud_edge.app:create_cloud_edge_app_from_env", "--factory", "--host", "0.0.0.0", "--port", "8090"]
