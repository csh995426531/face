import hashlib
import json
import shutil
import uuid
from datetime import datetime, timezone
from typing import Any

from app.config import BASE_DIR, DEFAULT_SERVICE_CAPABILITIES, SERVICE_MODEL_CONFIG_IDS, SUPPORTED_SERVICE_TYPES
from app.db.mysql import now_ts, utc_iso
from app.services.errors import json_error
from app.repositories.service import (
    complete_service_worker_task as repo_complete_service_worker_task,
    complete_task_with_result as repo_complete_task_with_result,
    create_compare_job,
    create_service_job_bundle,
    fail_task as repo_fail_task,
    comparison_exists,
    get_comparison_results,
    get_job,
    get_job_by_request,
    get_job_results,
    get_job_tasks,
    get_official_results,
    get_pending_official_result,
    get_service_assets,
    get_service_job,
    get_service_job_by_request,
    get_service_worker_task,
    get_service_worker_tasks,
    get_task,
    get_worker_results,
    insert_comparison_result,
    insert_official_result,
    lease_tasks,
    lease_service_worker_tasks as repo_lease_service_worker_tasks,
    mark_pending_official_attached,
    mark_task_running as repo_mark_task_running,
    renew_task_lease,
    save_pending_official_result,
    save_vendor_result,
    upsert_worker_heartbeat,
)
from app.services.service_storage import image_meta_from_path, service_asset_folder, service_image_folder, store_service_asset, store_service_images, validate_service_image

JOB_TYPE_API_CHECK = "api_check"
JOB_TYPE_WEB_SINGLE = "web_single"
JOB_TYPE_WEB_EVALUATION = "web_evaluation"


def next_service_id(prefix: str):
    return f"{prefix}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:10]}"


def canonical_json(value: Any):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_text(value: str):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def service_payload_hash(raw_payload_json: str | None):
    return sha256_text(raw_payload_json or "")


def service_assets_hash(assets: list[dict]):
    fingerprint = [
        {
            "fieldName": asset["field_name"],
            "position": asset["position"],
            "sha256": asset["sha256"],
            "sizeBytes": asset["size_bytes"],
            "mime": asset["mime"],
            "originalFilename": asset.get("original_filename"),
        }
        for asset in assets
    ]
    return sha256_text(canonical_json(fingerprint))


def validate_service_type(service_type: str):
    if service_type not in SUPPORTED_SERVICE_TYPES:
        json_error("PARAMETER_ERROR", f"unsupported serviceType: {service_type}", 400)
    return service_type


def default_capabilities_for_service(service_type: str):
    return [DEFAULT_SERVICE_CAPABILITIES[service_type]]


def parse_json_text(raw_value: str | None, field_name: str):
    if raw_value is None or raw_value == "":
        return None
    try:
        return json.loads(raw_value)
    except json.JSONDecodeError:
        json_error("PARAMETER_ERROR", f"{field_name} must be valid JSON")


