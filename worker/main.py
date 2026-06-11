import argparse
import json
import os
import time
from urllib import request
from urllib.error import URLError

from app.core.face_compare import run_compare_paths


def parse_args():
    parser = argparse.ArgumentParser(description="Run one face comparison model worker.")
    parser.add_argument("--api-base-url", default=os.environ.get("FACE_API_BASE_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--worker-id", default=os.environ.get("FACE_WORKER_ID", "dev-worker-buffalo-l"))
    parser.add_argument("--worker-token", default=os.environ.get("FACE_WORKER_TOKEN", "dev-worker-token-change-me-32-bytes"))
    parser.add_argument("--model-config-id", default=os.environ.get("FACE_WORKER_MODEL_CONFIG_ID", "buffalo_l"))
    parser.add_argument("--capability", default=os.environ.get("FACE_WORKER_CAPABILITY"))
    parser.add_argument("--poll-seconds", type=float, default=float(os.environ.get("FACE_WORKER_POLL_SECONDS", "2")))
    parser.add_argument("--limit", type=int, default=int(os.environ.get("FACE_WORKER_LEASE_LIMIT", "1")))
    args = parser.parse_args()
    if not args.capability:
        args.capability = f"face_compare.{args.model_config_id}"
    return args


def post_json(api_base_url: str, path: str, payload: dict, worker_id: str, worker_token: str):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(
        f"{api_base_url.rstrip('/')}{path}",
        data=body,
        headers={
            "Content-Type": "application/json",
            "X-WORKER-ID": worker_id,
            "X-WORKER-TOKEN": worker_token,
        },
        method="POST",
    )
    with request.urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def lease_tasks(args):
    tasks = post_json(
        args.api_base_url,
        "/internal/tasks/lease",
        {
            "workerId": args.worker_id,
            "capability": args.capability,
            "limit": args.limit,
        },
        args.worker_id,
        args.worker_token,
    ).get("tasks", [])
    if tasks:
        return tasks
    return post_json(
        args.api_base_url,
        "/internal/model-tasks/lease",
        {
            "workerId": args.worker_id,
            "modelConfigId": args.model_config_id,
            "limit": args.limit,
        },
        args.worker_id,
        args.worker_token,
    ).get("tasks", [])


def result_payload(task: dict, compare_result: dict, elapsed_ms: int):
    inner = compare_result["result"]
    same_person = inner.get("same_person")
    capability = str(task.get("capability") or "")
    model_config_id = task.get("modelConfigId") or (capability.split(".", 1)[1] if "." in capability else "")
    decision_status = "uncertain"
    if same_person is True:
        decision_status = "same_person"
    elif same_person is False:
        decision_status = "different_person"
    return {
        "status": "completed",
        "modelConfigId": model_config_id,
        "score": inner.get("score"),
        "distance": inner.get("distance"),
        "scoreDirection": compare_result["config"].get("score_direction"),
        "samePerson": same_person,
        "decisionStatus": decision_status,
        "threshold": inner.get("threshold"),
        "thresholdVersion": inner.get("threshold_version"),
        "elapsedMs": elapsed_ms,
        "rawResult": compare_result,
        "normalizedResult": {"samePerson": same_person, "score": inner.get("score")},
    }


def submit_result(args, task: dict, payload: dict):
    if "workerTaskId" in task:
        return post_json(
            args.api_base_url,
            f"/internal/tasks/{task['workerTaskId']}/result",
            {"workerId": args.worker_id, "capability": task.get("capability") or args.capability, **payload},
            args.worker_id,
            args.worker_token,
        )
    return post_json(
        args.api_base_url,
        f"/internal/model-tasks/{task['taskId']}/result",
        {"workerId": args.worker_id, **payload},
        args.worker_id,
        args.worker_token,
    )


def send_heartbeat(args, status="healthy", running_tasks=0):
    return post_json(
        args.api_base_url,
        "/internal/workers/heartbeat",
        {
            "workerId": args.worker_id,
            "modelConfigId": args.model_config_id,
            "capability": args.capability,
            "status": status,
            "runningTasks": running_tasks,
        },
        args.worker_id,
        args.worker_token,
    )


def process_task(args, task: dict):
    started = time.perf_counter()
    try:
        compare_result = run_compare_paths(
            str(task.get("capability") or args.capability).split(".", 1)[1] if "workerTaskId" in task and "." in str(task.get("capability") or args.capability) else args.model_config_id,
            task["firstImageUrl"],
            task["secondImageUrl"],
            str(task.get("threshold") or ""),
        )
        elapsed_ms = round((time.perf_counter() - started) * 1000)
        submit_result(args, task, result_payload(task, compare_result, elapsed_ms))
    except Exception as exc:
        elapsed_ms = round((time.perf_counter() - started) * 1000)
        submit_result(
            args,
            task,
            {
                "status": "failed",
                "modelConfigId": task.get("modelConfigId", args.model_config_id),
                "errorCode": "MODEL_RUNTIME_ERROR",
                "errorMessage": str(exc),
                "elapsedMs": elapsed_ms,
            },
        )


def main():
    args = parse_args()
    print(f"worker starting id={args.worker_id} capability={args.capability} model={args.model_config_id} api={args.api_base_url}", flush=True)
    while True:
        try:
            send_heartbeat(args)
            tasks = lease_tasks(args)
            if not tasks:
                time.sleep(args.poll_seconds)
                continue
            send_heartbeat(args, running_tasks=len(tasks))
            for task in tasks:
                process_task(args, task)
        except (URLError, TimeoutError, OSError) as exc:
            print(f"worker loop error: {exc}", flush=True)
            time.sleep(args.poll_seconds)


if __name__ == "__main__":
    main()
