import { execFileSync } from "node:child_process";
import { readFileSync, rmSync } from "node:fs";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const scriptsDirectory = path.dirname(fileURLToPath(import.meta.url));
const webDirectory = path.resolve(scriptsDirectory, "..");
const cacheRoot = path.resolve(webDirectory, "node_modules", ".cache");
const temporaryOutput = path.resolve(cacheRoot, "docreview-openapi-types");
const checkedInOutput = path.resolve(webDirectory, "src", "api", "generated");
const generator = path.resolve(
  webDirectory,
  "node_modules",
  "@hey-api",
  "openapi-ts",
  "bin",
  "run.js",
);
const source = path.resolve(webDirectory, "..", "api", "openapi.json");
const generatedFiles = ["index.ts", "types.gen.ts"];

if (!temporaryOutput.startsWith(`${cacheRoot}${path.sep}`)) {
  throw new Error("Temporary OpenAPI output must stay inside node_modules/.cache");
}

rmSync(temporaryOutput, { recursive: true, force: true });

try {
  execFileSync(
    process.execPath,
    [generator, "-i", source, "-o", temporaryOutput, "-p", "@hey-api/typescript", "--silent"],
    { cwd: webDirectory, stdio: "inherit" },
  );

  for (const filename of generatedFiles) {
    const expected = readFileSync(path.join(temporaryOutput, filename), "utf8");
    const actual = readFileSync(path.join(checkedInOutput, filename), "utf8");
    if (actual !== expected) {
      throw new Error(`Generated API type is stale: src/api/generated/${filename}`);
    }
  }
} finally {
  rmSync(temporaryOutput, { recursive: true, force: true });
}

console.log("Generated API types match apps/api/openapi.json");
