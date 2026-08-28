import { memo, useEffect, useState } from "react";
import type {
  FileChange,
  ToolPart as ToolPartData,
} from "../runtime/contracts";
import {
  getToolPresentation,
  isKnownTool,
} from "./tool-presentation";

const MUTATION_TOOLS = new Set(["write_file", "edit_file", "apply_patch"]);
const READ_TOOLS = new Set(["read_file", "list_dir", "find_files", "grep"]);
const SHELL_TOOLS = new Set(["exec", "write_stdin", "list_exec_sessions"]);

interface DiffRow {
  kind: "context" | "addition" | "deletion" | "omitted";
  lineNumber: number | null;
  text: string;
}

const HUNK_HEADER =
  /^@@ -(?<oldStart>\d+)(?:,\d+)? \+(?<newStart>\d+)(?:,\d+)? @@/;

export function parseUnifiedDiff(unifiedDiff: string | undefined): DiffRow[] {
  if (!unifiedDiff) return [];

  const rows: DiffRow[] = [];
  let oldLine = 0;
  let newLine = 0;
  let inHunk = false;

  for (const line of unifiedDiff.split("\n")) {
    const header = HUNK_HEADER.exec(line);
    if (header?.groups) {
      if (inHunk && rows.length > 0) {
        rows.push({ kind: "omitted", lineNumber: null, text: "" });
      }
      oldLine = Number(header.groups.oldStart);
      newLine = Number(header.groups.newStart);
      inHunk = true;
      continue;
    }
    if (!inHunk || line.startsWith("\\ No newline")) continue;

    const marker = line[0];
    const text = line.slice(1);
    if (marker === " ") {
      rows.push({ kind: "context", lineNumber: newLine, text });
      oldLine += 1;
      newLine += 1;
    } else if (marker === "-") {
      rows.push({ kind: "deletion", lineNumber: oldLine, text });
      oldLine += 1;
    } else if (marker === "+") {
      rows.push({ kind: "addition", lineNumber: newLine, text });
      newLine += 1;
    }
  }

  return rows;
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function parseResult(value: string | null): Record<string, unknown> | null {
  if (!value) return null;
  try {
    return asRecord(JSON.parse(value));
  } catch {
    return null;
  }
}

function resultText(
  document: Record<string, unknown> | null,
  key: string,
): string {
  return typeof document?.[key] === "string" ? document[key] : "";
}

function argumentText(part: ToolPartData, key: string): string {
  const value = asRecord(part.arguments)?.[key];
  return typeof value === "string" ? value : "";
}

function ToolGlyph({ part }: { part: ToolPartData }) {
  if (part.state === "running") {
    return <span className="tool-step-spinner" aria-hidden="true" />;
  }
  if (MUTATION_TOOLS.has(part.name)) {
    return (
      <svg viewBox="0 0 16 16" aria-hidden="true">
        <path d="M3.1 11.85 2.7 14l2.15-.4 7.55-7.55-1.75-1.75Z" />
        <path d="m9.8 5.15 1.75 1.75M10.65 4.3l.75-.75a1.24 1.24 0 0 1 1.75 0l.1.1a1.24 1.24 0 0 1 0 1.75l-.85.65" />
      </svg>
    );
  }
  if (SHELL_TOOLS.has(part.name)) {
    return (
      <svg viewBox="0 0 16 16" aria-hidden="true">
        <rect x="2.25" y="3" width="11.5" height="10" rx="2" />
        <path d="m4.5 6 2 1.7-2 1.7M8.2 10h3" />
      </svg>
    );
  }
  return (
    <svg viewBox="0 0 16 16" aria-hidden="true">
      <path d="M2.5 4.25h4l1.1 1.25h5.9v6.25a1.5 1.5 0 0 1-1.5 1.5H4a1.5 1.5 0 0 1-1.5-1.5Z" />
      <path d="M5 8h6M5 10.25h4" />
    </svg>
  );
}

function ToolStepRow({
  part,
  open,
  expandable,
}: {
  part: ToolPartData;
  open: boolean;
  expandable: boolean;
}) {
  const presentation = getToolPresentation(part);
  return (
    <>
      <span className="tool-step-icon">
        <ToolGlyph part={part} />
      </span>
      <span className="tool-step-name">{presentation.label}</span>
      <span className="tool-step-summary">{presentation.summary}</span>
      <span className="tool-step-status">{presentation.duration}</span>
      {expandable ? (
        <span
          className={`tool-step-chevron${open ? " open" : ""}`}
          aria-hidden="true"
        />
      ) : (
        <span />
      )}
    </>
  );
}

const FileDiff = memo(function FileDiff({
  change,
  showFileName,
}: {
  change: FileChange;
  showFileName: boolean;
}) {
  const rows = parseUnifiedDiff(change.unified_diff);

  return (
    <section className="tool-file-diff">
      {showFileName ? (
        <header className="tool-file-diff-header">
          <span>{change.path}</span>
          <span>
            <i>+{change.added}</i>
            <b>−{change.deleted}</b>
          </span>
        </header>
      ) : null}
      <div className="tool-diff-code" role="region" aria-label={`${change.path} 文件差异`}>
        {rows.length > 0 ? (
          rows.map((row, index) => (
            <div
              className={`tool-diff-line ${row.kind}`}
              key={`${row.kind}-${row.lineNumber ?? "gap"}-${index}`}
            >
              <span className="tool-diff-marker" aria-hidden="true" />
              <span className="tool-diff-line-number" aria-hidden="true">
                {row.lineNumber ?? ""}
              </span>
              <code>{row.kind === "omitted" ? "" : row.text || " "}</code>
            </div>
          ))
        ) : (
          <div className="tool-diff-empty">
            {change.truncated
              ? "差异内容过大，仅保留修改统计"
              : "文件已修改，没有可展示的文本差异"}
          </div>
        )}
      </div>
    </section>
  );
});

function resultPaths(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item) => {
    if (typeof item === "string") return [item];
    const path = asRecord(item)?.path;
    return typeof path === "string" ? [path] : [];
  });
}