def create_generic_service_task(
    *,
    service_type: str,
    source_product: str,
    request_id: str,
    raw_payload_json: str | None,
    assets: list[dict],
    official_result_json: str | None = None,
):
    validate_service_type(service_type)
    if not source_product:
        json_error("PARAMETER_ERROR", "sourceProduct is required")
    if not request_id:
        json_error("PARAMETER_ERROR", "requestId is required")
    parse_json_text(raw_payload_json, "payloadJson")
    parse_json_text(official_result_json, "officialResultJson")
    normalized_assets = sorted(assets, key=lambda item: (item["field_name"], item["position"], item["asset_id"]))
    payload_hash = service_payload_hash(raw_payload_json)
    assets_hash = service_assets_hash(normalized_assets)
    if official_result_json:
        pending = get_pending_official_result(source_product, request_id, service_type)
        if pending and pending["result_hash"] != sha256_text(official_result_json):
            json_error("PARAMETER_ERROR", "inline official result conflicts with pending official result", 409)
    existing = get_service_job_by_request(source_product, request_id, service_type)
    if existing:
        if existing["payload_hash"] != payload_hash or existing["assets_hash"] != assets_hash:
            json_error("PARAMETER_ERROR", "same sourceProduct + requestId + serviceType submitted with different payload or assets", 409)
        if official_result_json:
            submit_official_result_record(
                source_product=source_product,
                request_id=request_id,
                service_type=service_type,
                official_result=official_result_json,
            )
        attach_pending_official_result(existing["task_id"])
        return existing, False

    task_id = next_service_id("sj")
    now = now_ts()
    for asset in normalized_assets:
        asset["task_id"] = task_id
        asset["uri"] = store_service_asset(task_id, asset["asset_id"], asset)
        asset["created_at"] = now
    worker_tasks = [
        {
            "worker_task_id": f"swt_{task_id}_{index:02d}",
            "task_id": task_id,
            "capability": capability,
            "status": "queued",
            "queued_at": now,
        }
        for index, capability in enumerate(default_capabilities_for_service(service_type), start=1)
    ]
    job = {
        "task_id": task_id,
        "service_type": service_type,
        "source_product": source_product,
        "request_id": request_id,
        "status": "queued",
        "raw_payload_json": raw_payload_json,
        "payload_hash": payload_hash,
        "assets_hash": assets_hash,
        "metadata_json": canonical_json({"capabilities": [task["capability"] for task in worker_tasks]}),
        "created_at": now,
        "updated_at": now,
    }
    try:
        create_service_job_bundle(job, normalized_assets, worker_tasks)
    except Exception:
        shutil.rmtree(service_asset_folder(task_id), ignore_errors=True)
        raise

    if official_result_json:
        submit_official_result_record(
            source_product=source_product,
            request_id=request_id,
            service_type=service_type,
            official_result=official_result_json,
        )
    attach_pending_official_result(task_id)
    return get_service_job(task_id), True


def raw_result_text(value: Any):
    if isinstance(value, str):
        parse_json_text(value, "officialResult")
        return value
    return canonical_json(value if value is not None else {})


def build_official_result(source_product: str, request_id: str, service_type: str, raw_result_json: str, **metadata):
    return {
        "official_result_id": next_service_id("or"),
        "pending_id": next_service_id("por"),
        "source_product": source_product,
        "request_id": request_id,
        "service_type": service_type,
        "official_status": metadata.get("official_status"),
        "official_elapsed_ms": metadata.get("official_elapsed_ms"),
        "vendor_request_id": metadata.get("vendor_request_id"),
        "raw_result_json": raw_result_json,
        "result_hash": sha256_text(raw_result_json),
        "created_at": now_ts(),
    }


def attach_pending_official_result(task_id: str):
    job = get_service_job(task_id)
    if not job:
        return None
    pending = get_pending_official_result(job["source_product"], job["request_id"], job["service_type"])
    if not pending:
        return None
    attached = insert_official_result(
        {
            "official_result_id": next_service_id("or"),
            "task_id": task_id,
            "source_product": pending["source_product"],
            "request_id": pending["request_id"],
            "service_type": pending["service_type"],
            "official_status": pending.get("official_status"),
            "official_elapsed_ms": pending.get("official_elapsed_ms"),
            "vendor_request_id": pending.get("vendor_request_id"),
            "raw_result_json": pending["raw_result_json"],
            "result_hash": pending["result_hash"],
            "created_at": now_ts(),
        }
    )
    if attached["result_hash"] != pending["result_hash"]:
        json_error("PARAMETER_ERROR", "pending official result conflicts with the attached official result", 409)
    mark_pending_official_attached(pending["pending_id"], task_id)
    trigger_comparisons(task_id)
    return attached


