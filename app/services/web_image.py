import os
import tempfile
from pathlib import Path

import cv2
from fastapi import HTTPException, UploadFile
from fastapi.responses import Response

from app.web_config import DATASET_ROOT
from app.core.compare import PROJECT_ROOT, detect_buffalo_face_crop


def list_cache_files(path: Path):
    if not path.exists():
        return []
    return [
        {
            "path": str(file.relative_to(PROJECT_ROOT)),
            "size_mb": round(file.stat().st_size / 1024 / 1024, 2),
        }
        for file in sorted(path.rglob("*"))
        if file.is_file()
    ]


def read_cache_status():
    insightface_root = Path(os.environ["INSIGHTFACE_ROOT"])
    deepface_home = Path(os.environ["DEEPFACE_HOME"])
    return {
        "insightface_root": str(insightface_root),
        "deepface_home": str(deepface_home),
        "deepface_weights": str(deepface_home / ".deepface" / "weights"),
        "dataset_root": str(DATASET_ROOT),
        "insightface_files": list_cache_files(insightface_root),
        "deepface_files": list_cache_files(deepface_home),
    }


def resolve_dataset_path(relative_path: str):
    candidate = (DATASET_ROOT / relative_path).resolve()
    try:
        candidate.relative_to(DATASET_ROOT)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="dataset path escapes FACE_DATASET_ROOT") from exc
    if not candidate.is_file():
        raise HTTPException(status_code=404, detail=f"dataset image not found: {relative_path}")
    return candidate


def list_dataset_images():
    allowed_suffixes = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
    if not DATASET_ROOT.exists():
        return {"dataset_root": str(DATASET_ROOT), "images": []}
    images = []
    for file in sorted(DATASET_ROOT.rglob("*")):
        if not file.is_file() or file.name.startswith("."):
            continue
        if file.suffix.lower() not in allowed_suffixes:
            continue
        images.append(
            {
                "path": str(file.relative_to(DATASET_ROOT)),
                "name": file.name,
                "group": str(file.parent.relative_to(DATASET_ROOT)),
                "size_mb": round(file.stat().st_size / 1024 / 1024, 2),
            }
        )
    return {"dataset_root": str(DATASET_ROOT), "images": images}


def detect_image_type(data: bytes) -> str | None:
    if data.startswith(b"version https://git-lfs.github.com/spec/"):
        return "git_lfs_pointer"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data[:12].endswith(b"ftyp"):
        return "heic_or_mp4_container"
    if data.startswith(b"GIF87a") or data.startswith(b"GIF89a"):
        return "gif"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "webp"
    return None


def save_upload(upload: UploadFile) -> str:
    suffix = Path(upload.filename or "image.jpg").suffix or ".jpg"
    data = upload.file.read()
    if not data:
        raise HTTPException(status_code=400, detail=f"{upload.filename or 'image'} is empty; upload did not include file bytes")
    image_type = detect_image_type(data)
    if image_type == "git_lfs_pointer":
        raise HTTPException(status_code=415, detail=f"{upload.filename or 'image'} is a Git LFS pointer, not an image; run git lfs pull or download the real file")
    if image_type == "heic_or_mp4_container":
        raise HTTPException(status_code=415, detail=f"{upload.filename or 'image'} looks like HEIC/HEIF; convert it to JPEG or PNG first")
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(data)
        return tmp.name


def encode_jpeg(frame, quality=88):
    ok, encoded = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if not ok:
        raise HTTPException(status_code=500, detail="failed to encode image")
    return encoded.tobytes()


def render_preview(image: UploadFile):
    path = save_upload(image)
    try:
        frame = cv2.imread(path)
        if frame is None:
            raise HTTPException(status_code=415, detail="server cannot decode this image")
        height, width = frame.shape[:2]
        max_side = 900
        scale = min(1.0, max_side / max(height, width))
        if scale < 1.0:
            frame = cv2.resize(frame, (int(width * scale), int(height * scale)), interpolation=cv2.INTER_AREA)
        return Response(content=encode_jpeg(frame, quality=88), media_type="image/jpeg")
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def render_dataset_preview(relative_path: str):
    path = resolve_dataset_path(relative_path)
    frame = cv2.imread(str(path))
    if frame is None:
        raise HTTPException(status_code=415, detail=f"server cannot decode dataset image: {relative_path}")
    height, width = frame.shape[:2]
    max_side = 900
    scale = min(1.0, max_side / max(height, width))
    if scale < 1.0:
        frame = cv2.resize(frame, (int(width * scale), int(height * scale)), interpolation=cv2.INTER_AREA)
    return Response(content=encode_jpeg(frame, quality=88), media_type="image/jpeg")


def render_server_detection(relative_path: str):
    path = resolve_dataset_path(relative_path)
    try:
        crop, meta = detect_buffalo_face_crop(str(path))
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    headers = {
        "X-Face-Bbox": f"{meta['bbox']['x1']},{meta['bbox']['y1']},{meta['bbox']['x2']},{meta['bbox']['y2']}",
        "X-Face-Det-Score": str(meta["det_score"]),
        "X-Face-Image-Size": f"{meta['image_size']['width']}x{meta['image_size']['height']}",
    }
    return Response(content=encode_jpeg(crop, quality=92), media_type="image/jpeg", headers=headers)
