import json
from typing import Any

from app.db.mysql import db_connect


def init_evaluation_db():
    with db_connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS evaluation_jobs (
                job_id VARCHAR(96) PRIMARY KEY,
                status VARCHAR(32) NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                positive_limit_per_group INTEGER NOT NULL,
                negative_limit_per_group INTEGER NOT NULL,
                pairs INTEGER,
                positive_pairs INTEGER,
                negative_pairs INTEGER,
                payload_json JSON NOT NULL,
                KEY idx_evaluation_jobs_updated_at (updated_at)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS evaluation_model_results (
                job_id VARCHAR(96) NOT NULL,
                config_id VARCHAR(128) NOT NULL,
                summary_json JSON NOT NULL,
                details_json JSON NOT NULL,
                PRIMARY KEY (job_id, config_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )


def save_evaluation_job(job: dict[str, Any]):
    with db_connect() as conn:
        conn.execute(
            """
            INSERT INTO evaluation_jobs (
                job_id, status, created_at, updated_at, positive_limit_per_group,
                negative_limit_per_group, pairs, positive_pairs, negative_pairs, payload_json
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                status=VALUES(status),
                updated_at=VALUES(updated_at),
                pairs=VALUES(pairs),
                positive_pairs=VALUES(positive_pairs),
                negative_pairs=VALUES(negative_pairs),
                payload_json=VALUES(payload_json)
            """,
            (
                job["job_id"],
                job["status"],
                job["created_at"],
                job["updated_at"],
                int(job.get("positive_limit_per_group", 0)),
                int(job.get("negative_limit_per_group", 0)),
                job.get("pairs"),
                job.get("positive_pairs"),
                job.get("negative_pairs"),
                json.dumps(job, ensure_ascii=False),
            ),
        )


def save_evaluation_model_result(job_id: str, config_id: str, summary: dict[str, Any], details: dict[str, Any]):
    with db_connect() as conn:
        conn.execute(
            """
            INSERT INTO evaluation_model_results (job_id, config_id, summary_json, details_json)
            VALUES (%s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                summary_json=VALUES(summary_json),
                details_json=VALUES(details_json)
            """,
            (
                job_id,
                config_id,
                json.dumps(summary, ensure_ascii=False),
                json.dumps(details, ensure_ascii=False),
            ),
        )


def load_evaluation_job(job_id: str):
    with db_connect() as conn:
        row = conn.execute("SELECT payload_json FROM evaluation_jobs WHERE job_id = %s", (job_id,)).fetchone()
    if not row:
        return None
    payload = row["payload_json"]
    return payload if isinstance(payload, dict) else json.loads(payload)


def list_evaluation_jobs(limit=20):
    with db_connect() as conn:
        rows = conn.execute(
            """
            SELECT job_id, status, created_at, updated_at, pairs, positive_pairs, negative_pairs
            FROM evaluation_jobs
            ORDER BY updated_at DESC
            LIMIT %s
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]
