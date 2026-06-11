# Generic Service Task API

## Goal

Build a generic service-task API that can accept and persist six service task types before their exact request/response schemas are fully known, route them to capability-specific workers, accept official production-service results, and compare official results with worker-produced service results once both sides are available.

## What I already know

* The product scope is six service types: OCR recognition, face comparison, tamper/PS detection, liveness detection, AIGC-generated image detection, and blacklist service.
* The API must not depend on knowing every service-specific payload format upfront.
* The system needs to persist incoming task payloads and files first, then let specific workers lease and process tasks.
* The system also receives official production-service results and must store them.
* Comparison can only happen after both the official result and at least one worker result exist.
* The current repo already has FastAPI routes, MySQL-backed job/task tables, worker lease/result APIs, access-token auth, worker-token auth, and a Web POC path.
* Current face-specific tables and names include `compare_jobs`, `compare_model_tasks`, `compare_model_results`, and `vendor_results`.
* Current `/api/check` is face-comparison oriented and creates `api_check` jobs plus model tasks.
* Current worker routing is based on `modelConfigId`; the generic design will replace that with capability-based routing such as `ocr.baidu_latest`, `face.buffalo_l`, `liveness.vendor_x`, or `blacklist.engineering_v1`.

## Assumptions

* The MVP should preserve existing worker polling and result callback mechanics rather than introducing Kafka/RabbitMQ.
* Each incoming request should be idempotent by at least `sourceProduct + requestId + serviceType`.
* Raw request payloads, raw official results, raw worker results, and uploaded assets should be stored even when no service-specific adapter exists.
* File input can vary by service: images, videos, spreadsheets, or other attachments.
* Official results may arrive before or after worker results.
* Unknown or unsupported comparison formats should not block task ingestion; they should produce a `pending_adapter` comparison state.

## Open Questions

All initial blocking questions have been resolved by grill review. Future questions should be about implementation discoveries or real payload samples, not MVP scope.

## Requirements

* The external task ingestion API must be a single generic endpoint: `POST /api/tasks`.
* Existing face-specific ingestion via `/api/check` should not be the primary API for the generic MVP; face comparison should be represented as `serviceType=face_compare` on `/api/tasks`.
* The API must support official production-service results in two ways:
  * Inline at task creation when the caller already has the official result.
  * Later via a separate idempotent callback endpoint when the official result arrives asynchronously.
* The API must accept tasks for six `serviceType` values:
  * `ocr`
  * `face_compare`
  * `tamper_detect`
  * `liveness`
  * `aigc_detect`
  * `blacklist`
* The API must persist raw business payloads without requiring service-specific parsing.
* The API must persist uploaded assets with field name, URI/path, sha256, mime, size, and original filename.
* The API must persist official production-service results separately from worker service results.
* Worker tasks must be routed by service capability, not by a face-only `modelConfigId`.
* Worker capability names must combine service type and implementation, for example `face_compare.buffalo_l`, `ocr.baidu_latest`, `liveness.vendor_x`, `aigc_detect.watermark_v1`, and `blacklist.engineering_v1`.
* Workers must be able to lease tasks, process them, and submit raw results.
* Once official and worker results both exist, the system must either run a service-specific comparator or mark the comparison as waiting for an adapter.
* Official results that arrive before task creation must be supported by a pending result record keyed by `sourceProduct + requestId + serviceType`; when the matching task arrives, the system must attach the pending official result.
* Worker results that arrive after task lease expiry must be rejected unless the worker still holds the lease or the task has not been completed by another worker.
* Unknown file fields must be accepted and stored as assets, unless they violate size/type safety limits.
* A task may have multiple assets under the same field name, preserving upload order.
* The system must retain raw payload/result JSON exactly enough for audit and replay; service adapters may add normalized JSON but must not replace raw records.
* The system must create generic tables alongside current face-specific tables for MVP, then migrate face-specific paths into the generic model incrementally.
* Existing face comparison should become the first concrete adapter using the generic framework.

## Acceptance Criteria

