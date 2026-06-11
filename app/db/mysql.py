import hashlib
import json
import time
from datetime import datetime, timezone

import pymysql
from pymysql.cursors import DictCursor

from app.config import MYSQL_CONFIG, WORKER_CREDENTIALS


def now_ts():
    return time.time()


def utc_iso(timestamp: float | None = None):
    value = now_ts() if timestamp is None else timestamp
    return datetime.fromtimestamp(value, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def token_hash(token: str):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class MysqlConnection:
    def __init__(self):
        self.conn = pymysql.connect(
            **MYSQL_CONFIG,
            autocommit=False,
            cursorclass=DictCursor,
        )

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        if exc_type:
            self.conn.rollback()
        else:
            self.conn.commit()
        self.conn.close()

    def execute(self, sql, params=None):
        cursor = self.conn.cursor()
        cursor.execute(sql, params)
        return cursor


def db_connect():
    return MysqlConnection()


def seed_worker_credentials(conn):
    now = now_ts()
    for credential in WORKER_CREDENTIALS:
        conn.execute(
            """
            INSERT INTO worker_credentials (
                worker_id, worker_name, token_hash, allowed_model_config_ids_json,
                allowed_capabilities_json, ip_allowlist_json, status, created_at, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                worker_name=VALUES(worker_name),
                token_hash=VALUES(token_hash),
                allowed_model_config_ids_json=VALUES(allowed_model_config_ids_json),
                allowed_capabilities_json=VALUES(allowed_capabilities_json),
                ip_allowlist_json=VALUES(ip_allowlist_json),
                status=VALUES(status),
                updated_at=VALUES(updated_at)
            """,
            (
                credential["worker_id"],
                credential.get("worker_name") or credential["worker_id"],
                token_hash(credential["worker_token"]),
                json.dumps(credential["allowed_model_config_ids"], ensure_ascii=False),
                json.dumps(credential.get("allowed_capabilities", []), ensure_ascii=False),
                json.dumps(credential.get("ip_allowlist", ["*"]), ensure_ascii=False),
                credential.get("status", "enabled"),
                now,
                now,
            ),
        )


def sync_worker_credentials():
    with db_connect() as conn:
        seed_worker_credentials(conn)


def row_to_dict(row):
    return dict(row) if row else None


def load_compare_job(conn, job_id: str):
    return row_to_dict(conn.execute("SELECT * FROM compare_jobs WHERE job_id = %s", (job_id,)).fetchone())


def load_compare_job_by_request(conn, api_id: str, request_id: str):
    return row_to_dict(
        conn.execute(
            "SELECT * FROM compare_jobs WHERE api_id = %s AND request_id = %s",
            (api_id, request_id),
        ).fetchone()
    )


def load_compare_tasks(conn, job_id: str):
    return [
        dict(row)
        for row in conn.execute(
            "SELECT * FROM compare_model_tasks WHERE job_id = %s ORDER BY queued_at, task_id",
            (job_id,),
        ).fetchall()
    ]


def load_compare_results(conn, job_id: str):
    return [
        dict(row)
        for row in conn.execute(
            "SELECT * FROM compare_model_results WHERE job_id = %s ORDER BY created_at, task_id",
            (job_id,),
        ).fetchall()
    ]
