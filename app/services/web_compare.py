import os
import uuid

from fastapi import HTTPException, UploadFile

from app.services.evaluation import read_evaluation_job
from app.core.face_compare import MODEL_CONFIGS
from app.services.service_jobs import (
    create_local_service_job,
    JOB_TYPE_WEB_SINGLE,
    legacy_service_job_payload,
)
from app.services.web_image import resolve_dataset_path, save_upload


def list_configs():
    return [{"id": config_id, **config} for config_id, config in MODEL_CONFIGS.items()]


def enqueue_compare_job(config_id: str, image_a: UploadFile, image_b: UploadFile, threshold: str):
    path_a = save_upload(image_a)
    path_b = save_upload(image_b)
    try:
        job_id, _task_ids = create_local_service_job(
            api_id="web_poc",
            request_id=uuid.uuid4().hex,
            first_path=path_a,
            second_path=path_b,
            model_config_ids=[config_id],
            job_type=JOB_TYPE_WEB_SINGLE,
            threshold=threshold,
        )
        return {"job_id": job_id, "status": "queued"}
    finally:
        for path in (path_a, path_b):
            try:
                os.remove(path)
            except OSError:
                pass


def enqueue_server_compare_job(config_id: str, image_a_path: str, image_b_path: str, threshold: str):
    path_a = resolve_dataset_path(image_a_path)
    path_b = resolve_dataset_path(image_b_path)
    job_id, _task_ids = create_local_service_job(
        api_id="web_poc_dataset",
        request_id=uuid.uuid4().hex,
        first_path=str(path_a),
        second_path=str(path_b),
        model_config_ids=[config_id],
        job_type=JOB_TYPE_WEB_SINGLE,
        threshold=threshold,
    )
    return {"job_id": job_id, "status": "queued"}


def read_job(job_id: str):
    service_job = legacy_service_job_payload(job_id)
    if service_job:
        return service_job
    job = read_evaluation_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"unknown job_id: {job_id}")
    return job
