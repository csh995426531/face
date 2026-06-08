import os
import tempfile
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from compare import compare_buffalo, compare_deepface


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

MODEL_CONFIGS: dict[str, dict[str, Any]] = {
    "buffalo_l": {
        "label": "InsightFace Buffalo_L + cosine",
        "engine": "buffalo_l",
        "rank": "P0",
        "score_direction": "higher_is_more_similar",
        "license_note": "商用前必须确认 InsightFace 预训练模型授权。",
    },
    "arcface_retinaface_cosine": {
        "label": "DeepFace ArcFace + retinaface + cosine",
        "engine": "deepface",
        "model_name": "ArcFace",
        "detector_backend": "retinaface",
        "distance_metric": "cosine",
        "rank": "P1",
        "score_direction": "lower_is_more_similar",
    },
    "arcface_retinaface_euclidean_l2": {
        "label": "DeepFace ArcFace + retinaface + euclidean_l2",
        "engine": "deepface",
        "model_name": "ArcFace",
        "detector_backend": "retinaface",
        "distance_metric": "euclidean_l2",
        "rank": "P1",
        "score_direction": "lower_is_more_similar",
    },
    "facenet512_retinaface_cosine": {
        "label": "DeepFace Facenet512 + retinaface + cosine",
        "engine": "deepface",
        "model_name": "Facenet512",
        "detector_backend": "retinaface",
        "distance_metric": "cosine",
        "rank": "P2",
        "score_direction": "lower_is_more_similar",
    },
    "ghostfacenet_retinaface_cosine": {
        "label": "DeepFace GhostFaceNet + retinaface + cosine",
        "engine": "deepface",
        "model_name": "GhostFaceNet",
        "detector_backend": "retinaface",
        "distance_metric": "cosine",
        "rank": "P4",
        "score_direction": "lower_is_more_similar",
    },
}


app = FastAPI(title="Face Compare POC")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/configs")
def configs():
    return list_configs()


@app.get("/{prefix:path}/api/configs")
def prefixed_configs(prefix: str):
    return list_configs()


def list_configs():
    return [
        {
            "id": config_id,
            **config,
        }
        for config_id, config in MODEL_CONFIGS.items()
    ]


def save_upload(upload: UploadFile) -> str:
    suffix = Path(upload.filename or "image.jpg").suffix or ".jpg"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(upload.file.read())
        return tmp.name


@app.post("/api/compare")
def compare_images(
    config_id: str = Form(...),
    image_a: UploadFile = File(...),
    image_b: UploadFile = File(...),
    threshold: str = Form(""),
):
    return run_compare(config_id, image_a, image_b, threshold)


@app.post("/{prefix:path}/api/compare")
def prefixed_compare_images(
    prefix: str,
    config_id: str = Form(...),
    image_a: UploadFile = File(...),
    image_b: UploadFile = File(...),
    threshold: str = Form(""),
):
    return run_compare(config_id, image_a, image_b, threshold)


@app.get("/{prefix:path}")
def prefixed_index(prefix: str):
    return FileResponse(STATIC_DIR / "index.html")


def run_compare(
    config_id: str,
    image_a: UploadFile,
    image_b: UploadFile,
    threshold: str,
):
    config = MODEL_CONFIGS.get(config_id)
    if not config:
        raise HTTPException(status_code=400, detail=f"unknown config_id: {config_id}")

    parsed_threshold = None
    if threshold.strip():
        try:
            parsed_threshold = float(threshold)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="threshold must be a number") from exc

    path_a = save_upload(image_a)
    path_b = save_upload(image_b)
    try:
        if config["engine"] == "buffalo_l":
            result = compare_buffalo(path_a, path_b, parsed_threshold)
        else:
            result = compare_deepface(
                path_a,
                path_b,
                config["model_name"],
                config["detector_backend"],
                config["distance_metric"],
                parsed_threshold,
            )
        return {
            "config_id": config_id,
            "config": config,
            "result": result,
        }
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        for path in (path_a, path_b):
            try:
                os.remove(path)
            except OSError:
                pass
