from fastapi import HTTPException

from app.core.compare import compare_buffalo, compare_deepface

MODEL_CONFIGS = {
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

MODEL_CONFIG_ALIASES = {
    "buffalo_l_cosine_v1": "buffalo_l",
    "arcface_retinaface_cosine_v1": "arcface_retinaface_cosine",
}


def resolve_compare_config_id(config_id: str):
    return MODEL_CONFIG_ALIASES.get(config_id, config_id)


def run_compare_paths(config_id: str, path_a: str, path_b: str, threshold: str):
    config_id = resolve_compare_config_id(config_id)
    config = MODEL_CONFIGS.get(config_id)
    if not config:
        raise HTTPException(status_code=400, detail=f"unknown config_id: {config_id}")

    parsed_threshold = None
    if threshold.strip():
        try:
            parsed_threshold = float(threshold)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="threshold must be a number") from exc

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
