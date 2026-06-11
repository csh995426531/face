import time
import uuid
from typing import Any

from app.repositories.evaluation import (
    list_evaluation_jobs as repo_list_evaluation_jobs,
    load_evaluation_job,
    save_evaluation_job,
)
from app.repositories.service import get_job, get_job_results, get_job_tasks
from app.core.face_compare import MODEL_CONFIGS
from app.services.service_jobs import JOB_TYPE_WEB_EVALUATION, create_local_service_job
from app.services.web_image import list_dataset_images, resolve_dataset_path

def enqueue_evaluate_job(positive_limit_per_group: int, negative_limit_per_group: int):
    job_id = uuid.uuid4().hex
    pairs = build_evaluation_pairs(max(1, positive_limit_per_group), max(1, negative_limit_per_group))
    pair_jobs = []
    if not pairs:
        job = {
            "job_id": job_id,
            "status": "done",
            "kind": "evaluation",
            "created_at": time.time(),
            "updated_at": time.time(),
            "positive_limit_per_group": max(1, positive_limit_per_group),
            "negative_limit_per_group": max(1, negative_limit_per_group),
            "pairs": 0,
            "positive_pairs": 0,
            "negative_pairs": 0,
            "progress": initial_progress(0),
            "summaries": [summarize_model_results(config_id, []) for config_id in MODEL_CONFIGS],
            "details": {config_id: {"values": [], "failures": []} for config_id in MODEL_CONFIGS},
            "pair_jobs": [],
        }
        save_evaluation_job(job)
        return {"job_id": job_id, "status": "done"}
    try:
        for index, pair in enumerate(pairs, start=1):
            compare_job_id, _task_ids = create_local_service_job(
                source_product="web_poc_evaluation",
                request_id=f"{job_id}:{index}",
                first_path=str(resolve_dataset_path(pair["image_a"])),
                second_path=str(resolve_dataset_path(pair["image_b"])),
                model_config_ids=list(MODEL_CONFIGS),
                job_type=JOB_TYPE_WEB_EVALUATION,
            )
            pair_jobs.append({**pair, "compare_job_id": compare_job_id})
        job = {
            "job_id": job_id,
            "status": "queued",
            "kind": "evaluation",
            "created_at": time.time(),
            "updated_at": time.time(),
            "positive_limit_per_group": max(1, positive_limit_per_group),
            "negative_limit_per_group": max(1, negative_limit_per_group),
            "pairs": len(pairs),
            "positive_pairs": sum(1 for pair in pairs if pair["label"] == 1),
            "negative_pairs": sum(1 for pair in pairs if pair["label"] == 0),
            "progress": initial_progress(len(pairs)),
            "summaries": [],
            "details": {},
            "pair_jobs": pair_jobs,
        }
    except Exception as exc:
        job = {
            "job_id": job_id,
            "status": "error",
            "kind": "evaluation",
            "created_at": time.time(),
            "updated_at": time.time(),
            "positive_limit_per_group": max(1, positive_limit_per_group),
            "negative_limit_per_group": max(1, negative_limit_per_group),
            "pairs": len(pairs),
            "positive_pairs": sum(1 for pair in pairs if pair["label"] == 1),
            "negative_pairs": sum(1 for pair in pairs if pair["label"] == 0),
            "progress": {},
            "summaries": [],
            "details": {},
            "pair_jobs": pair_jobs,
            "error": str(exc),
        }
    save_evaluation_job(job)
    return {"job_id": job_id, "status": job["status"]}


def initial_progress(pair_count: int):
    return {config_id: {"status": "queued", "done": 0, "total": pair_count} for config_id in MODEL_CONFIGS}


def dataset_groups():
    images = list_dataset_images()["images"]
    groups: dict[str, list[dict[str, Any]]] = {}
    for image in images:
        group_key = image["group"]
        groups.setdefault(group_key, []).append(image)
    return {key: value for key, value in groups.items() if len(value) >= 2}


