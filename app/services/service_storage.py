import hashlib
from pathlib import Path

import cv2
from fastapi import UploadFile

from app.config import BASE_DIR, SERVICE_ASSET_DIR, SERVICE_IMAGE_DIR
from app.services.errors import json_error


def detect_image_type(data: bytes) -> str | None:
    if data.startswith(b"version https://git-lfs.github.com/spec/"):
        return "git_lfs_pointer"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data[:12].endswith(b"ftyp"):
        return "heic_or_mp4_container"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "webp"
    return None


def detect_upload_mime(data: bytes):
    image_type = detect_image_type(data)
    return {
        "jpeg": "image/jpeg",
        "png": "image/png",
        "webp": "image/webp",
    }.get(image_type)


def extension_for_mime(mime: str):
    return {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
    }[mime]


def np_from_bytes(data: bytes):
    import numpy as np

    return np.frombuffer(data, dtype=np.uint8)


def image_meta_from_bytes(data: bytes, filename: str):
    if not data:
        json_error("PARAMETER_ERROR", f"{filename or 'image'} is empty")
    if len(data) > 5 * 1024 * 1024:
        json_error("IMAGE_TOO_LARGE", "single image must be <= 5 MB")
    mime = detect_upload_mime(data)
    if not mime:
        image_type = detect_image_type(data)
        if image_type == "git_lfs_pointer":
            json_error("UNSUPPORTED_IMAGE_FORMAT", "uploaded file is a Git LFS pointer, not image bytes", 415)
        json_error("UNSUPPORTED_IMAGE_FORMAT", "supported image formats are JPEG, PNG, WEBP", 415)
    array = cv2.imdecode(np_from_bytes(data), cv2.IMREAD_COLOR)
    if array is None:
        json_error("IMAGE_READ_FAILED", "image cannot be decoded", 415)
    height, width = array.shape[:2]
    if min(height, width) < 80:
        json_error("PARAMETER_ERROR", "image minimum side must be at least 80 px")
    if max(height, width) > 4096:
        json_error("PARAMETER_ERROR", "image maximum side must be at most 4096 px")
    return {
        "data": data,
        "sha256": hashlib.sha256(data).hexdigest(),
        "size_bytes": len(data),
        "mime": mime,
        "original_filename": filename or "image",
        "ext": extension_for_mime(mime),
    }


def validate_service_image(upload: UploadFile):
    return image_meta_from_bytes(upload.file.read(), upload.filename or "image")


def image_meta_from_path(path: str):
    file_path = BASE_DIR / path if not str(path).startswith("/") else None
    source_path = file_path if file_path and file_path.exists() else Path(path)
    return image_meta_from_bytes(source_path.read_bytes(), source_path.name)


def service_image_folder(job_id: str):
    from datetime import datetime, timezone

    today = datetime.now(timezone.utc)
    return SERVICE_IMAGE_DIR / today.strftime("%Y") / today.strftime("%m") / today.strftime("%d") / job_id


def store_service_images(job_id: str, first: dict, second: dict):
    folder = service_image_folder(job_id)
    folder.mkdir(parents=True, exist_ok=True)
    first_path = folder / f"first{first['ext']}"
    second_path = folder / f"second{second['ext']}"
    first_path.write_bytes(first["data"])
    second_path.write_bytes(second["data"])
    return str(first_path.relative_to(BASE_DIR)), str(second_path.relative_to(BASE_DIR))


def safe_asset_extension(filename: str, mime: str):
    suffix = Path(filename or "").suffix.lower()
    if suffix and len(suffix) <= 16 and all(char.isalnum() or char in {".", "_", "-"} for char in suffix):
        return suffix
    return {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "application/json": ".json",
        "text/plain": ".txt",
        "video/mp4": ".mp4",
        "text/csv": ".csv",
    }.get(mime, ".bin")


def generic_asset_meta(data: bytes, filename: str, content_type: str | None):
    if not data:
        json_error("PARAMETER_ERROR", f"{filename or 'asset'} is empty")
    if len(data) > 50 * 1024 * 1024:
        json_error("ASSET_TOO_LARGE", "single asset must be <= 50 MB")
    mime = content_type or detect_upload_mime(data) or "application/octet-stream"
    return {
        "data": data,
        "sha256": hashlib.sha256(data).hexdigest(),
        "size_bytes": len(data),
        "mime": mime,
        "original_filename": filename or "asset",
        "ext": safe_asset_extension(filename or "", mime),
    }


def service_asset_folder(task_id: str):
    from datetime import datetime, timezone

    today = datetime.now(timezone.utc)
    return SERVICE_ASSET_DIR / today.strftime("%Y") / today.strftime("%m") / today.strftime("%d") / task_id


def store_service_asset(task_id: str, asset_id: str, asset: dict):
    folder = service_asset_folder(task_id)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{asset_id}{asset['ext']}"
    path.write_bytes(asset["data"])
    return str(path.relative_to(BASE_DIR))
