import json

from app.db.mysql import db_connect, load_compare_job, load_compare_job_by_request, load_compare_results, load_compare_tasks, now_ts, row_to_dict


def get_api_client(access_key: str):
    with db_connect() as conn:
        row = conn.execute("SELECT * FROM api_clients WHERE access_key = %s", (access_key,)).fetchone()
    return row_to_dict(row)


def create_access_token(token_hash_value: str, access_key: str, api_id: str, expires_at: float):
    with db_connect() as conn:
        conn.execute(
            """
            INSERT INTO access_tokens (token_hash, access_key, api_id, expires_at, created_at)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (token_hash_value, access_key, api_id, expires_at, now_ts()),
        )


def get_access_token(token_hash_value: str):
    with db_connect() as conn:
        row = conn.execute(
            """
            SELECT
                access_tokens.access_key,
                access_tokens.api_id,
                access_tokens.expires_at,
                api_clients.status AS client_status
            FROM access_tokens
            INNER JOIN api_clients ON api_clients.access_key = access_tokens.access_key
            WHERE token_hash = %s
            """,
            (token_hash_value,),
        ).fetchone()
    return row_to_dict(row)


def get_worker_credential(worker_id: str):
    with db_connect() as conn:
        row = conn.execute("SELECT * FROM worker_credentials WHERE worker_id = %s", (worker_id,)).fetchone()
    return row_to_dict(row)


def has_active_worker_lease(task: dict | None, worker_id: str):
    if not task or task.get("status") != "running" or task.get("worker_id") != worker_id or not task.get("lease_until"):
        return False
    try:
        return float(task["lease_until"]) >= now_ts()
    except (TypeError, ValueError):
        return False


def get_job(job_id: str):
    with db_connect() as conn:
        return load_compare_job(conn, job_id)


def get_job_by_request(api_id: str, request_id: str):
    with db_connect() as conn:
        return load_compare_job_by_request(conn, api_id, request_id)


def get_job_tasks(job_id: str):
    with db_connect() as conn:
        return load_compare_tasks(conn, job_id)


def get_job_results(job_id: str):
    with db_connect() as conn:
        return load_compare_results(conn, job_id)


def get_service_job(task_id: str):
    with db_connect() as conn:
        row = conn.execute("SELECT * FROM service_jobs WHERE task_id = %s", (task_id,)).fetchone()
    return row_to_dict(row)


def get_service_job_by_request(api_id: str, request_id: str, service_type: str):
    with db_connect() as conn:
        row = conn.execute(
            """
            SELECT * FROM service_jobs
            WHERE api_id = %s AND request_id = %s AND service_type = %s
            """,
            (api_id, request_id, service_type),
        ).fetchone()
    return row_to_dict(row)


def get_service_assets(task_id: str):
    with db_connect() as conn:
        return [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM service_assets WHERE task_id = %s ORDER BY field_name, position, asset_id",
                (task_id,),
            ).fetchall()
        ]


def get_service_worker_tasks(task_id: str):
    with db_connect() as conn:
        return [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM service_worker_tasks WHERE task_id = %s ORDER BY queued_at, worker_task_id",
                (task_id,),
            ).fetchall()
        ]


def get_official_results(task_id: str):
    with db_connect() as conn:
        return [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM official_results WHERE task_id = %s ORDER BY created_at, official_result_id",
                (task_id,),
            ).fetchall()
        ]


def get_worker_results(task_id: str):
    with db_connect() as conn:
        return [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM worker_results WHERE task_id = %s ORDER BY created_at, worker_result_id",
                (task_id,),
            ).fetchall()
        ]


def get_comparison_results(task_id: str):
    with db_connect() as conn:
        return [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM comparison_results WHERE task_id = %s ORDER BY created_at, comparison_id",
                (task_id,),
            ).fetchall()
        ]


def create_service_job_bundle(job: dict, assets: list[dict], worker_tasks: list[dict]):
    with db_connect() as conn:
        conn.execute("START TRANSACTION")
        conn.execute(
            """
            INSERT INTO service_jobs (
                task_id, service_type, api_id, request_id, status,
                raw_payload_json, payload_hash, assets_hash, metadata_json, created_at, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                job["task_id"],
                job["service_type"],
                job["api_id"],
                job["request_id"],
                job["status"],
                job.get("raw_payload_json"),
                job["payload_hash"],
                job["assets_hash"],
                job.get("metadata_json"),
                job["created_at"],
                job["updated_at"],
            ),
        )
        for asset in assets:
            conn.execute(
                """
                INSERT INTO service_assets (
                    asset_id, task_id, field_name, position, uri, sha256, mime,
                    size_bytes, original_filename, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    asset["asset_id"],
                    asset["task_id"],
                    asset["field_name"],
                    asset["position"],
                    asset["uri"],
                    asset["sha256"],
                    asset["mime"],
                    asset["size_bytes"],
                    asset.get("original_filename"),
                    asset["created_at"],
                ),
            )
        for task in worker_tasks:
            conn.execute(
                """
                INSERT INTO service_worker_tasks (
                    worker_task_id, task_id, capability, status, queued_at
                ) VALUES (%s, %s, %s, %s, %s)
                """,
                (task["worker_task_id"], task["task_id"], task["capability"], task["status"], task["queued_at"]),
            )


def get_pending_official_result(api_id: str, request_id: str, service_type: str):
    with db_connect() as conn:
        row = conn.execute(
            """
            SELECT * FROM pending_official_results
            WHERE api_id = %s AND request_id = %s AND service_type = %s AND attached_task_id IS NULL
            """,
            (api_id, request_id, service_type),
        ).fetchone()
    return row_to_dict(row)


def insert_official_result(result: dict):
    with db_connect() as conn:
        conn.execute(
            """
            INSERT INTO official_results (
                official_result_id, task_id, api_id, request_id, service_type,
                official_status, official_elapsed_ms, vendor_request_id,
                raw_result_json, result_hash, created_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE official_result_id = official_result_id
            """,
            (
                result["official_result_id"],
                result["task_id"],
                result["api_id"],
                result["request_id"],
                result["service_type"],
                result.get("official_status"),
                result.get("official_elapsed_ms"),
                result.get("vendor_request_id"),
                result["raw_result_json"],
                result["result_hash"],
                result["created_at"],
            ),
        )
        row = conn.execute(
            """
            SELECT * FROM official_results
            WHERE api_id = %s AND request_id = %s AND service_type = %s
            """,
            (result["api_id"], result["request_id"], result["service_type"]),
        ).fetchone()
    return row_to_dict(row)


def save_pending_official_result(result: dict):
    with db_connect() as conn:
        conn.execute(
            """
            INSERT INTO pending_official_results (
                pending_id, api_id, request_id, service_type, official_status,
                official_elapsed_ms, vendor_request_id, raw_result_json, result_hash, created_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE pending_id = pending_id
            """,
            (
                result["pending_id"],
                result["api_id"],
                result["request_id"],
                result["service_type"],
                result.get("official_status"),
                result.get("official_elapsed_ms"),
                result.get("vendor_request_id"),
                result["raw_result_json"],
                result["result_hash"],
                result["created_at"],
            ),
        )
        row = conn.execute(
            """
            SELECT * FROM pending_official_results
            WHERE api_id = %s AND request_id = %s AND service_type = %s
            """,
            (result["api_id"], result["request_id"], result["service_type"]),
        ).fetchone()
    return row_to_dict(row)


def mark_pending_official_attached(pending_id: str, task_id: str):
    with db_connect() as conn:
        conn.execute(
            """
            UPDATE pending_official_results
            SET attached_task_id = %s, attached_at = %s
            WHERE pending_id = %s AND attached_task_id IS NULL
            """,
            (task_id, now_ts(), pending_id),
        )


def recycle_expired_service_leases(conn):
    now = now_ts()
    conn.execute(
        """
        UPDATE service_worker_tasks
        SET status = 'queued',
            worker_id = NULL,
            lease_until = NULL,
            retry_count = retry_count + 1
        WHERE status = 'running'
          AND lease_until < %s
          AND retry_count < 3
        """,
        (now,),
    )
    conn.execute(
        """
        UPDATE service_worker_tasks
        SET status = 'failed',
            error_code = 'TASK_LEASE_EXPIRED',
            error_message = 'task lease expired after max retries',
            finished_at = %s
        WHERE status = 'running'
          AND lease_until < %s
          AND retry_count >= 3
        """,
        (now, now),
    )


def aggregate_service_job_status(conn, task_id: str):
    rows = conn.execute("SELECT status FROM service_worker_tasks WHERE task_id = %s", (task_id,)).fetchall()
    statuses = [row["status"] for row in rows]
    if not statuses:
        status = "failed"
    elif all(value == "queued" for value in statuses):
        status = "queued"
    elif all(value == "completed" for value in statuses):
        status = "completed"
    elif all(value == "failed" for value in statuses):
        status = "failed"
    elif any(value == "completed" for value in statuses) and any(value == "failed" for value in statuses):
        status = "partial_failed"
    else:
        status = "running"
    conn.execute("UPDATE service_jobs SET status = %s, updated_at = %s WHERE task_id = %s", (status, now_ts(), task_id))
    return status


def lease_service_worker_tasks(capability: str, worker_id: str, limit: int, lease_until: float):
    rows = []
    with db_connect() as conn:
        conn.execute("START TRANSACTION")
        recycle_expired_service_leases(conn)
        picked = conn.execute(
            """
            SELECT * FROM service_worker_tasks
            WHERE capability = %s AND status = 'queued'
            ORDER BY queued_at
            LIMIT %s
            FOR UPDATE SKIP LOCKED
            """,
            (capability, limit),
        ).fetchall()
        task_ids = [row["worker_task_id"] for row in picked]
        if task_ids:
            placeholders = ",".join("%s" for _ in task_ids)
            conn.execute(
                f"""
                UPDATE service_worker_tasks
                SET status = 'running',
                    worker_id = %s,
                    started_at = COALESCE(started_at, %s),
                    lease_until = %s
                WHERE worker_task_id IN ({placeholders})
                """,
                (worker_id, now_ts(), lease_until, *task_ids),
            )
            for row in picked:
                updated = dict(row)
                updated.update({"status": "running", "worker_id": worker_id, "lease_until": lease_until})
                job = row_to_dict(conn.execute("SELECT * FROM service_jobs WHERE task_id = %s", (row["task_id"],)).fetchone())
                assets = [
                    dict(asset)
                    for asset in conn.execute(
                        "SELECT * FROM service_assets WHERE task_id = %s ORDER BY field_name, position, asset_id",
                        (row["task_id"],),
                    ).fetchall()
                ]
                rows.append((updated, job, assets))
                aggregate_service_job_status(conn, row["task_id"])
    return rows


def get_service_worker_task(worker_task_id: str):
    with db_connect() as conn:
        row = conn.execute("SELECT * FROM service_worker_tasks WHERE worker_task_id = %s", (worker_task_id,)).fetchone()
    return row_to_dict(row)


def complete_service_worker_task(worker_task_id: str, result: dict):
    with db_connect() as conn:
        conn.execute("START TRANSACTION")
        task = row_to_dict(conn.execute("SELECT * FROM service_worker_tasks WHERE worker_task_id = %s FOR UPDATE", (worker_task_id,)).fetchone())
        if not has_active_worker_lease(task, result["worker_id"]):
            return None
        conn.execute(
            """
            INSERT INTO worker_results (
                worker_result_id, worker_task_id, task_id, capability, worker_id,
                result_status, elapsed_ms, raw_result_json, normalized_result_json, created_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE worker_result_id = worker_result_id
            """,
            (
                result["worker_result_id"],
                worker_task_id,
                task["task_id"],
                task["capability"],
                result["worker_id"],
                result["result_status"],
                result.get("elapsed_ms"),
                result["raw_result_json"],
                result.get("normalized_result_json"),
                result["created_at"],
            ),
        )
        if result["result_status"] == "completed":
            conn.execute(
                """
                UPDATE service_worker_tasks
                SET status = 'completed', finished_at = %s, error_code = NULL, error_message = NULL
                WHERE worker_task_id = %s
                """,
                (now_ts(), worker_task_id),
            )
        else:
            conn.execute(
                """
                UPDATE service_worker_tasks
                SET status = 'failed', finished_at = %s, error_code = %s, error_message = %s
                WHERE worker_task_id = %s
                """,
                (now_ts(), result.get("error_code") or "WORKER_RESULT_FAILED", result.get("error_message") or "worker task failed", worker_task_id),
            )
        aggregate_service_job_status(conn, task["task_id"])
        row = conn.execute("SELECT * FROM worker_results WHERE worker_task_id = %s", (worker_task_id,)).fetchone()
    return row_to_dict(row)


def comparison_exists(task_id: str, official_result_id: str | None, worker_result_id: str | None, compare_status: str):
    with db_connect() as conn:
        row = conn.execute(
            """
            SELECT comparison_id FROM comparison_results
            WHERE task_id = %s
              AND compare_status = %s
              AND official_result_id <=> %s
              AND worker_result_id <=> %s
            """,
            (task_id, compare_status, official_result_id, worker_result_id),
        ).fetchone()
    return bool(row)


def insert_comparison_result(result: dict):
    with db_connect() as conn:
        conn.execute(
            """
            INSERT INTO comparison_results (
                comparison_id, task_id, service_type, capability, official_result_id,
                worker_result_id, compare_status, diff_json, created_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                result["comparison_id"],
                result["task_id"],
                result["service_type"],
                result.get("capability"),
                result.get("official_result_id"),
                result.get("worker_result_id"),
                result["compare_status"],
                result.get("diff_json"),
                result["created_at"],
            ),
        )


def create_compare_job(job: dict, tasks: list[dict]):
    with db_connect() as conn:
        conn.execute("START TRANSACTION")
        conn.execute(
            """
            INSERT INTO compare_jobs (
                job_id, job_type, request_id, api_id, vendor_request_id,
                first_image_uri, second_image_uri, first_image_sha256, second_image_sha256,
                first_image_size_bytes, second_image_size_bytes, first_image_mime, second_image_mime,
                first_original_filename, second_original_filename, status, created_at, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                job["job_id"],
                job["job_type"],
                job["request_id"],
                job["api_id"],
                job.get("vendor_request_id"),
                job["first_image_uri"],
                job["second_image_uri"],
                job["first_image_sha256"],
                job["second_image_sha256"],
                job["first_image_size_bytes"],
                job["second_image_size_bytes"],
                job["first_image_mime"],
                job["second_image_mime"],
                job["first_original_filename"],
                job["second_original_filename"],
                job["status"],
                job["created_at"],
                job["updated_at"],
            ),
        )
        for task in tasks:
            conn.execute(
                """
                INSERT INTO compare_model_tasks (task_id, job_id, model_config_id, threshold, status, queued_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (task["task_id"], task["job_id"], task["model_config_id"], task.get("threshold"), task["status"], task["queued_at"]),
            )


def aggregate_job_status(conn, job_id: str):
    rows = conn.execute("SELECT status FROM compare_model_tasks WHERE job_id = %s", (job_id,)).fetchall()
    statuses = [row["status"] for row in rows]
    if not statuses:
        status = "failed"
    elif all(value == "queued" for value in statuses):
        status = "queued"
    elif all(value == "completed" for value in statuses):
        status = "completed"
    elif all(value == "failed" for value in statuses):
        status = "failed"
    elif any(value == "completed" for value in statuses) and any(value == "failed" for value in statuses):
        status = "partial_failed"
    else:
        status = "running"
    conn.execute("UPDATE compare_jobs SET status = %s, updated_at = %s WHERE job_id = %s", (status, now_ts(), job_id))
    return status


def mark_task_running(task_id: str):
    with db_connect() as conn:
        task = row_to_dict(conn.execute("SELECT job_id FROM compare_model_tasks WHERE task_id = %s", (task_id,)).fetchone())
        if not task:
            return
        conn.execute(
            """
            UPDATE compare_model_tasks
            SET status = 'running', started_at = COALESCE(started_at, %s), lease_until = %s
            WHERE task_id = %s
            """,
            (now_ts(), now_ts() + 300, task_id),
        )
        aggregate_job_status(conn, task["job_id"])


def complete_task_with_result(task_id: str, result: dict):
    with db_connect() as conn:
        conn.execute("START TRANSACTION")
        worker_id = result.get("worker_id")
        select_sql = "SELECT * FROM compare_model_tasks WHERE task_id = %s"
        if worker_id:
            select_sql += " FOR UPDATE"
        task = row_to_dict(conn.execute(select_sql, (task_id,)).fetchone())
        if not task:
            return
        if worker_id and not has_active_worker_lease(task, worker_id):
            return None
        existing = conn.execute("SELECT task_id FROM compare_model_results WHERE task_id = %s", (task_id,)).fetchone()
        if not existing:
            conn.execute(
                """
                INSERT INTO compare_model_results (
                    result_id, task_id, job_id, model_config_id, score, distance, score_direction,
                    same_person, decision_status, threshold, threshold_version, face_count_a, face_count_b,
                    bbox_a_json, bbox_b_json, elapsed_ms, image_download_elapsed_ms, model_elapsed_ms,
                    result_submit_elapsed_ms, raw_result_json, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    result["result_id"],
                    task_id,
                    task["job_id"],
                    task["model_config_id"],
                    result.get("score"),
                    result.get("distance"),
                    result.get("score_direction"),
                    result.get("same_person"),
                    result["decision_status"],
                    result.get("threshold"),
                    result.get("threshold_version"),
                    result.get("face_count_a"),
                    result.get("face_count_b"),
                    result.get("bbox_a_json"),
                    result.get("bbox_b_json"),
                    result.get("elapsed_ms"),
                    result.get("image_download_elapsed_ms"),
                    result.get("model_elapsed_ms"),
                    result.get("result_submit_elapsed_ms"),
                    result.get("raw_result_json"),
                    result["created_at"],
                ),
            )
        conn.execute(
            "UPDATE compare_model_tasks SET status = 'completed', finished_at = %s, error_code = NULL, error_message = NULL WHERE task_id = %s",
            (now_ts(), task_id),
        )
        aggregate_job_status(conn, task["job_id"])
        return task


def fail_task(task_id: str, error_message: str, error_code="MODEL_RUNTIME_ERROR", worker_id: str | None = None):
    with db_connect() as conn:
        conn.execute("START TRANSACTION")
        select_sql = "SELECT * FROM compare_model_tasks WHERE task_id = %s"
        if worker_id:
            select_sql += " FOR UPDATE"
        task = row_to_dict(conn.execute(select_sql, (task_id,)).fetchone())
        if not task:
            return
        if worker_id and not has_active_worker_lease(task, worker_id):
            return None
        now = now_ts()
        conn.execute(
            "UPDATE compare_model_tasks SET status = 'failed', error_code = %s, error_message = %s, finished_at = %s WHERE task_id = %s",
            (error_code, error_message, now, task_id),
        )
        aggregate_job_status(conn, task["job_id"])
        return task


def save_vendor_result(job_id: str, payload: dict, vendor_result_id: str):
    with db_connect() as conn:
        conn.execute(
            """
            INSERT INTO vendor_results (
                vendor_result_id, job_id, vendor_name, vendor_request_id,
                vendor_status, vendor_score, vendor_same_person, raw_response_json, created_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE vendor_result_id = vendor_result_id
            """,
            (
                vendor_result_id,
                job_id,
                payload["vendorName"],
                payload["vendorRequestId"],
                payload.get("vendorStatus"),
                payload.get("vendorScore"),
                int(bool(payload["vendorSamePerson"])) if "vendorSamePerson" in payload else None,
                json.dumps(payload.get("rawResponse", {}), ensure_ascii=False),
                now_ts(),
            ),
        )


def recycle_expired_leases(conn):
    now = now_ts()
    conn.execute(
        """
        UPDATE compare_model_tasks
        SET status = 'queued',
            worker_id = NULL,
            lease_until = NULL,
            retry_count = retry_count + 1
        WHERE status = 'running'
          AND lease_until < %s
          AND retry_count < 3
        """,
        (now,),
    )
    conn.execute(
        """
        UPDATE compare_model_tasks
        SET status = 'failed',
            error_code = 'TASK_LEASE_EXPIRED',
            error_message = 'task lease expired after max retries',
            finished_at = %s
        WHERE status = 'running'
          AND lease_until < %s
          AND retry_count >= 3
        """,
        (now, now),
    )


def lease_tasks(model_config_id: str, worker_id: str, limit: int, lease_until: float):
    tasks = []
    with db_connect() as conn:
        conn.execute("START TRANSACTION")
        recycle_expired_leases(conn)
        rows = conn.execute(
            """
            SELECT * FROM compare_model_tasks
            WHERE model_config_id = %s
              AND status = 'queued'
            ORDER BY queued_at
            LIMIT %s
            FOR UPDATE SKIP LOCKED
            """,
            (model_config_id, limit),
        ).fetchall()
        task_ids = [row["task_id"] for row in rows]
        if task_ids:
            placeholders = ",".join("%s" for _ in task_ids)
            conn.execute(
                f"""
                UPDATE compare_model_tasks
                SET status = 'running',
                    worker_id = %s,
                    started_at = COALESCE(started_at, %s),
                    lease_until = %s
                WHERE task_id IN ({placeholders})
                """,
                (worker_id, now_ts(), lease_until, *task_ids),
            )
            for row in rows:
                job = load_compare_job(conn, row["job_id"])
                updated = dict(row)
                updated.update({"status": "running", "worker_id": worker_id, "lease_until": lease_until})
                tasks.append((updated, job))
                aggregate_job_status(conn, row["job_id"])
    return tasks


def get_task(task_id: str):
    with db_connect() as conn:
        row = conn.execute("SELECT * FROM compare_model_tasks WHERE task_id = %s", (task_id,)).fetchone()
    return row_to_dict(row)


def renew_task_lease(task_id: str, lease_until: float):
    with db_connect() as conn:
        conn.execute("UPDATE compare_model_tasks SET lease_until = %s WHERE task_id = %s", (lease_until, task_id))


def upsert_worker_heartbeat(worker_id: str, model_config_id: str, payload: dict):
    now = now_ts()
    with db_connect() as conn:
        conn.execute(
            """
            INSERT INTO worker_heartbeats (
                worker_id, model_config_id, runtime_version, model_version, status,
                running_tasks, cpu_usage, memory_mb, payload_json, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                model_config_id=VALUES(model_config_id),
                runtime_version=VALUES(runtime_version),
                model_version=VALUES(model_version),
                status=VALUES(status),
                running_tasks=VALUES(running_tasks),
                cpu_usage=VALUES(cpu_usage),
                memory_mb=VALUES(memory_mb),
                payload_json=VALUES(payload_json),
                updated_at=VALUES(updated_at)
            """,
            (
                worker_id,
                model_config_id,
                payload.get("runtimeVersion"),
                payload.get("modelVersion"),
                payload.get("status", "healthy"),
                payload.get("runningTasks"),
                payload.get("cpuUsage"),
                payload.get("memoryMb"),
                json.dumps(payload, ensure_ascii=False),
                now,
            ),
        )
        conn.execute("UPDATE worker_credentials SET last_seen_at = %s, updated_at = %s WHERE worker_id = %s", (now, now, worker_id))