* [x] A task with unknown service-specific payload shape can be accepted and persisted.
* [x] Each task records `serviceType`, `sourceProduct`, `requestId`, raw payload, and assets.
* [x] `POST /api/tasks` accepts all six supported `serviceType` values.
* [x] `POST /api/tasks` can accept optional inline official results.
* [x] A separate official result callback can attach results to an existing task.
* [x] Duplicate requests with the same idempotency key do not create duplicate tasks.
* [x] Duplicate requests with the same idempotency key but different payload/assets are rejected with a conflict.
* [x] Official result callbacks can be persisted before or after worker completion.
* [x] Official result callbacks can be received before task creation and later linked to the matching task.
* [x] Workers can lease by capability and receive enough input context to process the task.
* [x] A worker cannot submit a result for a task it does not currently hold.
* [x] Worker results are persisted as raw results and associated with the leased task.
* [x] The system creates a comparison record when official and worker results are both present.
* [x] Unsupported comparison types are marked explicitly instead of failing ingestion.
* [x] Unknown asset field names are stored and returned to workers without requiring code changes.
* [x] Raw official and worker result bodies remain available even when normalization fails.
* [x] Existing face comparison still works through the new generic model or a documented compatibility wrapper.

## Definition of Done (team quality bar)

* Tests added/updated for generic task ingestion, idempotency, official result persistence, worker lease/result flow, and comparison trigger states.
* Lint / typecheck / CI green where available.
* API docs/notes updated for external task creation, official result callback, worker lease, and worker result callback.
* Rollout/rollback considered because this changes core job and worker schema.

## Out of Scope (explicit)

* Building final service-specific comparators for all six services in the MVP.
* Guaranteeing exact normalized schemas for all six service results before real payload samples are available.
* Replacing DB-backed worker polling with a message queue.
* Keeping `/api/check` as the long-term public API for face comparison.
* Fully migrating or deleting existing face-specific tables during the first generic MVP.
* Building UI changes unless needed to verify the generic task flow.
* Implementing production OSS storage if the current local storage path remains acceptable for the POC.

## Technical Approach

The architecture is a generic envelope plus adapter pattern:

* `service_jobs` stores the service type, source, idempotency key, status, raw payload, and metadata.
* `service_assets` stores uploaded files independently of service type.
* `service_worker_tasks` stores capability-specific work items for workers.
* `official_results` stores production-service outputs.
* `worker_results` stores worker outputs.
* `comparison_results` stores adapter-produced diffs or `pending_adapter`.

Existing face comparison logic can be preserved as the first `face_compare` adapter while the API and worker lifecycle become service-agnostic.

### External API Shape

#### Create generic task

`POST /api/tasks`

Accepts `multipart/form-data`:

* `serviceType`: one of `ocr`, `face_compare`, `tamper_detect`, `liveness`, `aigc_detect`, `blacklist`
* `requestId`: caller idempotency key within the service type
* `sourceProduct`: optional if token supplies it
* `payloadJson`: optional raw request envelope as JSON string
* `officialResultJson`: optional raw official result JSON string
* `files`: any number of uploaded files under any field names

Returns `202 accepted` with `taskId`, `serviceType`, and `status`.

#### Submit official result

`POST /api/official-results`

Accepts JSON:

* `sourceProduct`
* `requestId`
* `serviceType`
* `officialResult`
* optional `officialStatus`
* optional `officialElapsedMs`
* optional `vendorRequestId`

If the task exists, attach the result to the task. If the task does not exist yet, persist a pending official result and attach it later when the task arrives.

#### Query task

`GET /api/tasks/{taskId}`

Returns task envelope, assets, worker task states, official result state, worker result states, and comparison states.

### Internal Worker API Shape

#### Lease worker tasks

`POST /internal/tasks/lease`

Workers request tasks by `capability`, for example `face_compare.buffalo_l`.

#### Submit worker result

`POST /internal/tasks/{workerTaskId}/result`

Workers submit raw result JSON, status, elapsed time, and optional normalized JSON. The API validates that the worker currently holds the lease.

### Generic Status Model

`service_jobs.status` values:

* `queued`: task accepted, no worker result yet
* `running`: at least one worker task leased/running
* `completed`: all required worker tasks completed
* `failed`: all required worker tasks failed or ingestion failed
* `partial_failed`: mixed completed and failed worker tasks

