const assert = require("assert");
const fs = require("fs");

function read(path) {
  return fs.readFileSync(path, "utf8");
}

const routes = read("app/entrypoints/service_routes.py");
const schema = read("migrations/0001_init_schema.sql");
const service = read("app/services/service_jobs.py");
const repository = read("app/repositories/service.py");

for (const table of [
  "api_clients",
  "service_jobs",
  "service_assets",
  "service_worker_tasks",
  "official_results",
  "worker_results",
  "comparison_results",
  "pending_official_results",
]) {
  assert(schema.includes(`CREATE TABLE IF NOT EXISTS ${table}`), `${table} table must be bootstrapped`);
}

assert(routes.includes('@router.post("/api/tasks")'), "generic task ingestion route must exist");
assert(routes.includes('@router.post("/api/official-results")'), "official result callback route must exist");
assert(routes.includes('@router.get("/api/tasks/{task_id}")'), "generic task read route must exist");
assert(routes.includes('@router.post("/internal/tasks/lease")'), "generic worker lease route must exist");
assert(routes.includes('@router.post("/internal/tasks/{worker_task_id}/result")'), "generic worker result route must exist");

assert(schema.includes("UNIQUE KEY uk_service_request (api_id, request_id, service_type)"), "idempotency key must be scoped by api_id and service type");
assert(schema.includes("CREATE TABLE IF NOT EXISTS api_clients"), "api_clients table must be bootstrapped");
assert(repository.includes("SELECT * FROM api_clients WHERE access_key = %s"), "service repository must load api clients from MySQL");
assert(repository.includes("api_clients.status AS client_status"), "access token validation must load the current api_client status");
assert(schema.includes("field_name") && schema.includes("position"), "assets must preserve field names and order");
assert(schema.includes("capability") && repository.includes("lease_service_worker_tasks"), "worker tasks must route by capability");
assert(service.includes("pending_adapter"), "unsupported comparisons must produce pending_adapter");
assert(service.includes("attach_pending_official_result"), "task creation must attach earlier official results");
assert(service.includes('if official_result_json:') && service.includes('return existing, False'), "idempotent task replay must still attach inline official results");
assert(service.includes("raw_payload_json") && service.includes("raw_result_json"), "raw records must remain persisted");
assert(!routes.includes('source_product = token["source_product"]') && !routes.includes('token["source_product"] or'), "authenticated routes must not read sourceProduct from requests");
assert(routes.includes('payload.get("apiId") != token["api_id"]'), "read routes must reject cross-api access by taskId/jobId");
assert(service.includes('"apiId": job["api_id"]'), "external payloads must expose apiId instead of sourceProduct");

console.log("generic task api contract ok");
