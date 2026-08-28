import { access } from "node:fs/promises";
import { spawnSync } from "node:child_process";
import process from "node:process";

const root = new URL("..", import.meta.url);
const python = process.env.LALK_PYTHON || "python";
const required = [
  new URL("src/lalk/vad/data/silero_vad.onnx", root),
  new URL("src/lalk/turn_detection/data/smart-turn-v3.2-cpu.onnx", root),
  new URL("src/lalk/audio/_native/VoiceIO.swift", root),
];

let failed = false;
for (const item of required) {
  try {
    await access(item);
    console.log(`ok       ${item}`);
  } catch {
    console.error(`missing  ${item}`);
    failed = true;
  }
}

for (const [command, args] of [
  ["node", ["--version"]],
  ["pnpm", ["--version"]],
  ["rustc", ["--version"]],
  [python, ["--version"]],
]) {
  const result = spawnSync(command, args, { encoding: "utf8" });
  if (result.status === 0) {
    console.log(
      `ok       ${command} ${(result.stdout || result.stderr).trim()}`,
    );
  } else {
    console.error(`missing  ${command}`);
    failed = true;
  }
}

process.exit(failed ? 1 : 0);
