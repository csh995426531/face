import argparse
import json
import os
import time
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def normalize_model_root(env_name, default_path):
    raw_path = os.environ.get(env_name)
    path = Path(raw_path).expanduser() if raw_path else default_path
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    path = path.resolve()
    os.environ[env_name] = str(path)
    return path


INSIGHTFACE_ROOT = normalize_model_root("INSIGHTFACE_ROOT", PROJECT_ROOT / ".models" / "insightface")
DEEPFACE_HOME = normalize_model_root("DEEPFACE_HOME", PROJECT_ROOT / ".models" / "deepface")


def parse_args():
    parser = argparse.ArgumentParser(description="Compare two face images.")
    parser.add_argument("--engine", choices=["buffalo_l", "deepface"], required=True)
    parser.add_argument("--img-a", required=True)
    parser.add_argument("--img-b", required=True)
    parser.add_argument("--threshold", type=float, default=None)
    parser.add_argument("--model-name", default="ArcFace")
    parser.add_argument("--detector-backend", default="retinaface")
    parser.add_argument("--distance-metric", default="cosine")
    return parser.parse_args()


@lru_cache(maxsize=1)
def get_buffalo_app():
    from insightface.app import FaceAnalysis

    app = FaceAnalysis(name="buffalo_l", root=str(INSIGHTFACE_ROOT), providers=["CPUExecutionProvider"])
    app.prepare(ctx_id=-1, det_size=(640, 640))
    return app


def read_image(path):
    image = cv2.imread(path)
    if image is None:
        raise ValueError(f"failed to read image: {path}")
    return image


def get_buffalo_face(path):
    app = get_buffalo_app()
    image = read_image(path)
    faces = app.get(image)
    if len(faces) != 1:
        raise ValueError(f"expected exactly one face in {path}, got {len(faces)}")
    face = faces[0]
    height, width = image.shape[:2]
    bbox = [float(value) for value in face.bbox.tolist()]
    return {
        "embedding": face.normed_embedding,
        "meta": {
            "image_size": {"width": width, "height": height},
            "bbox": {
                "x1": round(bbox[0], 2),
                "y1": round(bbox[1], 2),
                "x2": round(bbox[2], 2),
                "y2": round(bbox[3], 2),
            },
            "det_score": round(float(getattr(face, "det_score", 0.0)), 6),
        },
    }


def crop_bbox(image, bbox, margin=0.28):
    height, width = image.shape[:2]
    x1, y1, x2, y2 = [float(value) for value in bbox]
    box_width = x2 - x1
    box_height = y2 - y1
    pad_x = box_width * margin
    pad_y = box_height * margin
    x1 = max(0, int(round(x1 - pad_x)))
    y1 = max(0, int(round(y1 - pad_y)))
    x2 = min(width, int(round(x2 + pad_x)))
    y2 = min(height, int(round(y2 + pad_y)))
    return image[y1:y2, x1:x2]


def detect_buffalo_face_crop(path):
    app = get_buffalo_app()
    image = read_image(path)
    faces = app.get(image)
    if len(faces) != 1:
        raise ValueError(f"expected exactly one face in {path}, got {len(faces)}")
    face = faces[0]
    bbox = [float(value) for value in face.bbox.tolist()]
    crop = crop_bbox(image, bbox)
    height, width = image.shape[:2]
    meta = {
        "image_size": {"width": width, "height": height},
        "bbox": {
            "x1": round(bbox[0], 2),
            "y1": round(bbox[1], 2),
            "x2": round(bbox[2], 2),
            "y2": round(bbox[3], 2),
        },
        "det_score": round(float(getattr(face, "det_score", 0.0)), 6),
    }
    return crop, meta


def compare_buffalo(img_a, img_b, threshold):
    face_a = get_buffalo_face(img_a)
    face_b = get_buffalo_face(img_b)
    similarity = float(np.dot(face_a["embedding"], face_b["embedding"]))
    result = {
        "engine": "insightface",
        "model": "buffalo_l",
        "metric": "cosine_similarity",
        "score": similarity,
        "faces": {
            "image_a": face_a["meta"],
            "image_b": face_b["meta"],
        },
    }
    if threshold is not None:
        result["threshold"] = threshold
        result["same_person"] = similarity >= threshold
    return result


def compare_deepface(img_a, img_b, model_name, detector_backend, distance_metric, threshold):
    os.environ["DEEPFACE_HOME"] = str(DEEPFACE_HOME)
    deepface_weights = DEEPFACE_HOME / ".deepface" / "weights"
    deepface_weights.mkdir(parents=True, exist_ok=True)

    from deepface import DeepFace
    try:
        from deepface.commons import folder_utils

        folder_utils.get_deepface_home = lambda: str(DEEPFACE_HOME)
        folder_utils.initialize_folder()
    except Exception:
        pass

    previous_cwd = Path.cwd()
    try:
        os.chdir(PROJECT_ROOT)
        result = DeepFace.verify(
            img1_path=img_a,
            img2_path=img_b,
            model_name=model_name,
            detector_backend=detector_backend,
            distance_metric=distance_metric,
            align=True,
            enforce_detection=True,
            silent=True,
        )
    finally:
        os.chdir(previous_cwd)
    distance = float(result["distance"])
    output = {
        "engine": "deepface",
        "model": model_name,
        "detector": detector_backend,
        "metric": distance_metric,
        "distance": distance,
        "deepface_threshold": float(result["threshold"]),
        "deepface_verified": bool(result["verified"]),
    }
    if "facial_areas" in result:
        output["facial_areas"] = result["facial_areas"]
    if threshold is not None:
        output["threshold"] = threshold
        output["same_person"] = distance <= threshold
    return output


def main():
    args = parse_args()
    started = time.perf_counter()
    if args.engine == "buffalo_l":
        result = compare_buffalo(args.img_a, args.img_b, args.threshold)
    else:
        result = compare_deepface(
            args.img_a,
            args.img_b,
            args.model_name,
            args.detector_backend,
            args.distance_metric,
            args.threshold,
        )
    result["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 2)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
