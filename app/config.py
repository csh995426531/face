import json
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / ".data"
SERVICE_IMAGE_DIR = DATA_DIR / "service-images"
SERVICE_ASSET_DIR = DATA_DIR / "service-assets"

MYSQL_CONFIG = {
    "host": os.environ.get("FACE_MYSQL_HOST", "127.0.0.1"),
    "port": int(os.environ.get("FACE_MYSQL_PORT", "3306")),
    "user": os.environ.get("FACE_MYSQL_USER", "face"),
    "password": os.environ.get("FACE_MYSQL_PASSWORD", "face"),
    "database": os.environ.get("FACE_MYSQL_DATABASE", "face_service_eval"),
    "charset": "utf8mb4",
}

DEFAULT_SERVICE_MODEL_CONFIG_IDS = "buffalo_l,arcface_retinaface_cosine,arcface_retinaface_euclidean_l2,facenet512_retinaface_cosine,ghostfacenet_retinaface_cosine"
SERVICE_MODEL_CONFIG_IDS = [
    value.strip()
    for value in os.environ.get("FACE_SERVICE_MODEL_CONFIG_IDS", DEFAULT_SERVICE_MODEL_CONFIG_IDS).split(",")
    if value.strip()
]
SUPPORTED_SERVICE_TYPES = {
    "ocr",
    "face_compare",
    "tamper_detect",
    "liveness",
    "aigc_detect",
    "blacklist",
}
DEFAULT_SERVICE_CAPABILITIES = {
    "ocr": os.environ.get("FACE_SERVICE_OCR_CAPABILITY", "ocr.baidu_latest"),
    "face_compare": os.environ.get("FACE_SERVICE_FACE_CAPABILITY", "face_compare.buffalo_l"),
    "tamper_detect": os.environ.get("FACE_SERVICE_TAMPER_CAPABILITY", "tamper_detect.vendor_x"),
    "liveness": os.environ.get("FACE_SERVICE_LIVENESS_CAPABILITY", "liveness.vendor_x"),
    "aigc_detect": os.environ.get("FACE_SERVICE_AIGC_CAPABILITY", "aigc_detect.watermark_v1"),
    "blacklist": os.environ.get("FACE_SERVICE_BLACKLIST_CAPABILITY", "blacklist.engineering_v1"),
}

ACCESS_CLIENTS = {
    os.environ.get("FACE_API_ACCESS_KEY", "sampleaccesskey"): {
        "secret_key": os.environ.get("FACE_API_SECRET_KEY", "samplesecretkey"),
        "source_product": os.environ.get("FACE_API_SOURCE_PRODUCT", "internal_product_a"),
        "status": os.environ.get("FACE_API_ACCOUNT_STATUS", "enabled"),
    }
}

DEV_WORKER_ID = os.environ.get("FACE_WORKER_ID", "dev-worker-buffalo-l")
DEV_WORKER_TOKEN = os.environ.get("FACE_WORKER_TOKEN", "dev-worker-token-change-me-32-bytes")


def load_worker_credentials():
    raw = os.environ.get("FACE_WORKER_CREDENTIALS_JSON")
    if raw:
        credentials = json.loads(raw)
        for credential in credentials:
            credential.setdefault("allowed_model_config_ids", SERVICE_MODEL_CONFIG_IDS)
            credential.setdefault(
                "allowed_capabilities",
                [f"face_compare.{value}" for value in credential.get("allowed_model_config_ids", [])],
            )
        return credentials
    return [
        {
            "worker_id": DEV_WORKER_ID,
            "worker_name": DEV_WORKER_ID,
            "worker_token": DEV_WORKER_TOKEN,
            "allowed_model_config_ids": SERVICE_MODEL_CONFIG_IDS,
            "allowed_capabilities": [f"face_compare.{value}" for value in SERVICE_MODEL_CONFIG_IDS],
        }
    ]


WORKER_CREDENTIALS = load_worker_credentials()
