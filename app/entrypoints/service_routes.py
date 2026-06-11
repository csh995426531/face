from datetime import datetime, timezone
from typing import Any
import uuid

from fastapi import APIRouter, Body, File, Form, Header, Request, UploadFile
from fastapi.responses import JSONResponse

from app.services.service_auth import generate_token, require_access_token, require_worker
from app.db.mysql import utc_iso
from app.services.errors import json_error
from app.services.service_jobs import (
    complete_generic_worker_task,
    complete_worker_task,
    create_generic_service_task,
    create_service_compare_job as create_service_compare_job_service,
    get_compare_task,
    generic_task_payload,
    lease_generic_worker_tasks,
    lease_worker_tasks,
    renew_worker_task,
    save_worker_heartbeat,
    service_job_payload,
    submit_official_result_record,
    submit_vendor_result as submit_vendor_result_service,
)
from app.services.service_storage import generic_asset_meta

router = APIRouter()


def api_response(code="SUCCESS", message="OK", data=None, http_status=200):
    return JSONResponse(
        status_code=http_status,
        content={
            "code": code,
            "message": message,
            "data": data,
            "extra": None,
            "transactionId": f"txn_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}",
            "pricingStrategy": "FREE",
        },
    )


def fail_api(code: str, message: str, http_status=400):
    return api_response(code=code, message=message, data=None, http_status=http_status)


def bounded_int(payload: dict[str, Any], field_name: str, default: int, minimum: int, maximum: int):
    try:
        value = int(payload.get(field_name, default))
    except (TypeError, ValueError):
        json_error("PARAMETER_ERROR", f"{field_name} must be integer")
    return min(max(value, minimum), maximum)


@router.post("/openapi/auth/ticket/v1/generate-token")
def generate_access_token(payload: dict[str, Any] = Body(...)):
    data, code, message = generate_token(
        str(payload.get("accessKey", "")).strip(),
        str(payload.get("timestamp", "")).strip(),
        str(payload.get("signature", "")).strip().lower(),
        payload.get("periodSecond", "3600"),
    )
    if code:
        return fail_api(code, message, 403 if code == "ACCOUNT_DISABLED" else 400)
    return api_response(data=data)


@router.post("/api/check")
def create_service_compare_job(
    firstImage: UploadFile = File(...),
    secondImage: UploadFile = File(...),
    requestId: str = Form(...),
    sourceProduct: str = Form(""),
    vendorRequestId: str = Form(""),
    x_access_token: str | None = Header(default=None),
):
    token = require_access_token(x_access_token)
    api_id = token["api_id"]
    request_id = requestId.strip()
    if not request_id:
        json_error("PARAMETER_ERROR", "requestId is required")
    job_id, status = create_service_compare_job_service(
        api_id,
        request_id,
        vendorRequestId.strip() or None,
        firstImage,
        secondImage,
    )
    return JSONResponse(status_code=202, content={"code": 0, "message": "accepted", "jobId": job_id, "status": status})


@router.post("/api/tasks")
async def create_generic_task(request: Request, x_access_token: str | None = Header(default=None)):
    token = require_access_token(x_access_token)
    form = await request.form()
    service_type = str(form.get("serviceType", "")).strip()
    request_id = str(form.get("requestId", "")).strip()
    api_id = token["api_id"]
    payload_json = form.get("payloadJson")
    official_result_json = form.get("officialResultJson")
    payload_json = str(payload_json) if payload_json is not None else None
    official_result_json = str(official_result_json) if official_result_json is not None else None
    positions: dict[str, int] = {}
    assets = []
    for field_name, value in form.multi_items():
        if not (hasattr(value, "filename") and hasattr(value, "read")):
            continue
        data = await value.read()
        position = positions.get(field_name, 0)
        positions[field_name] = position + 1
        meta = generic_asset_meta(data, value.filename or "asset", getattr(value, "content_type", None))
        assets.append(
            {
                "asset_id": f"sa_{uuid.uuid4().hex}",
                "field_name": field_name,
                "position": position,
                "sha256": meta["sha256"],
                "mime": meta["mime"],
                "size_bytes": meta["size_bytes"],
                "original_filename": meta["original_filename"],
                "data": meta["data"],
                "ext": meta["ext"],
            }
        )
    job, created = create_generic_service_task(
        service_type=service_type,
        api_id=api_id,
        request_id=request_id,
        raw_payload_json=payload_json,
        assets=assets,
        official_result_json=official_result_json,
    )
    return JSONResponse(
        status_code=202,
        content={
            "code": 0,
            "message": "accepted",
            "taskId": job["task_id"],
            "serviceType": job["service_type"],
            "status": job["status"],
            "created": created,
        },
    )


@router.post("/api/official-results")
def submit_official_result(payload: dict[str, Any] = Body(...), x_access_token: str | None = Header(default=None)):
    token = require_access_token(x_access_token)
    result = submit_official_result_record(
        api_id=token["api_id"],
        request_id=str(payload.get("requestId", "")).strip(),
        service_type=str(payload.get("serviceType", "")).strip(),
        official_result=payload.get("officialResult", {}),
        official_status=payload.get("officialStatus"),
        official_elapsed_ms=payload.get("officialElapsedMs"),
        vendor_request_id=payload.get("vendorRequestId"),
    )
    return JSONResponse(status_code=202, content={"code": 0, "message": "accepted", **result})


