from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.services.evaluation import enqueue_evaluate_job, list_evaluation_jobs
from app.entrypoints.service_routes import router as service_router
from app.services.web_compare import (
    enqueue_compare_job,
    enqueue_server_compare_job,
    list_configs,
    read_job,
)
from app.services.web_image import (
    list_dataset_images,
    read_cache_status,
    render_dataset_preview,
    render_preview,
    render_server_detection,
)
from app.web_config import STATIC_DIR

app = FastAPI(title="Face Compare POC")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.include_router(service_router)


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/configs")
def configs():
    return list_configs()


@app.get("/api/cache")
def cache_status():
    return read_cache_status()


@app.get("/api/dataset")
def dataset_images():
    return list_dataset_images()


@app.get("/api/dataset/preview")
def dataset_preview(path: str):
    return render_dataset_preview(path)


@app.get("/api/detect/server")
def detect_server_image(path: str):
    return render_server_detection(path)


@app.post("/api/compare-jobs")
def create_compare_job(
    config_id: str = Form(...),
    image_a: UploadFile = File(...),
    image_b: UploadFile = File(...),
    threshold: str = Form(""),
):
    return enqueue_compare_job(config_id, image_a, image_b, threshold)


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    return read_job(job_id)


@app.post("/api/compare-server-jobs")
def create_server_compare_job(
    config_id: str = Form(...),
    image_a_path: str = Form(...),
    image_b_path: str = Form(...),
    threshold: str = Form(""),
):
    return enqueue_server_compare_job(config_id, image_a_path, image_b_path, threshold)


@app.get("/api/evaluate-jobs")
def evaluation_jobs():
    return {"jobs": list_evaluation_jobs()}


@app.post("/api/evaluate-jobs")
def create_evaluate_job(
    positive_limit_per_group: int = Form(8),
    negative_limit_per_group: int = Form(8),
):
    return enqueue_evaluate_job(positive_limit_per_group, negative_limit_per_group)


@app.post("/api/preview")
def preview_image(image: UploadFile = File(...)):
    return render_preview(image)


@app.get("/{prefix:path}/api/configs")
def prefixed_configs(prefix: str):
    return list_configs()


@app.get("/{prefix:path}/api/cache")
def prefixed_cache_status(prefix: str):
    return read_cache_status()


@app.get("/{prefix:path}/api/dataset")
def prefixed_dataset_images(prefix: str):
    return list_dataset_images()


@app.get("/{prefix:path}/api/dataset/preview")
def prefixed_dataset_preview(prefix: str, path: str):
    return render_dataset_preview(path)


@app.get("/{prefix:path}/api/detect/server")
def prefixed_detect_server_image(prefix: str, path: str):
    return render_server_detection(path)


@app.post("/{prefix:path}/api/compare-jobs")
def prefixed_create_compare_job(
    prefix: str,
    config_id: str = Form(...),
    image_a: UploadFile = File(...),
    image_b: UploadFile = File(...),
    threshold: str = Form(""),
):
    return enqueue_compare_job(config_id, image_a, image_b, threshold)


@app.get("/{prefix:path}/api/jobs/{job_id}")
def prefixed_get_job(prefix: str, job_id: str):
    return read_job(job_id)


@app.post("/{prefix:path}/api/compare-server-jobs")
def prefixed_create_server_compare_job(
    prefix: str,
    config_id: str = Form(...),
    image_a_path: str = Form(...),
    image_b_path: str = Form(...),
    threshold: str = Form(""),
):
    return enqueue_server_compare_job(config_id, image_a_path, image_b_path, threshold)


@app.get("/{prefix:path}/api/evaluate-jobs")
def prefixed_evaluation_jobs(prefix: str):
    return {"jobs": list_evaluation_jobs()}


@app.post("/{prefix:path}/api/evaluate-jobs")
def prefixed_create_evaluate_job(
    prefix: str,
    positive_limit_per_group: int = Form(8),
    negative_limit_per_group: int = Form(8),
):
    return enqueue_evaluate_job(positive_limit_per_group, negative_limit_per_group)


@app.post("/{prefix:path}/api/preview")
def prefixed_preview_image(prefix: str, image: UploadFile = File(...)):
    return render_preview(image)


@app.get("/{prefix:path}")
def prefixed_index(prefix: str):
    return FileResponse(STATIC_DIR / "index.html")