def submit_official_result_record(
    *,
    source_product: str,
    request_id: str,
    service_type: str,
    official_result: Any,
    official_status: str | None = None,
    official_elapsed_ms: int | None = None,
    vendor_request_id: str | None = None,
):
    validate_service_type(service_type)
    if not source_product or not request_id:
        json_error("PARAMETER_ERROR", "sourceProduct and requestId are required")
    raw_result_json = raw_result_text(official_result)
    job = get_service_job_by_request(source_product, request_id, service_type)
    base = build_official_result(
        source_product,
        request_id,
        service_type,
        raw_result_json,
        official_status=official_status,
        official_elapsed_ms=official_elapsed_ms,
        vendor_request_id=vendor_request_id,
    )
    if not job:
        pending = save_pending_official_result(base)
        if pending["result_hash"] != base["result_hash"]:
            json_error("PARAMETER_ERROR", "same sourceProduct + requestId + serviceType submitted with different official result", 409)
        return {"status": "pending_task", "pendingId": pending["pending_id"]}
    official = insert_official_result({**base, "task_id": job["task_id"]})
    if official["result_hash"] != base["result_hash"]:
        json_error("PARAMETER_ERROR", "same sourceProduct + requestId + serviceType submitted with different official result", 409)
    trigger_comparisons(job["task_id"])
    return {"status": "attached", "taskId": job["task_id"], "officialResultId": official["official_result_id"]}


def maybe_json(raw: str | None):
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return raw


def asset_payload(asset: dict[str, Any], include_url=False):
    payload = {
        "assetId": asset["asset_id"],
        "fieldName": asset["field_name"],
        "position": asset["position"],
        "uri": asset["uri"],
        "sha256": asset["sha256"],
        "mime": asset["mime"],
        "sizeBytes": asset["size_bytes"],
        "originalFilename": asset.get("original_filename"),
    }
    if include_url:
        payload["url"] = str(BASE_DIR / asset["uri"])
    return payload


def generic_task_payload(task_id: str):
    job = get_service_job(task_id)
    if not job:
        return None
    return {
        "taskId": job["task_id"],
        "serviceType": job["service_type"],
        "sourceProduct": job["source_product"],
        "requestId": job["request_id"],
        "status": job["status"],
        "rawPayload": maybe_json(job.get("raw_payload_json")),
        "assets": [asset_payload(asset) for asset in get_service_assets(task_id)],
        "workerTasks": [
            {
                "workerTaskId": task["worker_task_id"],
                "capability": task["capability"],
                "status": task["status"],
                "workerId": task.get("worker_id"),
                "leaseUntil": utc_iso(task["lease_until"]) if task.get("lease_until") else None,
            }
            for task in get_service_worker_tasks(task_id)
        ],
        "officialResults": [
            {
                "officialResultId": row["official_result_id"],
                "officialStatus": row.get("official_status"),
                "officialElapsedMs": row.get("official_elapsed_ms"),
                "vendorRequestId": row.get("vendor_request_id"),
                "rawResult": maybe_json(row.get("raw_result_json")),
            }
            for row in get_official_results(task_id)
        ],
        "workerResults": [
            {
                "workerResultId": row["worker_result_id"],
                "workerTaskId": row["worker_task_id"],
                "capability": row["capability"],
                "status": row["result_status"],
                "elapsedMs": row.get("elapsed_ms"),
                "rawResult": maybe_json(row.get("raw_result_json")),
                "normalizedResult": maybe_json(row.get("normalized_result_json")),
            }
            for row in get_worker_results(task_id)
        ],
        "comparisons": [
            {
                "comparisonId": row["comparison_id"],
                "capability": row.get("capability"),
                "officialResultId": row.get("official_result_id"),
                "workerResultId": row.get("worker_result_id"),
                "compareStatus": row["compare_status"],
                "diff": maybe_json(row.get("diff_json")),
            }
            for row in get_comparison_results(task_id)
        ],
    }


