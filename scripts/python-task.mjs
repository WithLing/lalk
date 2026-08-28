import { spawn } from "node:child_process";
import { delimiter, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import process from "node:process";

const python = process.env.LALK_PYTHON || "python";
const root = fileURLToPath(new URL("..", import.meta.url));
const pythonPath = [
  resolve(root, "src"),
  resolve(root, "server/src"),
  process.env.PYTHONPATH,
]
  .filter(Boolean)
  .join(delimiter);

const child = spawn(python, process.argv.slice(2), {
  cwd: root,
  env: { ...process.env, PYTHONPATH: pythonPath },
  stdio: "inherit",
});

child.on("error", (error) => {
  console.error(`Unable to start Python at ${python}: ${error.message}`);
  process.exit(1);
});

child.on("exit", (code, signal) => {
  if (signal) {
    process.kill(process.pid, signal);
    return;
  }
  process.exit(code ?? 1);
});
