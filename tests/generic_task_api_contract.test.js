const assert = require("assert");
const fs = require("fs");

function read(path) {
  return fs.readFileSync(path, "utf8");
}

const routes = read("app/entrypoints/service_routes.py");
const mysql = read("app/db/mysql.py");
const service = read("app/services/service_jobs.py");
const repository = read("app/repositories/service.py");

for (const table of [
  "service_jobs",
  "service_assets",
  "service_worker_tasks",
  "official_results",
  "worker_results",
  "comparison_results",
  "pending_official_results",
]) {
  assert(mysql.includes(`CREATE TABLE IF NOT EXISTS ${table}`), `${table} table must be bootstrapped`);
}

assert(routes.includes('@router.post("/api/tasks")'), "generic task ingestion route must exist");
assert(routes.includes('@router.post("/api/official-results")'), "official result callback route must exist");
assert(routes.includes('@router.get("/api/tasks/{task_id}")'), "generic task read route must exist");
assert(routes.includes('@router.post("/internal/tasks/lease")'), "generic worker lease route must exist");
assert(routes.includes('@router.post("/internal/tasks/{worker_task_id}/result")'), "generic worker result route must exist");

assert(mysql.includes("UNIQUE KEY uk_service_request (source_product, request_id, service_type)"), "idempotency key must include service type");
assert(mysql.includes("field_name") && mysql.includes("position"), "assets must preserve field names and order");
assert(mysql.includes("capability") && repository.includes("lease_service_worker_tasks"), "worker tasks must route by capability");
assert(service.includes("pending_adapter"), "unsupported comparisons must produce pending_adapter");
assert(service.includes("attach_pending_official_result"), "task creation must attach earlier official results");
assert(service.includes('if official_result_json:') && service.includes('return existing, False'), "idempotent task replay must still attach inline official results");
assert(service.includes("raw_payload_json") && service.includes("raw_result_json"), "raw records must remain persisted");

console.log("generic task api contract ok");
