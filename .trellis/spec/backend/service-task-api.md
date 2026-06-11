# Service Task API Contract

> Executable backend contract for the generic service-task API, worker lifecycle, and result comparison flow.

---

## Scenario: Generic Service Task API

### 1. Scope / Trigger

- Trigger: Any change to external task ingestion, official result callbacks, worker leasing/results, generic task tables, Docker worker env, or capability authorization.
- Scope: `POST /api/tasks`, `POST /api/official-results`, `GET /api/tasks/{taskId}`, `POST /internal/tasks/lease`, `POST /internal/tasks/{workerTaskId}/result`, and related MySQL tables.
- Rule: New generic work must use `service_*` terminology and capability routing; do not introduce business terminology that implies a secondary/sidecar service.

### 2. Signatures

- `POST /api/tasks`: multipart form endpoint for generic task creation.
- `POST /api/official-results`: JSON endpoint for production-service result callbacks.
- `GET /api/tasks/{taskId}`: JSON endpoint for task, assets, worker results, official results, and comparisons.
- `POST /internal/tasks/lease`: JSON endpoint for worker pickup by `capability`.
- `POST /internal/tasks/{workerTaskId}/result`: JSON endpoint for worker result submission.
- DB tables: `service_jobs`, `service_assets`, `service_worker_tasks`, `official_results`, `worker_results`, `comparison_results`, `pending_official_results`.

### 3. Contracts

- `POST /api/tasks` requires `serviceType` and `requestId`; `sourceProduct` may come from token or form.
- Supported `serviceType` values are `ocr`, `face_compare`, `tamper_detect`, `liveness`, `aigc_detect`, and `blacklist`.
- `payloadJson` and `officialResultJson` are optional JSON strings and must remain raw/auditable when stored.
- Uploaded files may use unknown field names; persist each asset with field name, per-field upload position, URI, sha256, MIME, size, and original filename.
- Idempotency key is `sourceProduct + requestId + serviceType`; replays with the same payload/assets return the existing task, while different payload/assets are conflicts.
- Official results may arrive inline on task creation or later via `POST /api/official-results`; if the task does not exist, store a pending result keyed by `sourceProduct + requestId + serviceType`.
- Workers lease by `capability`, for example `face_compare.buffalo_l`; worker credentials and Docker env must allow the same capability string.

### 4. Validation & Error Matrix

- Missing `serviceType`, `requestId`, or token-derived `sourceProduct` -> `PARAMETER_ERROR`.
- Unsupported `serviceType` -> `PARAMETER_ERROR`.
- Invalid `payloadJson`, `officialResultJson`, `officialResult`, or `normalizedResult` JSON -> `PARAMETER_ERROR`.
- Same idempotency key with different payload/assets -> `PARAMETER_ERROR` with HTTP 409.
- Same idempotency key with different official result -> `PARAMETER_ERROR` with HTTP 409.
- Worker credential missing, token mismatch, or disallowed capability -> worker auth error with HTTP 401/403.
- Worker result submitted by a worker that does not currently hold an unexpired lease -> `WORKER_AUTH_FAILED` with HTTP 403.
- Unknown asset fields are accepted unless they violate size or safety limits.

### 5. Good/Base/Bad Cases

- Good: `face_compare` task includes `firstImage` and `secondImage`; worker lease response adds `firstImageUrl` and `secondImageUrl` for the first adapter.
- Good: official result arrives before task creation; `pending_official_results` stores it, and task creation attaches it automatically.
- Base: non-face service task is accepted and routed to its default capability; comparison becomes `pending_adapter` once both official and worker results exist.
- Bad: a Docker worker sets `FACE_WORKER_CAPABILITY=face_compare.arcface_retinaface_cosine` but API credentials omit the same `allowed_capabilities`; lease must be forbidden.
- Bad: an idempotent replay includes new files for the same `sourceProduct + requestId + serviceType`; the API must reject instead of overwriting.

### 6. Tests Required

- Contract tests assert generic routes exist and old long face check route is not registered.
- Contract tests assert all generic tables exist and idempotency includes `serviceType`.
- Contract tests assert assets persist field name and position.
- Contract tests assert worker leasing routes by `capability` and Docker credentials explicitly include matching `allowed_capabilities`.
- Contract tests assert official pending attach paths and `pending_adapter` comparison behavior are present.
- Python compile check must pass for all backend modules.
- `docker compose config` must render without empty critical MySQL env defaults.

### 7. Wrong vs Correct

#### Wrong

```yaml
FACE_WORKER_CAPABILITY: face_compare.arcface_retinaface_cosine
FACE_WORKER_CREDENTIALS_JSON: '[{"worker_id":"worker-arcface-cosine","allowed_model_config_ids":["arcface_retinaface_cosine"]}]'
```

This looks configured but fails capability authorization because the API credential does not explicitly allow the worker capability.

#### Correct

```yaml
FACE_WORKER_CAPABILITY: face_compare.arcface_retinaface_cosine
FACE_WORKER_CREDENTIALS_JSON: '[{"worker_id":"worker-arcface-cosine","allowed_model_config_ids":["arcface_retinaface_cosine"],"allowed_capabilities":["face_compare.arcface_retinaface_cosine"]}]'
```

The worker lease request, credential allowlist, and task capability all use the same capability string.