def build_evaluation_pairs(positive_limit_per_group: int, negative_limit_per_group: int):
    groups = dataset_groups()
    pairs = []
    for _group, images in groups.items():
        id_images = [item for item in images if item["name"].lower().startswith("id_")]
        selfie_images = [item for item in images if item["name"].lower().startswith("selfie_")]
        anchors = id_images or images[:1]
        positives = [(anchor, candidate) for anchor in anchors for candidate in selfie_images]
        if not positives:
            positives = [(anchor, candidate) for idx, anchor in enumerate(images) for candidate in images[idx + 1 :]]
        pairs.extend({"image_a": image_a["path"], "image_b": image_b["path"], "label": 1} for image_a, image_b in positives[:positive_limit_per_group])

    group_items = list(groups.items())
    for group, images in group_items:
        anchors = [item for item in images if item["name"].lower().startswith("id_")] or images[:1]
        per_other_group_candidates = []
        for other_group, other_images in group_items:
            if other_group == group:
                continue
            other_selfies = [item for item in other_images if item["name"].lower().startswith("selfie_")] or other_images
            candidates = [(anchor, candidate) for anchor in anchors for candidate in other_selfies]
            if candidates:
                per_other_group_candidates.append(candidates)

        negatives = []
        cursor = 0
        while len(negatives) < negative_limit_per_group and per_other_group_candidates:
            added = False
            for candidates in per_other_group_candidates:
                if cursor < len(candidates):
                    negatives.append(candidates[cursor])
                    added = True
                    if len(negatives) >= negative_limit_per_group:
                        break
            if not added:
                break
            cursor += 1

        pairs.extend({"image_a": image_a["path"], "image_b": image_b["path"], "label": 0} for image_a, image_b in negatives)
    return pairs


def is_higher_more_similar(config_id: str):
    return MODEL_CONFIGS[config_id]["score_direction"] == "higher_is_more_similar"


def confusion_for_threshold(values, threshold, higher_is_more_similar):
    tp = fp = tn = fn = 0
    for item in values:
        predicted_same = item["score"] >= threshold if higher_is_more_similar else item["score"] <= threshold
        actual_same = item["label"] == 1
        if predicted_same and actual_same:
            tp += 1
        elif predicted_same and not actual_same:
            fp += 1
        elif not predicted_same and actual_same:
            fn += 1
        else:
            tn += 1
    positives = tp + fn
    negatives = fp + tn
    total = positives + negatives
    return {
        "threshold": threshold,
        "tp": tp,
        "fp": fp,
        "tn": tn,
        "fn": fn,
        "accuracy": (tp + tn) / total if total else 0,
        "far": fp / negatives if negatives else 0,
        "frr": fn / positives if positives else 0,
    }


def auc_score(values, higher_is_more_similar):
    positives = [item["score"] for item in values if item["label"] == 1]
    negatives = [item["score"] for item in values if item["label"] == 0]
    if not positives or not negatives:
        return None
    wins = ties = 0
    for pos in positives:
        for neg in negatives:
            if higher_is_more_similar:
                if pos > neg:
                    wins += 1
                elif pos == neg:
                    ties += 1
            else:
                if pos < neg:
                    wins += 1
                elif pos == neg:
                    ties += 1
    return (wins + 0.5 * ties) / (len(positives) * len(negatives))


