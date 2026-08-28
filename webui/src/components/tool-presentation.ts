import type { ToolPart, ToolState } from "../runtime/contracts";

type ToolCopy = Record<ToolState, string>;

export interface ToolPresentation {
  label: string;
  summary: string;
  duration: string;
  technicalName: string;
}

const MUTATION_TOOLS = new Set(["write_file", "edit_file", "apply_patch"]);

const BUILTIN_TOOL_COPY: Record<string, ToolCopy> = {
  read_file: {
    running: "正在读取文件",
    succeeded: "已读取文件",
    failed: "已尝试读取文件",
  },
  write_file: {
    running: "正在写入文件",
    succeeded: "已写入文件",
    failed: "已尝试写入文件",
  },
  edit_file: {
    running: "正在编辑文件",
    succeeded: "已编辑文件",
    failed: "已尝试编辑文件",
  },
  apply_patch: {
    running: "正在编辑文件",
    succeeded: "已编辑文件",
    failed: "已尝试编辑文件",
  },
  list_dir: {
    running: "正在查看目录",
    succeeded: "已查看目录",
    failed: "已尝试查看目录",
  },
  find_files: {
    running: "正在查找文件",
    succeeded: "已查找文件",
    failed: "已尝试查找文件",
  },
  grep: {
    running: "正在搜索内容",
    succeeded: "已搜索内容",
    failed: "已尝试搜索内容",
  },
  exec: {
    running: "正在运行 Shell 命令",
    succeeded: "已运行 Shell 命令",
    failed: "已运行 Shell 命令",
  },
  write_stdin: {
    running: "正在向 Shell 发送输入",
    succeeded: "已向 Shell 发送输入",
    failed: "已尝试向 Shell 发送输入",
  },
  list_exec_sessions: {
    running: "正在查看 Shell 任务",
    succeeded: "已查看 Shell 任务",
    failed: "已尝试查看 Shell 任务",
  },
};

const INFERRED_TOOL_COPY: Array<{
  keywords: string[];
  copy: ToolCopy;
}> = [
  {
    keywords: ["search", "find", "query", "grep"],
    copy: actionCopy("搜索信息", "已搜索信息"),
  },
  {
    keywords: ["delete", "remove"],
    copy: actionCopy("删除内容", "已删除内容"),
  },
  {
    keywords: ["edit", "update", "patch", "modify"],
    copy: actionCopy("更新内容", "已更新内容"),
  },
  {
    keywords: ["create", "write", "save"],
    copy: actionCopy("创建内容", "已创建内容"),
  },
  {
    keywords: ["read", "get", "fetch", "download"],
    copy: actionCopy("获取信息", "已获取信息"),
  },
  {
    keywords: ["exec", "run", "execute", "shell"],
    copy: actionCopy("运行外部操作", "已运行外部操作"),
  },
  {
    keywords: ["send", "post", "upload"],
    copy: actionCopy("发送内容", "已发送内容"),
  },
  {
    keywords: ["list"],
    copy: actionCopy("查看列表", "已查看列表"),
  },
];

const FALLBACK_COPY: ToolCopy = {
  running: "正在执行外部操作",
  succeeded: "已完成外部操作",
  failed: "已执行外部操作",
};

function actionCopy(action: string, succeeded: string): ToolCopy {
  return {
    running: `正在${action}`,
    succeeded,
    failed: `已尝试${action}`,
  };
}

function inferredCopy(name: string): ToolCopy {
  const tokens = name.toLowerCase().split(/[^a-z0-9]+/).filter(Boolean);
  return (
    INFERRED_TOOL_COPY.find(({ keywords }) =>
      keywords.some((keyword) => tokens.includes(keyword)),
    )?.copy ?? FALLBACK_COPY
  );
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function shortValue(value: unknown): string {
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function displayFileName(path: string): string {
  return path.split(/[\\/]/).filter(Boolean).at(-1) || path;
}

function mutationSummary(tool: ToolPart): string | null {
  if (!MUTATION_TOOLS.has(tool.name)) return null;

  const argumentsValue = asRecord(tool.arguments);
  const argumentPaths =
    typeof argumentsValue?.path === "string"
      ? [argumentsValue.path]
      : Array.isArray(argumentsValue?.edits)
        ? argumentsValue.edits.flatMap((value) => {
            const edit = asRecord(value);
            return typeof edit?.path === "string" ? [edit.path] : [];
          })
        : [];
  const changes = tool.file_changes ?? [];
  const paths = Array.from(
    new Set(changes.length ? changes.map((change) => change.path) : argumentPaths),
  );
  const target =
    paths.length === 1
      ? displayFileName(paths[0])
      : paths.length > 1
        ? `${paths.length} 个文件`
        : "";
  const added = changes.reduce((sum, change) => sum + change.added, 0);
  const deleted = changes.reduce((sum, change) => sum + change.deleted, 0);
  const stats = [added ? `+${added}` : "", deleted ? `−${deleted}` : ""]
    .filter(Boolean)
    .join(" ");
  return [target, stats].filter(Boolean).join(" · ");
}

function toolSummary(tool: ToolPart): string {
  const mutation = mutationSummary(tool);
  if (mutation !== null) return mutation;

  const argumentsValue = asRecord(tool.arguments);
  if (!argumentsValue) return shortValue(tool.arguments || "").slice(0, 100);
  const preferredKey = ["path", "command", "query", "url"].find(
    (key) => argumentsValue[key] !== undefined,
  );
  if (preferredKey) return shortValue(argumentsValue[preferredKey]).slice(0, 100);
  return Object.entries(argumentsValue)
    .slice(0, 2)
    .map(([key, value]) => `${key}: ${shortValue(value)}`)
    .join(", ")
    .slice(0, 100);
}

function durationLabel(milliseconds: number | null): string {
  if (milliseconds === null) return "";
  if (milliseconds < 1_000) return `${milliseconds.toFixed(1)} ms`;
  return `${(milliseconds / 1_000).toFixed(1)} s`;
}

export function getToolPresentation(tool: ToolPart): ToolPresentation {
  const copy = BUILTIN_TOOL_COPY[tool.name] ?? inferredCopy(tool.name);
  return {
    label: copy[tool.state],
    summary: toolSummary(tool),
    duration: durationLabel(tool.elapsed_ms),
    technicalName: tool.name,
  };
}

export function isKnownTool(name: string): boolean {
  return name in BUILTIN_TOOL_COPY;
}