const ReadToolDetail = memo(function ReadToolDetail({
  part,
}: {
  part: ToolPartData;
}) {
  const document = parseResult(part.result);
  const metadata: string[] = [];
  const startLine = document?.start_line;
  const endLine = document?.end_line;
  if (typeof startLine === "number" && typeof endLine === "number") {
    metadata.push(`第 ${startLine}–${endLine} 行`);
  }
  const totalEntries = document?.total_entries;
  const totalMatches = document?.total_matches;
  if (typeof totalEntries === "number") metadata.push(`${totalEntries} 项`);
  if (typeof totalMatches === "number") metadata.push(`${totalMatches} 处结果`);
  if (document?.deduplicated === true) metadata.push("已读取过");
  if (document?.truncated === true) metadata.push("结果已截断");
  const items = Array.from(
    new Set([
      ...resultPaths(document?.entries),
      ...resultPaths(document?.files),
      ...resultPaths(document?.counts),
      ...resultPaths(document?.matches),
    ]),
  ).slice(0, 20);

  return (
    <div className="tool-read-details">
      <div className="tool-read-detail-row">
        <span>{getToolPresentation(part).label}</span>
        <code title={argumentText(part, "path") || resultText(document, "path")}>
          {argumentText(part, "path") || resultText(document, "path") || "."}
        </code>
        <span>{metadata.join(" · ")}</span>
      </div>
      {items.length > 0 ? (
        <div className="tool-read-result-items">
          {items.map((item) => <code key={item}>{item}</code>)}
        </div>
      ) : null}
    </div>
  );
});

