import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("FACE_API_ACCESS_KEY", "test-access-key")
os.environ.setdefault("FACE_API_SECRET_KEY", "test-secret-key")
os.environ.setdefault("FACE_API_SOURCE_PRODUCT", "test_product")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

import app.entrypoints.service_routes as routes
from app.main import app

app.router.on_startup.clear()


class ApiRouteContractTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def assert_parameter_error(self, response):
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"]["code"], "PARAMETER_ERROR")

    def test_configs_route_imports_without_database_startup(self):
        response = self.client.get("/api/configs")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(any(item["id"] == "buffalo_l" for item in response.json()))

    def test_service_task_lease_rejects_non_integer_limit(self):
        client = TestClient(app, raise_server_exceptions=False)
        with (
            patch.object(routes, "require_worker", return_value={"worker_id": "worker-a"}),
            patch.object(routes, "lease_generic_worker_tasks") as lease,
        ):
            response = client.post(
                "/internal/tasks/lease",
                headers={"X-WORKER-ID": "worker-a", "X-WORKER-TOKEN": "token"},
                json={"workerId": "worker-a", "capability": "face_compare.buffalo_l", "limit": "abc"},
            )

        self.assert_parameter_error(response)
        lease.assert_not_called()

    def test_model_task_lease_rejects_non_integer_limit(self):
        client = TestClient(app, raise_server_exceptions=False)
        with (
            patch.object(routes, "require_worker", return_value={"worker_id": "worker-a"}),
            patch.object(routes, "lease_worker_tasks") as lease,
        ):
            response = client.post(
                "/internal/model-tasks/lease",
                headers={"X-WORKER-ID": "worker-a", "X-WORKER-TOKEN": "token"},
                json={"workerId": "worker-a", "modelConfigId": "buffalo_l", "limit": "abc"},
            )

        self.assert_parameter_error(response)
        lease.assert_not_called()

    def test_model_task_renew_rejects_non_integer_lease_seconds(self):
        task = {
            "task_id": "ft_test",
            "job_id": "fc_test",
            "model_config_id": "buffalo_l",
            "status": "running",
            "worker_id": "worker-a",
            "lease_until": 9999999999,
        }
        client = TestClient(app, raise_server_exceptions=False)

        with (
            patch.object(routes, "get_compare_task", return_value=task),
            patch.object(routes, "require_worker", return_value={"worker_id": "worker-a"}),
            patch.object(routes, "renew_worker_task") as renew,
        ):
            response = client.post(
                "/internal/model-tasks/ft_test/renew-lease",
                headers={"X-WORKER-ID": "worker-a", "X-WORKER-TOKEN": "token"},
                json={"leaseSeconds": "abc"},
            )

        self.assert_parameter_error(response)
        renew.assert_not_called()

    def test_model_task_result_rejects_payload_worker_id_mismatch(self):
        task = {
            "task_id": "ft_test",
            "job_id": "fc_test",
            "model_config_id": "buffalo_l",
            "status": "running",
            "worker_id": "worker-a",
            "lease_until": 9999999999,
        }
        payload = {"workerId": "worker-b", "status": "completed", "modelConfigId": "buffalo_l"}

        with (
            patch.object(routes, "get_compare_task", return_value=task),
            patch.object(routes, "require_worker", return_value={"worker_id": "worker-a"}),
            patch.object(routes, "complete_worker_task") as complete,
        ):
            response = self.client.post(
                "/internal/model-tasks/ft_test/result",
                headers={"X-WORKER-ID": "worker-a", "X-WORKER-TOKEN": "token"},
                json=payload,
            )

        self.assertEqual(response.status_code, 401)
        complete.assert_not_called()

    def test_model_task_result_passes_authenticated_worker_to_service(self):
        task = {
            "task_id": "ft_test",
            "job_id": "fc_test",
            "model_config_id": "buffalo_l",
            "status": "running",
            "worker_id": "worker-a",
            "lease_until": 9999999999,
        }
        payload = {"workerId": "worker-a", "status": "completed", "modelConfigId": "buffalo_l"}

        with (
            patch.object(routes, "get_compare_task", return_value=task),
            patch.object(routes, "require_worker", return_value={"worker_id": "worker-a"}),
            patch.object(routes, "complete_worker_task") as complete,
            patch.object(routes, "service_job_payload", return_value={"status": "completed"}),
        ):
            response = self.client.post(
                "/internal/model-tasks/ft_test/result",
                headers={"X-WORKER-ID": "worker-a", "X-WORKER-TOKEN": "token"},
                json=payload,
            )

        self.assertEqual(response.status_code, 200)
        complete.assert_called_once_with("ft_test", "worker-a", payload)


if __name__ == "__main__":
    unittest.main()
