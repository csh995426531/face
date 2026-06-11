import hashlib
import hmac
import json

from fastapi import HTTPException, Request

from app.config import ACCESS_CLIENTS
from app.db.mysql import now_ts, token_hash
from app.services.errors import json_error
from app.repositories.service import create_access_token, get_access_token, get_worker_credential


def get_client(access_key: str):
    client = ACCESS_CLIENTS.get(access_key)
    if not client or client.get("status") != "enabled":
        return None
    return client


def generate_token(access_key: str, timestamp: str, signature: str, period_raw):
    if not access_key or not timestamp or not signature:
        return None, "PARAMETER_ERROR", "Parameter should not be empty"
    if not timestamp.isdigit():
        return None, "PARAMETER_ERROR", "Timestamp error"
    now_ms = int(now_ts() * 1000)
    timestamp_ms = int(timestamp)
    if abs(now_ms - timestamp_ms) > 300_000:
        return None, "PARAMETER_ERROR", "Timestamp error"
    client = get_client(access_key)
    if not client:
        return None, "ACCOUNT_DISABLED", "Account Disabled"
    expected = hashlib.sha256(f"{access_key}{client['secret_key']}{timestamp}".encode("utf-8")).hexdigest()
    if not hmac.compare_digest(expected, signature.lower()):
        return None, "PARAMETER_ERROR", "Signature error"
    try:
        period_second = int(period_raw)
    except (TypeError, ValueError):
        return None, "PARAMETER_ERROR", "periodSecond must be integer seconds"
    if period_second < 60 or period_second > 86400:
        return None, "PARAMETER_ERROR", "periodSecond out of range"
    import uuid

    token = f"access_token_{uuid.uuid4().hex}"
    expires_at = now_ts() + period_second
    create_access_token(token_hash(token), access_key, client["source_product"], expires_at)
    return {"token": token, "expiredTime": int(expires_at * 1000)}, None, None


def require_access_token(x_access_token: str | None):
    if not x_access_token:
        raise HTTPException(status_code=401, detail={"code": "INVALID_TOKEN", "message": "token missing"})
    row = get_access_token(token_hash(x_access_token))
    if not row or float(row["expires_at"]) < now_ts():
        raise HTTPException(status_code=401, detail={"code": "INVALID_TOKEN", "message": "token invalid or expired"})
    return row


def require_worker(request: Request, model_config_id: str | None = None, capability: str | None = None):
    worker_id = request.headers.get("X-WORKER-ID")
    worker_token = request.headers.get("X-WORKER-TOKEN")
    if not worker_id or not worker_token:
        json_error("WORKER_AUTH_MISSING", "worker auth headers missing", 401)
    row = get_worker_credential(worker_id)
    if not row or row["status"] != "enabled" or not hmac.compare_digest(row["token_hash"], token_hash(worker_token)):
        json_error("WORKER_AUTH_FAILED", "worker token validation failed", 401)
    allowed = json.loads(row["allowed_model_config_ids_json"])
    if model_config_id and model_config_id not in allowed:
        json_error("WORKER_MODEL_FORBIDDEN", "worker cannot access this modelConfigId", 403)
    allowed_capabilities = json.loads(row.get("allowed_capabilities_json") or "[]")
    if capability and capability not in allowed_capabilities:
        json_error("WORKER_CAPABILITY_FORBIDDEN", "worker cannot access this capability", 403)
    return row
