import { spawn, spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { fileURLToPath } from "node:url";

export const repositoryDirectory = fileURLToPath(new URL("../", import.meta.url));
export const apiDirectory = fileURLToPath(new URL("../apps/api/", import.meta.url));
export const webDirectory = fileURLToPath(new URL("../apps/web/", import.meta.url));
export const contractsDirectory = fileURLToPath(new URL("../contracts/", import.meta.url));

export const systemPython = process.env.DOCREVIEW_PYTHON ??
  (process.platform === "win32" ? "python" : "python3");
export const venvPython = fileURLToPath(
  new URL(
    process.platform === "win32" ? "../apps/api/.venv/Scripts/python.exe" : "../apps/api/.venv/bin/python",
    import.meta.url,
  ),
);

export function requireVirtualEnvironment() {
  if (!existsSync(venvPython)) {
    throw new Error('Python environment is missing. Run "npm run setup" first.');
  }
}

export function run(command, args, options = {}) {
  console.log(`\n> ${command} ${args.join(" ")}`);
  const result = spawnSync(command, args, {
    cwd: repositoryDirectory,
    stdio: "inherit",
    ...options,
  });

  if (result.error) throw result.error;
  if (result.status !== 0) process.exit(result.status ?? 1);
}

export function start(command, args, options = {}) {
  return spawn(command, args, {
    cwd: repositoryDirectory,
    stdio: "inherit",
    ...options,
  });
}

export function runNpm(args, options = {}) {
  const npmCli = process.env.npm_execpath;
  if (npmCli) return run(process.execPath, [npmCli, ...args], options);
  return run("npm", args, {
    ...options,
    shell: process.platform === "win32",
  });
}

export function startNpm(args, options = {}) {
  const npmCli = process.env.npm_execpath;
  if (npmCli) return start(process.execPath, [npmCli, ...args], options);
  return start("npm", args, {
    ...options,
    shell: process.platform === "win32",
  });
}