const ShellToolDetail = memo(function ShellToolDetail({
  part,
}: {
  part: ToolPartData;
}) {
  const document = parseResult(part.result);
  const command = resultText(document, "command") || argumentText(part, "command");
  const output = resultText(document, "output") || resultText(document, "stdout");
  const stderr = resultText(document, "stderr");
  const exitCode = document?.exit_code;

  return (
    <div className="tool-shell-card">
      <div className="tool-detail-card-header">
        <span>Shell</span>
        <span>{typeof exitCode === "number" ? `exit ${exitCode}` : ""}</span>
      </div>
      {command ? (
        <div className="tool-shell-command"><span>$</span><code>{command}</code></div>
      ) : null}
      <div className="tool-shell-output">
        {output ? <pre>{output}</pre> : null}
        {stderr ? <pre>{stderr}</pre> : null}
        {!output && !stderr ? <div className="tool-detail-empty">命令没有输出</div> : null}
      </div>
    </div>
  );
});

const GenericToolDetail = memo(function GenericToolDetail({
  part,
}: {
  part: ToolPartData;
}) {
  const resultDocument = parseResult(part.result);
  const error = resultText(resultDocument, "error");
  return (
    <div className="tool-generic-card">
      <div className="tool-detail-card-header">
        <span>{part.name}</span>
        <span>{part.state === "failed" ? "执行失败" : "工具详情"}</span>
      </div>
      <section>
        <h4>Arguments</h4>
        <pre>{JSON.stringify(part.arguments, null, 2)}</pre>
      </section>
      {part.result !== null ? (
        <section className={error ? "error" : ""}>
          <h4>Result</h4>
          <pre>{part.result}</pre>
        </section>
      ) : null}
    </div>
  );
});

function ToolDetailPanel({ part }: { part: ToolPartData }) {
  const changes = part.file_changes ?? [];
  if (MUTATION_TOOLS.has(part.name) && changes.length > 0) {
    return (
      <div className="tool-mutation-files">
        {changes.map((change) => (
          <FileDiff
            change={change}
            key={change.path}
            showFileName={changes.length > 1}
          />
        ))}
      </div>
    );
  }
  if (READ_TOOLS.has(part.name) && part.state !== "failed") {
    return <ReadToolDetail part={part} />;
  }
  if (SHELL_TOOLS.has(part.name) && part.name !== "list_exec_sessions") {
    return <ShellToolDetail part={part} />;
  }
  return <GenericToolDetail part={part} />;
}

export const ToolPart = memo(function ToolPart({ part }: { part: ToolPartData }) {
  const changes = part.file_changes ?? [];
  const mutationWithDiff = MUTATION_TOOLS.has(part.name) && changes.length > 0;
  const expandable =
    mutationWithDiff ||
    READ_TOOLS.has(part.name) ||
    SHELL_TOOLS.has(part.name) ||
    !isKnownTool(part.name) ||
    part.state === "failed";
  const [open, setOpen] = useState(mutationWithDiff || part.state === "failed");

  useEffect(() => {
    if (mutationWithDiff || part.state === "failed") setOpen(true);
  }, [mutationWithDiff, part.state]);

  return (
    <article className={`message-row tool-row ${part.state}`} aria-label={`工具 ${part.name}`}>
      <section
        className={`tool-entry tool-step-${part.state}${open ? " open" : ""}${mutationWithDiff ? " mutation-diff" : ""}`}
      >
        {expandable ? (
          <button
            className="tool-step"
            type="button"
            aria-expanded={open}
            title={`工具：${part.name}`}
            onClick={() => setOpen((current) => !current)}
          >
            <ToolStepRow expandable open={open} part={part} />
          </button>
        ) : (
          <div className="tool-step" title={`工具：${part.name}`}>
            <ToolStepRow expandable={false} open={false} part={part} />
          </div>
        )}
        {open ? <div className="tool-detail-panel"><ToolDetailPanel part={part} /></div> : null}
      </section>
    </article>
  );
});