def lease_generic_worker_tasks(capability: str, worker_id: str, limit: int):
    lease_until = now_ts() + 300
    leased = []
    for worker_task, job, assets in repo_lease_service_worker_tasks(capability, worker_id, limit, lease_until):
        asset_list = [asset_payload(asset, include_url=True) for asset in assets]
        payload = {
            "workerTaskId": worker_task["worker_task_id"],
            "taskId": worker_task["task_id"],
            "serviceType": job["service_type"],
            "sourceProduct": job["source_product"],
            "requestId": job["request_id"],
            "capability": worker_task["capability"],
            "rawPayload": maybe_json(job.get("raw_payload_json")),
            "assets": asset_list,
            "leaseUntil": utc_iso(worker_task["lease_until"]),
        }
        if job["service_type"] == "face_compare":
            first = next((asset for asset in asset_list if asset["fieldName"] in {"firstImage", "image_a", "first"}), None)
            second = next((asset for asset in asset_list if asset["fieldName"] in {"secondImage", "image_b", "second"}), None)
            if first and second:
                payload.update({"firstImageUrl": first["url"], "secondImageUrl": second["url"]})
        leased.append(payload)
    return leased


def extract_same_person(value: Any):
    if not isinstance(value, dict):
        return None
    for key in ("samePerson", "same_person", "vendorSamePerson"):
        if key in value and isinstance(value[key], bool):
            return value[key]
    raw = value.get("rawResponse") if isinstance(value.get("rawResponse"), dict) else None
    if raw is not None:
        return extract_same_person(raw)
    result = value.get("result") if isinstance(value.get("result"), dict) else None
    if result is not None:
        return extract_same_person(result)
    return None


def compare_face_results(official: dict, worker: dict):
    official_raw = maybe_json(official.get("raw_result_json"))
    worker_raw = maybe_json(worker.get("normalized_result_json")) or maybe_json(worker.get("raw_result_json"))
    official_same = extract_same_person(official_raw)
    worker_same = extract_same_person(worker_raw)
    if official_same is None or worker_same is None:
        return "pending_adapter", {"reason": "face_compare result missing comparable samePerson value"}
    return (
        "matched" if official_same == worker_same else "mismatched",
        {"officialSamePerson": official_same, "workerSamePerson": worker_same},
    )


def insert_comparison_once(task_id: str, service_type: str, status: str, official: dict | None = None, worker: dict | None = None, diff: dict | None = None):
    official_id = official.get("official_result_id") if official else None
    worker_id = worker.get("worker_result_id") if worker else None
    if comparison_exists(task_id, official_id, worker_id, status):
        return
    insert_comparison_result(
        {
            "comparison_id": next_service_id("cr"),
            "task_id": task_id,
            "service_type": service_type,
            "capability": worker.get("capability") if worker else None,
            "official_result_id": official_id,
            "worker_result_id": worker_id,
            "compare_status": status,
            "diff_json": canonical_json(diff or {}) if diff is not None else None,
            "created_at": now_ts(),
        }
    )


def trigger_comparisons(task_id: str):
    job = get_service_job(task_id)
    if not job:
        return
    official_results = get_official_results(task_id)
    worker_results = [row for row in get_worker_results(task_id) if row["result_status"] == "completed"]
    if official_results and not worker_results:
        for official in official_results:
            insert_comparison_once(task_id, job["service_type"], "pending_worker", official=official)
        return
    if worker_results and not official_results:
        for worker in worker_results:
            insert_comparison_once(task_id, job["service_type"], "pending_official", worker=worker)
        return
    for official in official_results:
        for worker in worker_results:
            if job["service_type"] == "face_compare":
                status, diff = compare_face_results(official, worker)
            else:
                status, diff = "pending_adapter", {"reason": f"comparator not implemented for {job['service_type']}"}
            insert_comparison_once(task_id, job["service_type"], status, official=official, worker=worker, diff=diff)


