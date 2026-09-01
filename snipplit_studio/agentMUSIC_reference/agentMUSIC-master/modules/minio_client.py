"""Shared MinIO client factory (used by both api_server and api_worker)."""

from __future__ import annotations

from modules.config import settings


def build_minio_client():
    """Return a configured Minio client or None when MinIO is not configured."""
    if not settings.minio_configured:
        return None

    from urllib.parse import urlparse

    from minio import Minio

    parsed = urlparse(settings.minio_url)
    endpoint = parsed.hostname + (f":{parsed.port}" if parsed.port else "")
    secure = parsed.scheme == "https"
    kwargs = {}
    if not settings.minio_tls_verify:
        import urllib3

        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        kwargs["http_client"] = urllib3.PoolManager(cert_reqs="CERT_NONE")

    return Minio(
        endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=secure,
        **kwargs,
    )
