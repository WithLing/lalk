import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { MarkdownMessage } from "./MarkdownMessage";

describe("MarkdownMessage", () => {
  it("renders common and GFM markdown", () => {
    const markup = renderToStaticMarkup(
      <MarkdownMessage>{"**Bold**\n\n- [x] done\n\n| A | B |\n| - | - |\n| 1 | 2 |"}</MarkdownMessage>,
    );

    expect(markup).toContain("<strong>Bold</strong>");
    expect(markup).toContain('type="checkbox"');
    expect(markup).toContain("<table>");
  });

  it("does not render raw HTML and opens links externally", () => {
    const markup = renderToStaticMarkup(
      <MarkdownMessage>{"<script>alert(1)</script>\n\n[Open](https://example.com)"}</MarkdownMessage>,
    );

    expect(markup).not.toContain("<script>");
    expect(markup).toContain("&lt;script&gt;");
    expect(markup).toContain('target="_blank"');
    expect(markup).toContain('rel="noreferrer noopener"');
  });
});