def complete_generic_worker_task(worker_task_id: str, worker_id: str, payload: dict[str, Any]):
    task = get_service_worker_task(worker_task_id)
    if not task:
        json_error("PARAMETER_ERROR", f"unknown workerTaskId: {worker_task_id}", 404)
    if task["status"] != "running" or task["worker_id"] != worker_id or not task.get("lease_until") or float(task["lease_until"]) < now_ts():
        json_error("WORKER_AUTH_FAILED", "worker does not currently hold this task lease", 403)
    status = str(payload.get("status", "")).strip()
    if status not in {"completed", "failed"}:
        json_error("PARAMETER_ERROR", "status must be completed or failed")
    raw_result = payload.get("rawResult", payload.get("result", {}))
    normalized = payload.get("normalizedResult")
    saved = repo_complete_service_worker_task(
        worker_task_id,
        {
            "worker_result_id": next_service_id("wr"),
            "worker_id": worker_id,
            "result_status": status,
            "elapsed_ms": payload.get("elapsedMs"),
            "raw_result_json": raw_result_text(raw_result),
            "normalized_result_json": raw_result_text(normalized) if normalized is not None else None,
            "error_code": payload.get("errorCode"),
            "error_message": payload.get("errorMessage"),
            "created_at": now_ts(),
        },
    )
    if not saved:
        json_error("WORKER_AUTH_FAILED", "worker does not currently hold this task lease", 403)
    trigger_comparisons(task["task_id"])
    return saved


def build_job_and_tasks(
    source_product: str,
    request_id: str,
    vendor_request_id: str | None,
    first: dict,
    second: dict,
    model_config_ids: list[str],
    job_type: str,
    threshold: str = "",
):
    job_id = next_service_id("fc")
    first_uri, second_uri = store_service_images(job_id, first, second)
    now = now_ts()
    job = {
        "job_id": job_id,
        "job_type": job_type,
        "request_id": request_id,
        "source_product": source_product,
        "vendor_request_id": vendor_request_id,
        "first_image_uri": first_uri,
        "second_image_uri": second_uri,
        "first_image_sha256": first["sha256"],
        "second_image_sha256": second["sha256"],
        "first_image_size_bytes": first["size_bytes"],
        "second_image_size_bytes": second["size_bytes"],
        "first_image_mime": first["mime"],
        "second_image_mime": second["mime"],
        "first_original_filename": first["original_filename"],
        "second_original_filename": second["original_filename"],
        "status": "queued",
        "created_at": now,
        "updated_at": now,
    }
    tasks = [
        {
            "task_id": f"ft_{job_id}_{index:02d}",
            "job_id": job_id,
            "model_config_id": model_config_id,
            "threshold": threshold.strip() or None,
            "status": "queued",
            "queued_at": now,
        }
        for index, model_config_id in enumerate(model_config_ids, start=1)
    ]
    return job, tasks


def create_service_compare_job(source_product: str, request_id: str, vendor_request_id: str | None, first_upload, second_upload):
    first = validate_service_image(first_upload)
    second = validate_service_image(second_upload)
    existing = get_job_by_request(source_product, request_id)
    if existing:
        same_images = (
            existing["first_image_sha256"] == first["sha256"]
            and existing["second_image_sha256"] == second["sha256"]
        )
        if not same_images:
            json_error("PARAMETER_ERROR", "same sourceProduct + requestId submitted with different images", 409)
        return existing["job_id"], existing["status"]

    job, tasks = build_job_and_tasks(source_product, request_id, vendor_request_id, first, second, SERVICE_MODEL_CONFIG_IDS, JOB_TYPE_API_CHECK)
    try:
        create_compare_job(job, tasks)
    except Exception:
        shutil.rmtree(service_image_folder(job["job_id"]), ignore_errors=True)
        raise
    return job["job_id"], "queued"


def create_local_service_job(
    *,
    source_product: str,
    request_id: str,
    first_path: str,
    second_path: str,
    model_config_ids: list[str],
    job_type: str,
    threshold: str = "",
):
    existing = get_job_by_request(source_product, request_id)
    if existing:
        tasks = get_job_tasks(existing["job_id"])
        return existing["job_id"], [task["task_id"] for task in tasks]
    first = image_meta_from_path(first_path)
    second = image_meta_from_path(second_path)
    job, tasks = build_job_and_tasks(source_product, request_id, None, first, second, model_config_ids, job_type, threshold)
    create_compare_job(job, tasks)
    return job["job_id"], [task["task_id"] for task in tasks]


def mark_task_running(task_id: str):
    repo_mark_task_running(task_id)


