const assert = require("assert");
const fs = require("fs");

const dockerignore = fs.readFileSync(".dockerignore", "utf8");
assert.match(dockerignore, /^\.env$/m, ".dockerignore must exclude real .env files");
assert.match(dockerignore, /^\.env\.\*$/m, ".dockerignore must exclude .env.* files");
assert.match(dockerignore, /^!\.env\.example$/m, ".dockerignore must keep .env.example available");

const compose = fs.readFileSync("docker-compose.yml", "utf8");
const main = fs.readFileSync("app/main.py", "utf8");
for (const unsafeDefault of [
  ":-sampleaccesskey",
  ":-samplesecretkey",
  ":-change-me",
]) {
  assert(
    !compose.includes(unsafeDefault),
    `docker-compose.yml must not provide sensitive default ${unsafeDefault}`
  );
}
const envExample = fs.readFileSync(".env.example", "utf8");
assert(
  !envExample.includes("FACE_API_ACCESS_KEY"),
  ".env.example must not advertise env-based API caller credentials"
);
assert(
  !envExample.includes("FACE_API_SECRET_KEY"),
  ".env.example must not advertise env-based API caller secrets"
);
assert(
  !envExample.includes("FACE_API_SOURCE_PRODUCT"),
  ".env.example must not advertise source-product caller config"
);
assert(
  !compose.includes("FACE_API_ACCESS_KEY"),
  "docker-compose.yml must not require env-based API caller credentials"
);
assert(
  !compose.includes("FACE_API_SECRET_KEY"),
  "docker-compose.yml must not require env-based API caller secrets"
);
assert(
  !compose.includes("FACE_API_SOURCE_PRODUCT"),
  "docker-compose.yml must not require source product env"
);

const staticHtml = fs.readFileSync("static/index.html", "utf8");
assert(
  !/\.innerHTML\s*=/.test(staticHtml),
  "frontend must not assign service-controlled data through innerHTML"
);

const routes = fs.readFileSync("app/entrypoints/service_routes.py", "utf8");
assert(
  !routes.includes("init_service_db()"),
  "service DB initialization must not run at route-module import time"
);
assert(
  !main.includes("init_service_db()") && !main.includes("init_evaluation_db()"),
  "app startup must not run schema DDL"
);
assert(
  fs.existsSync("scripts/migrate.py"),
  "explicit SQL migration runner must exist"
);
assert(
  fs.existsSync("migrations/0001_init_schema.sql"),
  "baseline migration SQL must exist"
);
assert(
  !fs.existsSync("migrations/0002_api_clients_and_api_id.sql"),
  "unused pre-release delta migration must not remain after folding schema into 0001"
);

const evaluation = fs.readFileSync("app/services/evaluation.py", "utf8");
assert(
  !evaluation.includes("init_evaluation_db()"),
  "evaluation DB initialization must not run at service-module import time"
);

console.log("security contract ok");
