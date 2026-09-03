import { existsSync } from "node:fs";

import {
  apiDirectory,
  contractsDirectory,
  mockCoreDirectory,
  run,
  runNpm,
  systemPython,
  venvPython,
  webDirectory,
} from "./processes.mjs";

if (!existsSync(venvPython)) {
  run(systemPython, ["-m", "venv", ".venv"], { cwd: apiDirectory });
}

run(venvPython, [
  "-m",
  "pip",
  "install",
  "-r",
  "requirements.lock",
  "-r",
  "../../contracts/requirements.lock",
], { cwd: apiDirectory });
run(venvPython, [
  "-m",
  "pip",
  "install",
  "--no-deps",
  "--no-build-isolation",
  "-e",
  ".",
], { cwd: apiDirectory });
run(venvPython, [
  "-m",
  "pip",
  "install",
  "--no-deps",
  "--no-build-isolation",
  "-e",
  ".",
], { cwd: mockCoreDirectory });
runNpm(["ci"], { cwd: contractsDirectory });
runNpm(["ci"], { cwd: webDirectory });

console.log("\nSetup complete. Run npm run dev or npm run check.");
