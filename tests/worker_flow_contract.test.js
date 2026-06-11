const assert = require("assert");
const fs = require("fs");

function read(path) {
  return fs.readFileSync(path, "utf8");
}

const main = read("app/main.py");
const routes = read("app/entrypoints/service_routes.py");
const webCompare = read("app/services/web_compare.py");
const evaluation = read("app/services/evaluation.py");
const mysql = read("app/db/mysql.py");
const worker = read("worker/main.py");
const compose = read("docker-compose.yml");

assert(
  routes.includes('@router.post("/api/check")'),
  "service check ingestion must be exposed at /api/check"
);

assert(
  !routes.includes("/openapi/face-recognition/v4/check"),
  "legacy long check route must not remain registered"
);

assert(
  mysql.includes("job_type"),
  "compare_jobs must persist job_type to distinguish web_single, web_evaluation, and api_check"
);

assert(
  !webCompare.includes("EXECUTOR.submit") && !webCompare.includes("run_compare_job"),
  "web single compare must enqueue worker tasks instead of running model work in API"
);

assert(
  evaluation.includes("JOB_TYPE_WEB_EVALUATION") && !evaluation.includes("EXECUTOR.submit") && !evaluation.includes("run_compare_paths"),
  "web evaluation must enqueue worker tasks and aggregate results instead of running models in API"
);

assert(
  webCompare.includes("read_evaluation_job"),
  "evaluation job reads must aggregate worker-backed compare results"
);

assert(
  worker.includes('args.capability = f"face_compare.{args.model_config_id}"'),
  "worker capability must default from its configured model id"
);

for (const capability of [
  "face_compare.buffalo_l",
  "face_compare.arcface_retinaface_cosine",
  "face_compare.arcface_retinaface_euclidean_l2",
  "face_compare.facenet512_retinaface_cosine",
  "face_compare.ghostfacenet_retinaface_cosine",
]) {
  assert(compose.includes(`FACE_WORKER_CAPABILITY: ${capability}`), `${capability} docker worker capability must be explicit`);
  assert(compose.includes(`"allowed_capabilities":["${capability}"]`), `${capability} docker API credential capability must be explicit`);
}

console.log("worker flow contract ok");