def complete_task_with_result(task_id: str, compare_result: dict[str, Any], elapsed_ms: int):
    inner = compare_result["result"]
    same_person = inner.get("same_person")
    decision_status = "uncertain"
    if same_person is True:
        decision_status = "same_person"
    elif same_person is False:
        decision_status = "different_person"
    repo_complete_task_with_result(
        task_id,
        {
            "result_id": next_service_id("fr"),
            "score": inner.get("score"),
            "distance": inner.get("distance"),
            "score_direction": compare_result["config"].get("score_direction"),
            "same_person": int(bool(same_person)) if same_person is not None else None,
            "decision_status": decision_status,
            "threshold": inner.get("threshold"),
            "threshold_version": inner.get("threshold_version"),
            "elapsed_ms": elapsed_ms,
            "raw_result_json": json.dumps(compare_result, ensure_ascii=False),
            "created_at": now_ts(),
        },
    )


def fail_task(task_id: str, error_message: str, error_code="MODEL_RUNTIME_ERROR"):
    repo_fail_task(task_id, error_message, error_code)


def result_payload(row: dict[str, Any]):
    payload = {
        "modelConfigId": row["model_config_id"],
        "status": row["decision_status"],
        "score": row["score"],
        "distance": row["distance"],
        "scoreDirection": row["score_direction"],
        "samePerson": bool(row["same_person"]) if row["same_person"] is not None else None,
        "threshold": row["threshold"],
        "thresholdVersion": row["threshold_version"],
        "elapsedMs": row["elapsed_ms"],
    }
    return {key: value for key, value in payload.items() if value is not None}


def service_job_payload(job_id: str):
    job = get_job(job_id)
    if not job:
        return None
    tasks = get_job_tasks(job_id)
    results = {row["task_id"]: result_payload(row) for row in get_job_results(job_id)}
    return {
        "jobId": job["job_id"],
        "jobType": job.get("job_type"),
        "requestId": job["request_id"],
        "sourceProduct": job["source_product"],
        "status": job["status"],
        "tasks": [
            {
                "taskId": task["task_id"],
                "modelConfigId": task["model_config_id"],
                "status": task["status"],
                **results.get(task["task_id"], {}),
            }
            for task in tasks
        ],
    }


def legacy_service_job_payload(job_id: str):
    job = get_job(job_id)
    if not job:
        return None
    tasks = get_job_tasks(job_id)
    results = get_job_results(job_id)
    if not tasks:
        return None
    task = tasks[0]
    status = {"completed": "done", "failed": "error"}.get(task["status"], task["status"])
    payload = {
        "job_id": job_id,
        "status": status,
        "created_at": job["created_at"],
        "updated_at": job["updated_at"],
    }
    if task["status"] == "failed":
        payload["error"] = task.get("error_message") or task.get("error_code") or "compare job failed"
    if results:
        raw = results[0].get("raw_result_json")
        payload["result"] = json.loads(raw) if isinstance(raw, str) else raw
    return payload


def submit_vendor_result(source_product: str, payload: dict[str, Any]):
    request_id = str(payload.get("requestId", "")).strip()
    vendor_name = str(payload.get("vendorName", "")).strip()
    vendor_request_id = str(payload.get("vendorRequestId", "")).strip()
    if not request_id or not vendor_name or not vendor_request_id:
        json_error("PARAMETER_ERROR", "requestId, vendorName and vendorRequestId are required")
    job = get_job_by_request(source_product, request_id)
    if not job:
        json_error("PARAMETER_ERROR", "compare job not found for sourceProduct + requestId", 404)
    normalized = dict(payload)
    normalized["vendorName"] = vendor_name
    normalized["vendorRequestId"] = vendor_request_id
    save_vendor_result(job["job_id"], normalized, next_service_id("vr"))
    return job["job_id"]


