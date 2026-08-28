import { memo } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

export const MarkdownMessage = memo(function MarkdownMessage({ children }: { children: string }) {
  return (
    <div className="markdown-content">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ children: linkChildren, ...props }) => (
            <a {...props} target="_blank" rel="noreferrer noopener">
              {linkChildren}
            </a>
          ),
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
});
