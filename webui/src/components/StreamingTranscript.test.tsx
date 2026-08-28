import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { StreamingTranscript } from "./StreamingTranscript";

describe("StreamingTranscript", () => {
  it("shows a caret while recognition is still changing", () => {
    const markup = renderToStaticMarkup(
      <StreamingTranscript text="你好" isFinal={false} />,
    );

    expect(markup).toContain("streaming-transcript-caret");
  });

  it("settles without a caret for the final transcript", () => {
    const markup = renderToStaticMarkup(
      <StreamingTranscript text="你好世界" isFinal />,
    );

    expect(markup).toContain("你好世界");
    expect(markup).not.toContain("streaming-transcript-caret");
  });
});
