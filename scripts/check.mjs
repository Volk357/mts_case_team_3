import {
  apiDirectory,
  contractsDirectory,
  mockCoreDirectory,
  repositoryDirectory,
  requireVirtualEnvironment,
  run,
  runNpm,
  venvPython,
  webDirectory,
} from "./processes.mjs";

requireVirtualEnvironment();

run(venvPython, ["-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"], {
  cwd: repositoryDirectory,
});
run(venvPython, ["-m", "ruff", "check", "src", "tests", "scripts", "alembic"], {
  cwd: apiDirectory,
});
run(venvPython, ["-m", "ruff", "format", "--check", "src", "tests", "scripts", "alembic"], {
  cwd: apiDirectory,
});
run(venvPython, ["-m", "mypy"], { cwd: apiDirectory });
run(
  venvPython,
  ["-m", "pytest", "--cov", "--basetemp", ".tmp-pytest-check", "-p", "no:cacheprovider"],
  { cwd: apiDirectory },
);
run(venvPython, ["-m", "ruff", "check", "src", "tests", "tools"], {
  cwd: mockCoreDirectory,
});
run(venvPython, ["-m", "ruff", "format", "--check", "src", "tests", "tools"], {
  cwd: mockCoreDirectory,
});
run(venvPython, ["-m", "mypy"], { cwd: mockCoreDirectory });
run(
  venvPython,
  ["-m", "pytest", "--cov", "--basetemp", ".tmp-pytest-check", "-p", "no:cacheprovider"],
  { cwd: mockCoreDirectory },
);
runNpm(["run", "check"], { cwd: contractsDirectory });
runNpm(["run", "lint"], { cwd: webDirectory });
runNpm(["run", "typecheck"], { cwd: webDirectory });
runNpm(["run", "test"], { cwd: webDirectory });
runNpm(["run", "build"], { cwd: webDirectory });

console.log("\nAll checks passed.");
