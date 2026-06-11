const assert = require("assert");
const fs = require("fs");

const dockerignore = fs.readFileSync(".dockerignore", "utf8");
assert.match(dockerignore, /^\.env$/m, ".dockerignore must exclude real .env files");
assert.match(dockerignore, /^\.env\.\*$/m, ".dockerignore must exclude .env.* files");
assert.match(dockerignore, /^!\.env\.example$/m, ".dockerignore must keep .env.example available");

const compose = fs.readFileSync("docker-compose.yml", "utf8");
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

const evaluation = fs.readFileSync("app/services/evaluation.py", "utf8");
assert(
  !evaluation.includes("init_evaluation_db()"),
  "evaluation DB initialization must not run at service-module import time"
);

console.log("security contract ok");
