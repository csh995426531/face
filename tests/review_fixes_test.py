import unittest
import sys
import types
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from fastapi import HTTPException
except ModuleNotFoundError:
    fastapi = types.ModuleType("fastapi")

    class HTTPException(Exception):
        def __init__(self, status_code, detail=None):
            super().__init__(detail)
            self.status_code = status_code
            self.detail = detail

    fastapi.HTTPException = HTTPException
    fastapi.UploadFile = object
    sys.modules["fastapi"] = fastapi

if "cv2" not in sys.modules:
    sys.modules["cv2"] = types.ModuleType("cv2")

if "pymysql" not in sys.modules:
    pymysql = types.ModuleType("pymysql")
    cursors = types.ModuleType("pymysql.cursors")
    cursors.DictCursor = object
    pymysql.cursors = cursors
    pymysql.connect = lambda *args, **kwargs: None
    sys.modules["pymysql"] = pymysql
    sys.modules["pymysql.cursors"] = cursors

import app.services.service_jobs as jobs
import app.repositories.service as repo


class FakeCursor:
    def __init__(self, one=None, all_rows=None):
        self.one = one
        self.all_rows = all_rows or []

    def fetchone(self):
        return self.one

    def fetchall(self):
        return self.all_rows


class FakeConnection:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        if "FROM service_worker_tasks" in sql and "SELECT *" in sql:
            return FakeCursor(self.rows.get("service_worker_task"))
        if "FROM compare_model_tasks" in sql and "SELECT *" in sql:
            return FakeCursor(self.rows.get("compare_model_task"))
        if "FROM worker_results" in sql and "SELECT *" in sql:
            return FakeCursor(self.rows.get("worker_result"))
        if "SELECT status FROM service_worker_tasks" in sql:
            return FakeCursor(all_rows=[])
        if "SELECT status FROM compare_model_tasks" in sql:
            return FakeCursor(all_rows=[])
        return FakeCursor()

    def sql_text(self):
        return "\n".join(sql for sql, _params in self.calls)


class WorkerLeaseContractTest(unittest.TestCase):
    def test_legacy_worker_result_requires_current_lease_holder(self):
        task = {
            "task_id": "ft_test",
            "model_config_id": "buffalo_l",
            "status": "running",
            "worker_id": "worker-a",
            "lease_until": jobs.now_ts() + 60,
        }

        with patch.object(jobs, "get_task", return_value=task):
            with self.assertRaises(HTTPException) as raised:
                jobs.complete_worker_task(
                    "ft_test",
                    "worker-b",
                    {"status": "completed", "modelConfigId": "buffalo_l", "samePerson": True},
                )

        self.assertEqual(raised.exception.status_code, 403)
        self.assertEqual(raised.exception.detail["code"], "WORKER_AUTH_FAILED")

    def test_generic_worker_result_rejects_lease_lost_between_service_and_repository(self):
        task = {
            "worker_task_id": "swt_test",
            "task_id": "sj_test",
            "capability": "face_compare.buffalo_l",
            "status": "running",
            "worker_id": "worker-a",
            "lease_until": jobs.now_ts() + 60,
        }

        with (
            patch.object(jobs, "get_service_worker_task", return_value=task),
            patch.object(jobs, "repo_complete_service_worker_task", return_value=None),
        ):
            with self.assertRaises(HTTPException) as raised:
                jobs.complete_generic_worker_task(
                    "swt_test",
                    "worker-a",
                    {"status": "completed", "rawResult": {"ok": True}},
                )

        self.assertEqual(raised.exception.status_code, 403)
        self.assertEqual(raised.exception.detail["code"], "WORKER_AUTH_FAILED")

    def test_legacy_worker_result_rejects_lease_lost_between_service_and_repository(self):
        task = {
            "task_id": "ft_test",
            "model_config_id": "buffalo_l",
            "status": "running",
            "worker_id": "worker-a",
            "lease_until": jobs.now_ts() + 60,
        }

        with (
            patch.object(jobs, "get_task", return_value=task),
            patch.object(jobs, "repo_complete_task_with_result", return_value=None),
        ):
            with self.assertRaises(HTTPException) as raised:
                jobs.complete_worker_task(
                    "ft_test",
                    "worker-a",
                    {"status": "completed", "modelConfigId": "buffalo_l", "samePerson": True},
                )

        self.assertEqual(raised.exception.status_code, 403)
        self.assertEqual(raised.exception.detail["code"], "WORKER_AUTH_FAILED")

    def test_legacy_worker_failed_result_rejects_lease_lost_between_service_and_repository(self):
        task = {
            "task_id": "ft_test",
            "model_config_id": "buffalo_l",
            "status": "running",
            "worker_id": "worker-a",
            "lease_until": jobs.now_ts() + 60,
        }

        with (
            patch.object(jobs, "get_task", return_value=task),
            patch.object(jobs, "repo_fail_task", return_value=None),
        ):
            with self.assertRaises(HTTPException) as raised:
                jobs.complete_worker_task(
                    "ft_test",
                    "worker-a",
                    {"status": "failed", "modelConfigId": "buffalo_l", "errorMessage": "boom"},
                )

        self.assertEqual(raised.exception.status_code, 403)
        self.assertEqual(raised.exception.detail["code"], "WORKER_AUTH_FAILED")


