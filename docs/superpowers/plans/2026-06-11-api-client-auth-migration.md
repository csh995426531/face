# API Client Auth Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace env-based API caller auth with a database-backed `api_clients` table and migrate API-authenticated job ownership from `source_product` to `api_id`.

**Architecture:** The API caller registry moves into MySQL and becomes the source of truth for token issuance. Access tokens and all API-authenticated job/result records carry `api_id`, preserving per-caller idempotency without using request-provided `sourceProduct`.

**Tech Stack:** FastAPI, MySQL via PyMySQL, Python `unittest`, Node.js string-contract tests

---

### Task 1: Lock the new auth and schema contract in tests

**Files:**
- Modify: `tests/api_route_contract_test.py`
- Modify: `tests/generic_task_api_contract.test.js`
- Test: `tests/api_route_contract_test.py`
- Test: `tests/generic_task_api_contract.test.js`

- [ ] **Step 1: Write the failing test**

```python
def test_generate_token_looks_up_client_in_repository(self):
    with patch.object(routes, "generate_token", return_value=({"token": "t", "expiredTime": 1}, None, None)) as generate:
        response = self.client.post(
            "/openapi/auth/ticket/v1/generate-token",
            json={
                "accessKey": "test-access-key",
                "timestamp": "1718080000000",
                "signature": "abc",
                "periodSecond": 3600,
            },
        )

    self.assertEqual(response.status_code, 200)
    generate.assert_called_once()
```

```js
assert(mysql.includes("CREATE TABLE IF NOT EXISTS api_clients"), "api_clients table must be bootstrapped");
assert(mysql.includes("UNIQUE KEY uk_service_request (api_id, request_id, service_type)"), "idempotency key must be scoped by api_id and service type");
assert(!routes.includes("sourceProduct = token"), "authenticated routes must not read sourceProduct from requests");
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.api_route_contract_test && node tests/generic_task_api_contract.test.js`
Expected: FAIL because the schema and route code still reference env-configured callers and `source_product`.

- [ ] **Step 3: Write minimal implementation**

```python
# Replace env-based caller fixtures with DB-backed lookup expectations in tests.
```

```js
// Update string-contract checks from source_product to api_id and api_clients.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.api_route_contract_test && node tests/generic_task_api_contract.test.js`
Expected: PASS

### Task 2: Migrate schema and repository access to api clients

**Files:**
- Modify: `app/db/mysql.py`
- Modify: `app/repositories/service.py`
- Test: `tests/generic_task_api_contract.test.js`

- [ ] **Step 1: Write the failing test**

```js
assert(mysql.includes("api_id VARCHAR(128) NOT NULL"), "api-authenticated tables must persist api_id");
assert(repository.includes("SELECT * FROM api_clients WHERE access_key = %s"), "service repository must load API clients from MySQL");
```

- [ ] **Step 2: Run test to verify it fails**

Run: `node tests/generic_task_api_contract.test.js`
Expected: FAIL because the schema and repository still use `source_product` and have no `api_clients` lookup.

- [ ] **Step 3: Write minimal implementation**

```python
def get_api_client(access_key: str):
    with db_connect() as conn:
        row = conn.execute("SELECT * FROM api_clients WHERE access_key = %s", (access_key,)).fetchone()
    return row_to_dict(row)
```

```sql
CREATE TABLE IF NOT EXISTS api_clients (
    api_id VARCHAR(128) PRIMARY KEY,
    access_key VARCHAR(128) NOT NULL UNIQUE,
    secret_key VARCHAR(255) NOT NULL,
    remark VARCHAR(255),
    status VARCHAR(32) NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `node tests/generic_task_api_contract.test.js`
Expected: PASS

### Task 3: Switch auth and service flows from source_product to api_id

**Files:**
- Modify: `app/services/service_auth.py`
- Modify: `app/entrypoints/service_routes.py`
- Modify: `app/services/service_jobs.py`
- Modify: `app/repositories/service.py`
- Test: `tests/api_route_contract_test.py`
- Test: `tests/review_fixes_test.py`

- [ ] **Step 1: Write the failing test**

```python
def test_create_service_compare_job_uses_api_id_from_token(self):
    with (
        patch.object(routes, "require_access_token", return_value={"api_id": "api-a"}),
        patch.object(routes, "create_service_compare_job_service", return_value=("job-1", "queued")) as create_job,
    ):
        response = self.client.post(
            "/api/check",
            headers={"X-ACCESS-TOKEN": "token"},
            files={
                "firstImage": ("a.jpg", b"a", "image/jpeg"),
                "secondImage": ("b.jpg", b"b", "image/jpeg"),
            },
            data={"requestId": "req-1", "sourceProduct": "ignored"},
        )

    self.assertEqual(response.status_code, 202)
    create_job.assert_called_once()
    self.assertEqual(create_job.call_args.args[:2], ("api-a", "req-1"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.api_route_contract_test tests.review_fixes_test`
Expected: FAIL because routes and services still read and emit `source_product`.

- [ ] **Step 3: Write minimal implementation**

```python
source_product = token["api_id"]
```

```python
create_access_token(token_hash(token), access_key, client["api_id"], expires_at)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.api_route_contract_test tests.review_fixes_test`
Expected: PASS

### Task 4: Remove obsolete env-based caller config and refresh examples

**Files:**
- Modify: `app/config.py`
- Modify: `.env.example`
- Modify: `docker-compose.yml`
- Test: `tests/security_contract.test.js`

- [ ] **Step 1: Write the failing test**

```js
assert(!read(".env.example").includes("FACE_API_ACCESS_KEY"), ".env.example must not advertise env-based API caller credentials");
assert(!read("docker-compose.yml").includes("FACE_API_SOURCE_PRODUCT"), "docker-compose must not require source product env");
```

- [ ] **Step 2: Run test to verify it fails**

Run: `node tests/security_contract.test.js`
Expected: FAIL because the example env and compose file still carry caller credentials.

- [ ] **Step 3: Write minimal implementation**

```python
# Remove ACCESS_CLIENTS, ACCESS_KEY, and ACCESS_SECRET from config.py.
```

```dotenv
# Keep only MySQL and worker credentials in .env.example.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `node tests/security_contract.test.js`
Expected: PASS

### Task 5: Full verification

**Files:**
- Modify: `.trellis/spec/backend/service-task-api.md`
- Test: `tests/api_route_contract_test.py`
- Test: `tests/review_fixes_test.py`
- Test: `tests/generic_task_api_contract.test.js`
- Test: `tests/security_contract.test.js`

- [ ] **Step 1: Update the executable contract**

```md
- `sourceProduct` is no longer part of authenticated API contracts.
- Idempotency key is `api_id + request_id + service_type`.
```

- [ ] **Step 2: Run the focused backend verification**

Run: `python3 -m unittest tests.api_route_contract_test tests.review_fixes_test`
Expected: PASS

- [ ] **Step 3: Run the string contract verification**

Run: `node tests/generic_task_api_contract.test.js && node tests/security_contract.test.js`
Expected: PASS

- [ ] **Step 4: Run a compile sanity check**

Run: `python3 -m compileall app`
Expected: PASS with no syntax errors