@router.get("/api/tasks/{task_id}")
def get_generic_task(task_id: str, x_access_token: str | None = Header(default=None)):
    token = require_access_token(x_access_token)
    payload = generic_task_payload(task_id)
    if not payload or payload.get("apiId") != token["api_id"]:
        json_error("PARAMETER_ERROR", f"unknown taskId: {task_id}", 404)
    return payload


@router.get("/internal/face-recognition/jobs/{job_id}")
def get_service_job(job_id: str, x_access_token: str | None = Header(default=None)):
    token = require_access_token(x_access_token)
    payload = service_job_payload(job_id)
    if not payload or payload.get("apiId") != token["api_id"]:
        json_error("PARAMETER_ERROR", f"unknown jobId: {job_id}", 404)
    return payload


@router.post("/internal/face-recognition/vendor-results")
def submit_vendor_result(payload: dict[str, Any] = Body(...), x_access_token: str | None = Header(default=None)):
    token = require_access_token(x_access_token)
    job_id = submit_vendor_result_service(token["api_id"], payload)
    return {"code": 0, "message": "accepted", "jobId": job_id}


@router.post("/internal/model-tasks/lease")
def lease_model_tasks(request: Request, payload: dict[str, Any] = Body(...)):
    model_config_id = str(payload.get("modelConfigId", "")).strip()
    worker_id = str(payload.get("workerId", "")).strip() or request.headers.get("X-WORKER-ID")
    limit = bounded_int(payload, "limit", 1, 1, 20)
    if not model_config_id:
        json_error("PARAMETER_ERROR", "modelConfigId is required")
    worker = require_worker(request, model_config_id)
    if worker_id != worker["worker_id"]:
        json_error("WORKER_AUTH_FAILED", "workerId does not match auth header", 401)
    return {"tasks": lease_worker_tasks(model_config_id, worker_id, limit)}


@router.post("/internal/tasks/lease")
def lease_service_tasks(request: Request, payload: dict[str, Any] = Body(...)):
    capability = str(payload.get("capability", "")).strip()
    worker_id = str(payload.get("workerId", "")).strip() or request.headers.get("X-WORKER-ID")
    limit = bounded_int(payload, "limit", 1, 1, 20)
    if not capability:
        json_error("PARAMETER_ERROR", "capability is required")
    worker = require_worker(request, capability=capability)
    if worker_id != worker["worker_id"]:
        json_error("WORKER_AUTH_FAILED", "workerId does not match auth header", 401)
    return {"tasks": lease_generic_worker_tasks(capability, worker_id, limit)}


@router.post("/internal/tasks/{worker_task_id}/result")
def submit_service_task_result(worker_task_id: str, request: Request, payload: dict[str, Any] = Body(...)):
    capability = str(payload.get("capability", "")).strip() or None
    worker = require_worker(request, capability=capability)
    worker_id = str(payload.get("workerId", "")).strip() or request.headers.get("X-WORKER-ID")
    if worker_id != worker["worker_id"]:
        json_error("WORKER_AUTH_FAILED", "workerId does not match auth header", 401)
    result = complete_generic_worker_task(worker_task_id, worker_id, payload)
    return {"code": 0, "message": "accepted", "workerTaskId": worker_task_id, "workerResultId": result["worker_result_id"], "workerId": worker["worker_id"]}


@router.post("/internal/model-tasks/{task_id}/result")
def submit_model_task_result(task_id: str, request: Request, payload: dict[str, Any] = Body(...)):
    task = get_compare_task(task_id)
    worker = require_worker(request, task["model_config_id"])
    worker_id = str(payload.get("workerId", "")).strip() or request.headers.get("X-WORKER-ID")
    if worker_id != worker["worker_id"]:
        json_error("WORKER_AUTH_FAILED", "workerId does not match auth header", 401)
    complete_worker_task(task_id, worker["worker_id"], payload)
    job = service_job_payload(task["job_id"])
    return {"code": 0, "message": "accepted", "taskId": task_id, "jobStatus": job["status"], "workerId": worker["worker_id"]}


@router.post("/internal/model-tasks/{task_id}/renew-lease")
def renew_model_task_lease(task_id: str, request: Request, payload: dict[str, Any] = Body(...)):
    task = get_compare_task(task_id)
    worker = require_worker(request, task["model_config_id"])
    if task["worker_id"] != worker["worker_id"]:
        json_error("WORKER_AUTH_FAILED", "worker does not hold this task lease", 403)
    lease_seconds = bounded_int(payload, "leaseSeconds", 300, 1, 600)
    _task, lease_until = renew_worker_task(task_id, lease_seconds)
    return {"taskId": task_id, "leaseUntil": utc_iso(lease_until)}


@router.post("/internal/workers/heartbeat")
def worker_heartbeat(request: Request, payload: dict[str, Any] = Body(...)):
    model_config_id = str(payload.get("modelConfigId", "")).strip()
    capability = str(payload.get("capability", "")).strip()
    worker = require_worker(request, model_config_id or None, capability or None)
    save_worker_heartbeat(worker["worker_id"], model_config_id, payload)
    return {"code": 0, "message": "accepted", "workerId": worker["worker_id"]}