`comparison_results.compare_status` values:

* `matched`: comparator found results equivalent
* `mismatched`: comparator found differences
* `pending_official`: worker result exists, official result missing
* `pending_worker`: official result exists, worker result missing
* `pending_adapter`: both results exist but comparator is not implemented
* `compare_failed`: comparator errored

### Minimum Table Set

* `service_jobs`
* `service_assets`
* `service_worker_tasks`
* `official_results`
* `worker_results`
* `comparison_results`
* `pending_official_results`

The existing face-specific tables may remain during migration but should not be the target schema for new generic task ingestion.

## Grill Review Decisions

### Q1: Should the MVP expose one generic task API or keep service-specific public APIs?

**Recommended answer adopted:** Use one generic public task API: `POST /api/tasks`.

**Reasoning:** The six service formats are not fully known, so service-specific endpoints would encode premature assumptions. A generic envelope lets the system persist first and add service adapters later.

### Q2: What happens to `/api/check`?

**Recommended answer adopted:** `/api/check` is not the target generic API. Face comparison moves to `POST /api/tasks` with `serviceType=face_compare`.

**Reasoning:** This avoids one-off face semantics leaking into the generic six-service design. If a transition wrapper is needed during implementation, it must be documented as compatibility-only and outside the final target shape.

### Q3: Should official production results arrive inline, later, or both?

**Recommended answer adopted:** Support both inline official results on task creation and a separate idempotent official-result callback.

**Reasoning:** Some flows may call the official service before service-task submission, while others may receive official results asynchronously. Supporting both avoids ordering assumptions.

### Q4: Should unknown payloads be parsed at ingestion?

**Recommended answer adopted:** Do not parse service-specific payloads at ingestion beyond envelope validation, size limits, and asset metadata.

**Reasoning:** The immediate goal is durable capture and worker dispatch. Parsing should live in service adapters once real schemas are known.

### Q5: Should generic tables replace current face-specific tables immediately?

**Recommended answer adopted:** Add generic tables alongside existing face-specific tables, then migrate face paths into generic storage incrementally.

**Reasoning:** The schema shift is large and affects job creation, worker leasing, result storage, and Web POC behavior. A parallel generic model reduces migration risk.

### Q6: How should workers be routed?

**Recommended answer adopted:** Route by `capability`, not by face-only `modelConfigId`.

**Reasoning:** Capability names can cover all six services and multiple implementations per service, while `modelConfigId` is too face-model specific.

### Q7: How should comparisons be triggered?

**Recommended answer adopted:** Trigger comparison whenever either official or worker result is stored and the other side already exists.

**Reasoning:** Result ordering is not guaranteed. Both result-write paths should call a shared "try compare" service.

### Q8: What if no comparator exists for a service type?

**Recommended answer adopted:** Store a comparison row with `compare_status=pending_adapter`.

**Reasoning:** The system should prove ingestion, storage, and worker processing before every service has a mature comparator.

### Q9: What is the idempotency key?

**Recommended answer adopted:** Use `sourceProduct + requestId + serviceType`.

**Reasoning:** Different services may share business request IDs. Including `serviceType` prevents cross-service collisions while preserving business-level idempotency.

### Q10: What should happen on idempotent replay with different payload/assets?

**Recommended answer adopted:** Reject with a conflict.

**Reasoning:** Silent overwrites would break auditability and invalidate comparisons.

### Q11: What should be the first concrete adapter?

**Recommended answer adopted:** `face_compare`.

**Reasoning:** The repo already has face comparison model configs, worker code, and Web POC behavior. It is the lowest-risk proof of the generic framework.

### Q12: What is the MVP boundary?

**Recommended answer adopted:** MVP includes generic ingestion, raw persistence, asset storage, official result persistence, capability-based worker lease/result flow, comparison trigger states, and one concrete `face_compare` adapter. MVP excludes final comparators for all six services.

**Reasoning:** This validates the architecture without blocking on unavailable real schemas for every service.

### Q13: Can official results arrive before task creation?

**Recommended answer adopted:** Yes. Store them as pending official results keyed by `sourceProduct + requestId + serviceType`, then attach when the matching task is created.

