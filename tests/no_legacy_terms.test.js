const assert = require("assert");
const fs = require("fs");
const path = require("path");

const root = process.cwd();
const allowed = new Set([
  "static/index.html",
]);

function walk(dir) {
  const entries = fs.readdirSync(dir, { withFileTypes: true });
  const files = [];
  for (const entry of entries) {
    const fullPath = path.join(dir, entry.name);
    const relative = path.relative(root, fullPath);
    if (entry.isDirectory()) {
      if ([".git", ".venv", "venv", "__pycache__", ".pytest_cache"].includes(entry.name)) continue;
      files.push(...walk(fullPath));
    } else if (!allowed.has(relative)) {
      files.push(relative);
    }
  }
  return files;
}

const matches = [];
const legacyTerm = ["sh", "adow"].join("");
for (const file of walk(root)) {
  const content = fs.readFileSync(file, "utf8");
  if (content.toLowerCase().includes(legacyTerm)) {
    matches.push(file);
  }
}

assert.deepStrictEqual(matches, [], `Remove legacy terminology from code/docs:\n${matches.join("\n")}`);
console.log("no legacy terminology ok");
