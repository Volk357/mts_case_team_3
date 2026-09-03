import {
  apiDirectory,
  requireVirtualEnvironment,
  start,
  startNpm,
  venvPython,
  webDirectory,
} from "./processes.mjs";

requireVirtualEnvironment();

const processes = [
  start(venvPython, ["-m", "uvicorn", "docreview_api.main:app", "--reload"], {
    cwd: apiDirectory,
  }),
  start(venvPython, ["-m", "docreview_api.workers.review_worker"], {
    cwd: apiDirectory,
  }),
  startNpm(["run", "dev", "--", "--host", "127.0.0.1"], { cwd: webDirectory }),
];

let stopping = false;

function stop(exitCode = 0) {
  if (stopping) return;
  stopping = true;
  for (const child of processes) {
    if (!child.killed) child.kill();
  }
  process.exitCode = exitCode;
}

for (const child of processes) {
  child.on("error", (error) => {
    console.error(error);
    stop(1);
  });
  child.on("exit", (code) => {
    if (!stopping) stop(code ?? 1);
  });
}

process.on("SIGINT", () => stop());
process.on("SIGTERM", () => stop());
