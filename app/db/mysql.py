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


def ensure_column(conn, table_name: str, column_name: str, definition: str):
    row = conn.execute(
        """
        SELECT COUNT(*) AS count
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = %s
          AND TABLE_NAME = %s
          AND COLUMN_NAME = %s
        """,
        (MYSQL_CONFIG["database"], table_name, column_name),
    ).fetchone()
    if row and row["count"]:
        return
    conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")


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


def init_service_db():
    with db_connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS access_tokens (
                token_hash VARCHAR(128) PRIMARY KEY,
                access_key VARCHAR(128) NOT NULL,
                source_product VARCHAR(128) NOT NULL,
                expires_at REAL NOT NULL,
                created_at REAL NOT NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS compare_jobs (
                job_id VARCHAR(64) PRIMARY KEY,
                job_type VARCHAR(32) NOT NULL DEFAULT 'api_check',
                request_id VARCHAR(191) NOT NULL,
                source_product VARCHAR(128) NOT NULL,
                vendor_request_id VARCHAR(191),
                first_image_uri VARCHAR(1024) NOT NULL,
                second_image_uri VARCHAR(1024) NOT NULL,
                first_image_sha256 CHAR(64) NOT NULL,
                second_image_sha256 CHAR(64) NOT NULL,
                first_image_size_bytes INTEGER NOT NULL,
                second_image_size_bytes INTEGER NOT NULL,
                first_image_mime VARCHAR(64) NOT NULL,
                second_image_mime VARCHAR(64) NOT NULL,
                first_original_filename VARCHAR(512),
                second_original_filename VARCHAR(512),
                status VARCHAR(32) NOT NULL,
                error_code VARCHAR(64),
                error_message TEXT,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                UNIQUE KEY uk_source_request (source_product, request_id),
                KEY idx_job_type_status (job_type, status, created_at),
                KEY idx_status_created_at (status, created_at),
                KEY idx_vendor_request_id (vendor_request_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS compare_model_tasks (
                task_id VARCHAR(96) PRIMARY KEY,
                job_id VARCHAR(64) NOT NULL,
                model_config_id VARCHAR(128) NOT NULL,
                threshold VARCHAR(64),
                status VARCHAR(32) NOT NULL,
                worker_id VARCHAR(128),
                retry_count INTEGER NOT NULL DEFAULT 0,
                queued_at REAL NOT NULL,
                started_at REAL,
                lease_until REAL,
                finished_at REAL,
                error_code VARCHAR(64),
                error_message TEXT,
                UNIQUE KEY uk_job_model (job_id, model_config_id),
                KEY idx_lease_pickup (model_config_id, status, lease_until, queued_at),
                KEY idx_worker_running (worker_id, status, lease_until),
                KEY idx_job_status (job_id, status)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
        ensure_column(conn, "compare_jobs", "job_type", "VARCHAR(32) NOT NULL DEFAULT 'api_check' AFTER job_id")
        ensure_column(conn, "compare_model_tasks", "threshold", "VARCHAR(64) AFTER model_config_id")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS compare_model_results (
                result_id VARCHAR(96) PRIMARY KEY,
                task_id VARCHAR(96) NOT NULL UNIQUE,
                job_id VARCHAR(64) NOT NULL,
                model_config_id VARCHAR(128) NOT NULL,
                score REAL,
                distance REAL,
                score_direction VARCHAR(32),
                same_person INTEGER,
                decision_status VARCHAR(32) NOT NULL,
                threshold REAL,
                threshold_version VARCHAR(128),
                face_count_a INTEGER,
                face_count_b INTEGER,
                bbox_a_json JSON,
                bbox_b_json JSON,
                elapsed_ms INTEGER,
                image_download_elapsed_ms INTEGER,
                model_elapsed_ms INTEGER,
                result_submit_elapsed_ms INTEGER,
                raw_result_json JSON,
                created_at REAL NOT NULL,
                KEY idx_job_model (job_id, model_config_id),
                KEY idx_model_created_at (model_config_id, created_at)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS vendor_results (
                vendor_result_id VARCHAR(96) PRIMARY KEY,
                job_id VARCHAR(64) NOT NULL,
                vendor_name VARCHAR(128) NOT NULL,
                vendor_request_id VARCHAR(191) NOT NULL,
                vendor_status VARCHAR(64),
                vendor_score REAL,
                vendor_same_person INTEGER,
                raw_response_json JSON,
                created_at REAL NOT NULL,
                UNIQUE KEY uk_job_vendor_request (job_id, vendor_name, vendor_request_id),
                KEY idx_job_vendor (job_id, vendor_name),
                KEY idx_vendor_request_id (vendor_request_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS worker_credentials (
                worker_id VARCHAR(128) PRIMARY KEY,
                worker_name VARCHAR(256) NOT NULL,
                token_hash VARCHAR(128) NOT NULL,
                allowed_model_config_ids_json JSON NOT NULL,
                allowed_capabilities_json JSON NOT NULL,
                ip_allowlist_json JSON NOT NULL,
                status VARCHAR(32) NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                last_seen_at REAL,
                KEY idx_status_last_seen (status, last_seen_at)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
        ensure_column(conn, "worker_credentials", "allowed_capabilities_json", "JSON NULL AFTER allowed_model_config_ids_json")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS worker_heartbeats (
                worker_id VARCHAR(128) PRIMARY KEY,
                model_config_id VARCHAR(128) NOT NULL,
                runtime_version VARCHAR(128),
                model_version VARCHAR(128),
                status VARCHAR(32) NOT NULL,
                running_tasks INTEGER,
                cpu_usage REAL,
                memory_mb REAL,
                payload_json JSON NOT NULL,
                updated_at REAL NOT NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS service_jobs (
                task_id VARCHAR(96) PRIMARY KEY,
                service_type VARCHAR(64) NOT NULL,
                source_product VARCHAR(128) NOT NULL,
                request_id VARCHAR(191) NOT NULL,
                status VARCHAR(32) NOT NULL,
                raw_payload_json LONGTEXT,
                payload_hash CHAR(64) NOT NULL,
                assets_hash CHAR(64) NOT NULL,
                metadata_json JSON,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                UNIQUE KEY uk_service_request (source_product, request_id, service_type),
                KEY idx_service_status (service_type, status, created_at),
                KEY idx_source_request (source_product, request_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS service_assets (
                asset_id VARCHAR(96) PRIMARY KEY,
                task_id VARCHAR(96) NOT NULL,
                field_name VARCHAR(191) NOT NULL,
                position INTEGER NOT NULL,
                uri VARCHAR(1024) NOT NULL,
                sha256 CHAR(64) NOT NULL,
                mime VARCHAR(128) NOT NULL,
                size_bytes INTEGER NOT NULL,
                original_filename VARCHAR(512),
                created_at REAL NOT NULL,
                KEY idx_task_field (task_id, field_name, position),
                KEY idx_asset_sha (sha256)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS service_worker_tasks (
                worker_task_id VARCHAR(96) PRIMARY KEY,
                task_id VARCHAR(96) NOT NULL,
                capability VARCHAR(128) NOT NULL,
                status VARCHAR(32) NOT NULL,
                worker_id VARCHAR(128),
                retry_count INTEGER NOT NULL DEFAULT 0,
                queued_at REAL NOT NULL,
                started_at REAL,
                lease_until REAL,
                finished_at REAL,
                error_code VARCHAR(64),
                error_message TEXT,
                UNIQUE KEY uk_task_capability (task_id, capability),
                KEY idx_capability_pickup (capability, status, lease_until, queued_at),
                KEY idx_service_worker_running (worker_id, status, lease_until),
                KEY idx_task_status (task_id, status)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS official_results (
                official_result_id VARCHAR(96) PRIMARY KEY,
                task_id VARCHAR(96) NOT NULL,
                source_product VARCHAR(128) NOT NULL,
                request_id VARCHAR(191) NOT NULL,
                service_type VARCHAR(64) NOT NULL,
                official_status VARCHAR(64),
                official_elapsed_ms INTEGER,
                vendor_request_id VARCHAR(191),
                raw_result_json LONGTEXT NOT NULL,
                result_hash CHAR(64) NOT NULL,
                created_at REAL NOT NULL,
                UNIQUE KEY uk_official_service_request (source_product, request_id, service_type),
                KEY idx_official_task (task_id, created_at)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS worker_results (
                worker_result_id VARCHAR(96) PRIMARY KEY,
                worker_task_id VARCHAR(96) NOT NULL UNIQUE,
                task_id VARCHAR(96) NOT NULL,
                capability VARCHAR(128) NOT NULL,
                worker_id VARCHAR(128) NOT NULL,
                result_status VARCHAR(32) NOT NULL,
                elapsed_ms INTEGER,
                raw_result_json LONGTEXT NOT NULL,
                normalized_result_json LONGTEXT,
                created_at REAL NOT NULL,
                KEY idx_worker_result_task (task_id, created_at),
                KEY idx_worker_result_capability (capability, created_at)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS comparison_results (
                comparison_id VARCHAR(96) PRIMARY KEY,
                task_id VARCHAR(96) NOT NULL,
                service_type VARCHAR(64) NOT NULL,
                capability VARCHAR(128),
                official_result_id VARCHAR(96),
                worker_result_id VARCHAR(96),
                compare_status VARCHAR(32) NOT NULL,
                diff_json LONGTEXT,
                created_at REAL NOT NULL,
                KEY idx_comparison_task (task_id, created_at),
                KEY idx_compare_status (compare_status, created_at)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS pending_official_results (
                pending_id VARCHAR(96) PRIMARY KEY,
                source_product VARCHAR(128) NOT NULL,
                request_id VARCHAR(191) NOT NULL,
                service_type VARCHAR(64) NOT NULL,
                official_status VARCHAR(64),
                official_elapsed_ms INTEGER,
                vendor_request_id VARCHAR(191),
                raw_result_json LONGTEXT NOT NULL,
                result_hash CHAR(64) NOT NULL,
                created_at REAL NOT NULL,
                attached_task_id VARCHAR(96),
                attached_at REAL,
                UNIQUE KEY uk_pending_service_request (source_product, request_id, service_type),
                KEY idx_pending_attached (attached_task_id, attached_at)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
        seed_worker_credentials(conn)


def row_to_dict(row):
    return dict(row) if row else None


def load_compare_job(conn, job_id: str):
    return row_to_dict(conn.execute("SELECT * FROM compare_jobs WHERE job_id = %s", (job_id,)).fetchone())


def load_compare_job_by_request(conn, source_product: str, request_id: str):
    return row_to_dict(
        conn.execute(
            "SELECT * FROM compare_jobs WHERE source_product = %s AND request_id = %s",
            (source_product, request_id),
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
