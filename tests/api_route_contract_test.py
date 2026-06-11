import hashlib
import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from fastapi import HTTPException
except ModuleNotFoundError:
    fastapi = types.ModuleType("fastapi")
    responses = types.ModuleType("fastapi.responses")

    class HTTPException(Exception):
        def __init__(self, status_code, detail=None):
            super().__init__(detail)
            self.status_code = status_code
            self.detail = detail

    class APIRouter:
        def post(self, *_args, **_kwargs):
            return lambda fn: fn

        def get(self, *_args, **_kwargs):
            return lambda fn: fn

    class Request:
        def __init__(self, headers=None):
            self.headers = headers or {}

    class UploadFile:
        pass

    class JSONResponse:
        def __init__(self, status_code=200, content=None):
            self.status_code = status_code
            self.content = content
            self.body = json.dumps(content).encode("utf-8")

    def passthrough(default=None, **_kwargs):
        return default

    fastapi.APIRouter = APIRouter
    fastapi.Body = passthrough
    fastapi.File = passthrough
    fastapi.Form = passthrough
    fastapi.Header = passthrough
    fastapi.HTTPException = HTTPException
    fastapi.Request = Request
    fastapi.UploadFile = UploadFile
    responses.JSONResponse = JSONResponse
    sys.modules["fastapi"] = fastapi
    sys.modules["fastapi.responses"] = responses

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

import app.entrypoints.service_routes as routes
import app.services.service_auth as service_auth


class ApiRouteContractTest(unittest.TestCase):
    def assert_parameter_error(self, error):
        self.assertEqual(error.status_code, 400)
        self.assertEqual(error.detail["code"], "PARAMETER_ERROR")

    def test_generate_token_uses_database_api_client(self):
        signature = hashlib.sha256("db-access-keydb-secret100000".encode("utf-8")).hexdigest()

        with (
            patch.object(service_auth, "now_ts", return_value=100.0),
            patch.object(
                service_auth,
                "get_api_client",
                create=True,
                return_value={
                    "api_id": "api_test",
                    "access_key": "db-access-key",
                    "secret_key": "db-secret",
                    "status": "enabled",
                },
            ) as get_api_client,
            patch.object(service_auth, "create_access_token") as create_access_token,
        ):
            data, code, message = service_auth.generate_token(
                "db-access-key",
                "100000",
                signature,
                3600,
            )

        self.assertIsNone(code)
        self.assertIsNone(message)
        self.assertTrue(data["token"].startswith("access_token_"))
        self.assertEqual(data["expiredTime"], 3700000)
        get_api_client.assert_called_once_with("db-access-key")
        create_access_token.assert_called_once()
        self.assertEqual(create_access_token.call_args.args[1], "db-access-key")
        self.assertEqual(create_access_token.call_args.args[2], "api_test")

    def test_service_task_lease_rejects_non_integer_limit(self):
        with (
            patch.object(routes, "require_worker", return_value={"worker_id": "worker-a"}),
            patch.object(routes, "lease_generic_worker_tasks") as lease,
        ):
            with self.assertRaises(HTTPException) as raised:
                routes.lease_service_tasks(
                    object(),
                    {"workerId": "worker-a", "capability": "face_compare.buffalo_l", "limit": "abc"},
                )

        self.assert_parameter_error(raised.exception)
        lease.assert_not_called()

    def test_model_task_lease_rejects_non_integer_limit(self):
        with (
            patch.object(routes, "require_worker", return_value={"worker_id": "worker-a"}),
            patch.object(routes, "lease_worker_tasks") as lease,
        ):
            with self.assertRaises(HTTPException) as raised:
                routes.lease_model_tasks(
                    object(),
                    {"workerId": "worker-a", "modelConfigId": "buffalo_l", "limit": "abc"},
                )

        self.assert_parameter_error(raised.exception)
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
        with (
            patch.object(routes, "get_compare_task", return_value=task),
            patch.object(routes, "require_worker", return_value={"worker_id": "worker-a"}),
            patch.object(routes, "renew_worker_task") as renew,
        ):
            with self.assertRaises(HTTPException) as raised:
                routes.renew_model_task_lease("ft_test", object(), {"leaseSeconds": "abc"})

        self.assert_parameter_error(raised.exception)
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
            with self.assertRaises(HTTPException) as raised:
                routes.submit_model_task_result("ft_test", object(), payload)

        self.assertEqual(raised.exception.status_code, 401)
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
            response = routes.submit_model_task_result("ft_test", object(), payload)

        self.assertEqual(response["code"], 0)
        complete.assert_called_once_with("ft_test", "worker-a", payload)

    def test_api_check_uses_api_id_from_token_not_source_product(self):
        with (
            patch.object(routes, "require_access_token", return_value={"api_id": "api-a"}),
            patch.object(routes, "create_service_compare_job_service", return_value=("job-1", "queued")) as create_job,
        ):
            response = routes.create_service_compare_job(
                firstImage=object(),
                secondImage=object(),
                requestId="req-1",
                sourceProduct="ignored",
                vendorRequestId="",
                x_access_token="token",
            )

        self.assertEqual(response.status_code, 202)
        self.assertEqual(json.loads(response.body), {"code": 0, "message": "accepted", "jobId": "job-1", "status": "queued"})
        create_job.assert_called_once()
        self.assertEqual(create_job.call_args.args[:2], ("api-a", "req-1"))

    def test_get_generic_task_rejects_other_api_owner(self):
        with (
            patch.object(routes, "require_access_token", return_value={"api_id": "api-a"}),
            patch.object(routes, "generic_task_payload", return_value={"taskId": "sj-1", "apiId": "api-b"}),
        ):
            with self.assertRaises(HTTPException) as raised:
                routes.get_generic_task("sj-1", x_access_token="token")

        self.assertEqual(raised.exception.status_code, 404)
        self.assertEqual(raised.exception.detail["code"], "PARAMETER_ERROR")

    def test_get_service_job_rejects_other_api_owner(self):
        with (
            patch.object(routes, "require_access_token", return_value={"api_id": "api-a"}),
            patch.object(routes, "service_job_payload", return_value={"jobId": "fc-1", "apiId": "api-b"}),
        ):
            with self.assertRaises(HTTPException) as raised:
                routes.get_service_job("fc-1", x_access_token="token")

        self.assertEqual(raised.exception.status_code, 404)
        self.assertEqual(raised.exception.detail["code"], "PARAMETER_ERROR")

    def test_require_access_token_rejects_disabled_api_client(self):
        with (
            patch.object(service_auth, "get_access_token", return_value={"api_id": "api-a", "expires_at": 1000, "client_status": "disabled"}),
            patch.object(service_auth, "now_ts", return_value=100),
        ):
            with self.assertRaises(HTTPException) as raised:
                service_auth.require_access_token("token")

        self.assertEqual(raised.exception.status_code, 401)
        self.assertEqual(raised.exception.detail["code"], "INVALID_TOKEN")


if __name__ == "__main__":
    unittest.main()