class RepositoryLeaseContractTest(unittest.TestCase):
    def test_generic_worker_result_rechecks_active_lease_inside_transaction(self):
        conn = FakeConnection(
            {
                "service_worker_task": {
                    "worker_task_id": "swt_test",
                    "task_id": "sj_test",
                    "capability": "face_compare.buffalo_l",
                    "status": "queued",
                    "worker_id": None,
                    "lease_until": None,
                }
            }
        )
        result = {
            "worker_result_id": "wr_test",
            "worker_id": "worker-a",
            "result_status": "completed",
            "elapsed_ms": 10,
            "raw_result_json": "{}",
            "created_at": jobs.now_ts(),
        }

        with patch.object(repo, "db_connect", return_value=conn):
            saved = repo.complete_service_worker_task("swt_test", result)

        self.assertIsNone(saved)
        self.assertIn("FOR UPDATE", conn.sql_text())
        self.assertNotIn("INSERT INTO worker_results", conn.sql_text())

    def test_legacy_worker_result_rechecks_active_lease_inside_transaction(self):
        conn = FakeConnection(
            {
                "compare_model_task": {
                    "task_id": "ft_test",
                    "job_id": "fc_test",
                    "model_config_id": "buffalo_l",
                    "status": "running",
                    "worker_id": "worker-b",
                    "lease_until": jobs.now_ts() + 60,
                }
            }
        )
        result = {
            "result_id": "fr_test",
            "worker_id": "worker-a",
            "decision_status": "same_person",
            "raw_result_json": "{}",
            "created_at": jobs.now_ts(),
        }

        with patch.object(repo, "db_connect", return_value=conn):
            saved = repo.complete_task_with_result("ft_test", result)

        self.assertIsNone(saved)
        self.assertIn("FOR UPDATE", conn.sql_text())
        self.assertNotIn("INSERT INTO compare_model_results", conn.sql_text())

    def test_legacy_worker_failed_result_rechecks_active_lease_inside_transaction(self):
        conn = FakeConnection(
            {
                "compare_model_task": {
                    "task_id": "ft_test",
                    "job_id": "fc_test",
                    "model_config_id": "buffalo_l",
                    "status": "running",
                    "worker_id": "worker-b",
                    "lease_until": jobs.now_ts() + 60,
                }
            }
        )

        with patch.object(repo, "db_connect", return_value=conn):
            saved = repo.fail_task("ft_test", "boom", worker_id="worker-a")

        self.assertIsNone(saved)
        self.assertIn("FOR UPDATE", conn.sql_text())
        self.assertNotIn("SET status = 'failed'", conn.sql_text())


class ServicePayloadContractTest(unittest.TestCase):
    def test_external_generic_task_payload_does_not_expose_local_asset_path(self):
        job = {
            "task_id": "sj_test",
            "service_type": "face_compare",
            "source_product": "internal_product_a",
            "request_id": "req-1",
            "status": "queued",
            "raw_payload_json": None,
        }
        asset = {
            "asset_id": "sa_test",
            "field_name": "firstImage",
            "position": 0,
            "uri": ".data/service-assets/2026/06/11/sj_test/sa_test.jpg",
            "sha256": "0" * 64,
            "mime": "image/jpeg",
            "size_bytes": 123,
            "original_filename": "a.jpg",
        }

        patches = [
            patch.object(jobs, "get_service_job", return_value=job),
            patch.object(jobs, "get_service_assets", return_value=[asset]),
            patch.object(jobs, "get_service_worker_tasks", return_value=[]),
            patch.object(jobs, "get_official_results", return_value=[]),
            patch.object(jobs, "get_worker_results", return_value=[]),
            patch.object(jobs, "get_comparison_results", return_value=[]),
        ]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)

        payload = jobs.generic_task_payload("sj_test")

        self.assertNotIn("url", payload["assets"][0])
        self.assertEqual(payload["assets"][0]["uri"], asset["uri"])


if __name__ == "__main__":
    unittest.main()
