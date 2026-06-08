import argparse
import json
import os
import time
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np


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

    insightface_root = os.environ.get("INSIGHTFACE_ROOT", str(Path.cwd() / ".models" / "insightface"))
    app = FaceAnalysis(name="buffalo_l", root=insightface_root, providers=["CPUExecutionProvider"])
    app.prepare(ctx_id=-1, det_size=(640, 640))
    return app


def read_image(path):
    image = cv2.imread(path)
    if image is None:
        raise ValueError(f"failed to read image: {path}")
    return image


def get_buffalo_embedding(path):
    app = get_buffalo_app()
    faces = app.get(read_image(path))
    if len(faces) != 1:
        raise ValueError(f"expected exactly one face in {path}, got {len(faces)}")
    return faces[0].normed_embedding


def compare_buffalo(img_a, img_b, threshold):
    emb_a = get_buffalo_embedding(img_a)
    emb_b = get_buffalo_embedding(img_b)
    similarity = float(np.dot(emb_a, emb_b))
    result = {
        "engine": "insightface",
        "model": "buffalo_l",
        "metric": "cosine_similarity",
        "score": similarity,
    }
    if threshold is not None:
        result["threshold"] = threshold
        result["same_person"] = similarity >= threshold
    return result


def compare_deepface(img_a, img_b, model_name, detector_backend, distance_metric, threshold):
    from deepface import DeepFace

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
