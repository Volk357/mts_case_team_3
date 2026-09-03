import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

import { compileFromFile } from "json-schema-to-typescript";

const contractsDirectory = fileURLToPath(new URL("../", import.meta.url));
const schemaPath = fileURLToPath(
  new URL("../review-result.schema.json", import.meta.url),
);
const generatedPath = fileURLToPath(
  new URL("../generated/review-result.d.ts", import.meta.url),
);

const [expected, actual] = await Promise.all([
  compileFromFile(schemaPath),
  readFile(generatedPath, "utf8"),
]);

const normalizeNewlines = (value) => value.replaceAll("\r\n", "\n");

if (normalizeNewlines(expected) !== normalizeNewlines(actual)) {
  console.error(
    `Generated types are stale. Run "npm --prefix ${contractsDirectory} run generate:types".`,
  );
  process.exitCode = 1;
}