def summarize_model_results(config_id: str, values):
    higher = is_higher_more_similar(config_id)
    scores = sorted({item["score"] for item in values})
    thresholds = [scores[0] - 1e-9] if len(scores) > 1 else scores
    if len(scores) > 1:
        thresholds.extend((left + right) / 2 for left, right in zip(scores, scores[1:]))
        thresholds.append(scores[-1] + 1e-9)
    if not thresholds:
        return {"config_id": config_id, "label": MODEL_CONFIGS[config_id]["label"], "ok": 0, "failed": 0}
    best = max(
        (confusion_for_threshold(values, threshold, higher) for threshold in thresholds),
        key=lambda item: (item["accuracy"], -item["far"], -item["frr"]),
    )
    operating_points = [confusion_for_threshold(values, threshold, higher) for threshold in thresholds]
    zero_far_candidates = [point for point in operating_points if point["far"] == 0]
    zero_far = min(zero_far_candidates, key=lambda item: item["frr"]) if zero_far_candidates else None
    positive_scores = [item["score"] for item in values if item["label"] == 1]
    negative_scores = [item["score"] for item in values if item["label"] == 0]
    auc = auc_score(values, higher)
    return {
        "config_id": config_id,
        "label": MODEL_CONFIGS[config_id]["label"],
        "score_direction": MODEL_CONFIGS[config_id]["score_direction"],
        "ok": len(values),
        "best_threshold": round(best["threshold"], 6),
        "accuracy": round(best["accuracy"], 4),
        "far": round(best["far"], 4),
        "frr": round(best["frr"], 4),
        "zero_far_threshold": round(zero_far["threshold"], 6) if zero_far else None,
        "zero_far_frr": round(zero_far["frr"], 4) if zero_far else None,
        "tp": best["tp"],
        "fp": best["fp"],
        "tn": best["tn"],
        "fn": best["fn"],
        "auc": round(auc, 4) if auc is not None else None,
        "positive_score_range": [round(min(positive_scores), 6), round(max(positive_scores), 6)] if positive_scores else None,
        "negative_score_range": [round(min(negative_scores), 6), round(max(negative_scores), 6)] if negative_scores else None,
        "avg_latency_ms": round(sum(item["elapsed_ms"] for item in values) / len(values), 2),
    }


def result_score(result: dict[str, Any]):
    if result.get("score") is not None:
        return float(result["score"])
    return float(result["distance"])


def refresh_evaluation_job(job: dict[str, Any]):
    if job.get("status") == "error":
        return job
    pair_jobs = job.get("pair_jobs") or []
    progress = initial_progress(len(pair_jobs))
    details = {config_id: {"values": [], "failures": []} for config_id in MODEL_CONFIGS}
    terminal_count = 0
    task_count = 0

    for pair_job in pair_jobs:
        compare_job = get_job(pair_job["compare_job_id"])
        if not compare_job:
            continue
        tasks = get_job_tasks(compare_job["job_id"])
        results = {row["task_id"]: row for row in get_job_results(compare_job["job_id"])}
        for task in tasks:
            config_id = task["model_config_id"]
            if config_id not in progress:
                continue
            task_count += 1
            task_status = task["status"]
            if task_status in {"completed", "failed"}:
                terminal_count += 1
                progress[config_id]["done"] += 1
            if task_status == "completed" and task["task_id"] in results:
                result = results[task["task_id"]]
                details[config_id]["values"].append(
                    {
                        "image_a": pair_job["image_a"],
                        "image_b": pair_job["image_b"],
                        "label": pair_job["label"],
                        "score": result_score(result),
                        "elapsed_ms": result.get("elapsed_ms") or 0,
                    }
                )
            elif task_status == "failed":
                details[config_id]["failures"].append(
                    {
                        "image_a": pair_job["image_a"],
                        "image_b": pair_job["image_b"],
                        "label": pair_job["label"],
                        "error": task.get("error_message") or task.get("error_code") or "model task failed",
                    }
                )

    for config_id, item in progress.items():
        item["status"] = "done" if item["done"] == item["total"] else "running" if item["done"] else "queued"

    summaries = []
    for config_id, detail in details.items():
        summary = summarize_model_results(config_id, detail["values"])
        summary["failed"] = len(detail["failures"])
        summaries.append(summary)

    if task_count == 0:
        status = "queued"
    elif terminal_count == task_count:
        status = "done"
    else:
        status = "running"

    job.update(
        {
            "status": status,
            "updated_at": time.time(),
            "progress": progress,
            "summaries": summaries,
            "details": details,
        }
    )
    save_evaluation_job(job)
    return job


def read_evaluation_job(job_id: str):
    job = load_evaluation_job(job_id)
    if not job:
        return None
    return refresh_evaluation_job(job)


def list_evaluation_jobs(limit=20):
    rows = repo_list_evaluation_jobs(limit)
    jobs = []
    for row in rows:
        job = read_evaluation_job(row["job_id"])
        if job:
            jobs.append(
                {
                    "job_id": job["job_id"],
                    "status": job["status"],
                    "created_at": job["created_at"],
                    "updated_at": job["updated_at"],
                    "pairs": job.get("pairs"),
                    "positive_pairs": job.get("positive_pairs"),
                    "negative_pairs": job.get("negative_pairs"),
                }
            )
    return jobs
