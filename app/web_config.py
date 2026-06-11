import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def normalize_app_model_root(env_name, default_path):
    raw_path = os.environ.get(env_name)
    path = Path(raw_path).expanduser() if raw_path else default_path
    if not path.is_absolute():
        path = BASE_DIR / path
    path = path.resolve()
    os.environ[env_name] = str(path)
    return path


normalize_app_model_root("INSIGHTFACE_ROOT", BASE_DIR / ".models" / "insightface")
normalize_app_model_root("DEEPFACE_HOME", BASE_DIR / ".models" / "deepface")
DATASET_ROOT = normalize_app_model_root("FACE_DATASET_ROOT", BASE_DIR / "datasets")
STATIC_DIR = BASE_DIR / "static"