**Reasoning:** Production result callbacks can be retried or reordered. Rejecting early official results would create operational coupling that the service-task system does not need.

### Q14: Can one asset field contain multiple files?

**Recommended answer adopted:** Yes. Store assets as rows with `field_name` and `position`.

**Reasoning:** OCR and tamper detection may be one-image flows, face comparison is two-image, liveness may include video plus image frames, and blacklist may include structured files. The API should not assume cardinality.

### Q15: Should unknown file field names be rejected?

**Recommended answer adopted:** No. Accept unknown field names subject to safety validation.

**Reasoning:** The task format is intentionally schema-light until real service samples are available.

### Q16: How strict should result submission be after lease expiry?

**Recommended answer adopted:** A worker result should be accepted only when the submitting worker currently holds the task lease and the task is still running.

**Reasoning:** This prevents late results from stale workers overwriting a retry that was already picked up by another worker.

### Q17: Should raw records be overwritten by normalized records?

**Recommended answer adopted:** No. Raw request, official result, and worker result records are immutable audit inputs; normalized records are additive.

**Reasoning:** Comparators and normalizers will evolve. Keeping raw records enables replay and debugging.

### Q18: What is the minimum comparison behavior for unsupported services?

**Recommended answer adopted:** Create a comparison record with `compare_status=pending_adapter`, references to both result IDs, and no diff metrics.

**Reasoning:** This proves the lifecycle is complete while making unsupported comparison explicit.

### Q19: Should Web POC use the generic model?

**Recommended answer adopted:** Yes, but only after the generic API and `face_compare` adapter are stable.

**Reasoning:** Web POC is useful for validation, but external API correctness should drive the MVP.

### Q20: What must not be included in MVP?

**Recommended answer adopted:** Do not implement all six service-specific comparators, a new queue system, full UI redesign, or production object storage migration in this task.

**Reasoning:** Those are useful follow-up tasks, but they would blur the core architecture validation.

## Expansion Sweep

### Future evolution

* Add service-specific normalizers and comparators incrementally as real payloads arrive.
* Add multiple workers per service type and multiple capabilities per worker without changing external ingestion.

### Related scenarios

* Web POC tasks should use the same generic job/task storage model as external API tasks.
* Official result callbacks should support retry/idempotency because production systems often resend callbacks.

### Failure & edge cases

* Official result arrives before task creation.
* Worker result arrives before official result.
* Unsupported `serviceType`.
* Unknown file fields.
* Duplicate `requestId` with different payload/assets.
* Worker lease timeout and retry.

## Technical Notes

* Existing API route file: `app/entrypoints/service_routes.py`.
* Existing Web POC routes: `app/main.py`.
* Existing worker polling: `worker/main.py`.
* Existing DB schema bootstrap: `app/db/mysql.py`.
* Existing repository layer: `app/repositories/service.py`.
* Existing service layer: `app/services/service_jobs.py`.
* Existing official/vendor result path: `/internal/face-recognition/vendor-results`.
* Current worker auth uses `X-WORKER-ID` and `X-WORKER-TOKEN`.
* Current access auth uses `/openapi/auth/ticket/v1/generate-token` and `X-ACCESS-TOKEN`.

## Implementation Plan (small PRs)

* PR1: Add generic tables, repository methods, and contract tests for task ingestion/idempotency.
* PR2: Add `POST /api/tasks`, asset persistence, and pending official result attach logic.
* PR3: Add generic worker lease/result APIs using `capability`.
* PR4: Add result comparison trigger service with `pending_adapter` behavior and `face_compare` comparator scaffold.
* PR5: Migrate Web POC / existing face path to create `serviceType=face_compare` tasks through the generic model.
* PR6: Update docs and run full quality check.

## Decision Log

* Use `POST /api/tasks` as the generic external task creation endpoint.
* Use `POST /api/official-results` for official production result callbacks.
* Support inline official results during task creation as a convenience path.
* Use `sourceProduct + requestId + serviceType` as the idempotency key.
* Route worker tasks by `capability`.
* Keep raw records immutable and add normalized records separately.
* Add generic tables alongside existing face-specific tables for MVP.
* Implement `face_compare` as the first concrete adapter.