def task_response(task: dict[str, Any], job: dict[str, Any]):
    return {
        "taskId": task["task_id"],
        "jobId": task["job_id"],
        "modelConfigId": task["model_config_id"],
        "firstImageUrl": str(BASE_DIR / job["first_image_uri"]),
        "secondImageUrl": str(BASE_DIR / job["second_image_uri"]),
        "threshold": task.get("threshold") or "",
        "leaseUntil": utc_iso(task["lease_until"]),
    }


def lease_worker_tasks(model_config_id: str, worker_id: str, limit: int):
    lease_until = now_ts() + 300
    return [task_response(task, job) for task, job in lease_tasks(model_config_id, worker_id, limit, lease_until)]


def complete_worker_task(task_id: str, worker_id: str, payload: dict[str, Any]):
    task = get_task(task_id)
    if not task:
        json_error("PARAMETER_ERROR", f"unknown taskId: {task_id}", 404)
    if task["status"] != "running" or task.get("worker_id") != worker_id or not task.get("lease_until") or float(task["lease_until"]) < now_ts():
        json_error("WORKER_AUTH_FAILED", "worker does not currently hold this task lease", 403)
    status = str(payload.get("status", "")).strip()
    if status not in {"completed", "failed"}:
        json_error("PARAMETER_ERROR", "status must be completed or failed")
    if payload.get("modelConfigId") and payload["modelConfigId"] != task["model_config_id"]:
        json_error("PARAMETER_ERROR", "modelConfigId does not match task")
    if status == "failed":
        error_code = str(payload.get("errorCode") or "MODEL_RUNTIME_ERROR")
        error_message = str(payload.get("errorMessage") or "model task failed")
        failed = repo_fail_task(task_id, error_message, error_code, worker_id=worker_id)
        if not failed:
            json_error("WORKER_AUTH_FAILED", "worker does not currently hold this task lease", 403)
        return task, None

    decision_status = str(payload.get("decisionStatus") or ("same_person" if payload.get("samePerson") is True else "different_person" if payload.get("samePerson") is False else "uncertain"))
    saved = repo_complete_task_with_result(
        task_id,
        {
            "result_id": next_service_id("fr"),
            "worker_id": worker_id,
            "score": payload.get("score"),
            "distance": payload.get("distance"),
            "score_direction": payload.get("scoreDirection"),
            "same_person": int(bool(payload["samePerson"])) if "samePerson" in payload else None,
            "decision_status": decision_status,
            "threshold": payload.get("threshold"),
            "threshold_version": payload.get("thresholdVersion"),
            "face_count_a": payload.get("faceCountA"),
            "face_count_b": payload.get("faceCountB"),
            "bbox_a_json": json.dumps(payload.get("bboxA"), ensure_ascii=False) if "bboxA" in payload else None,
            "bbox_b_json": json.dumps(payload.get("bboxB"), ensure_ascii=False) if "bboxB" in payload else None,
            "elapsed_ms": payload.get("elapsedMs"),
            "image_download_elapsed_ms": payload.get("imageDownloadElapsedMs"),
            "model_elapsed_ms": payload.get("modelElapsedMs"),
            "result_submit_elapsed_ms": payload.get("resultSubmitElapsedMs"),
            "raw_result_json": json.dumps(payload.get("rawResult", {}), ensure_ascii=False),
            "created_at": now_ts(),
        },
    )
    if not saved:
        json_error("WORKER_AUTH_FAILED", "worker does not currently hold this task lease", 403)
    updated = get_task(task_id)
    return task, updated


def get_compare_task(task_id: str):
    task = get_task(task_id)
    if not task:
        json_error("PARAMETER_ERROR", f"unknown taskId: {task_id}", 404)
    return task


def renew_worker_task(task_id: str, lease_seconds: int):
    task = get_compare_task(task_id)
    if task["status"] != "running":
        json_error("PARAMETER_ERROR", "only running task can renew lease")
    lease_until = now_ts() + lease_seconds
    renew_task_lease(task_id, lease_until)
    return task, lease_until


def save_worker_heartbeat(worker_id: str, model_config_id: str, payload: dict[str, Any]):
    upsert_worker_heartbeat(worker_id, model_config_id, payload)
