import { useCallback, useEffect, useRef, useState } from "react";

const STREAM_CATCH_UP_MS = 72;
const MIN_STREAM_CHARACTERS_PER_SECOND = 90;
const MAX_STREAM_FRAME_ELAPSED_MS = 50;

function takeCodePointPrefix(value: string, limit: number): string {
  let end = 0;
  let count = 0;
  for (const character of value) {
    if (count >= limit) break;
    end += character.length;
    count += 1;
  }
  return value.slice(0, end);
}

export function StreamingTranscript({
  text,
  isFinal,
}: {
  text: string;
  isFinal: boolean;
}) {
  const initialText = isFinal ? text : "";
  const [displayedText, setDisplayedText] = useState(initialText);
  const displayedTextRef = useRef(initialText);
  const targetTextRef = useRef(text);
  const animationRef = useRef<number | null>(null);
  const creditRef = useRef(0);
  const lastTimestampRef = useRef<number | null>(null);
  const paintRef = useRef<(timestamp: number) => void>(() => undefined);

  const schedulePaint = useCallback(() => {
    if (animationRef.current !== null) return;
    animationRef.current = window.requestAnimationFrame((timestamp) => {
      animationRef.current = null;
      paintRef.current(timestamp);
    });
  }, []);

  const paint = useCallback((timestamp: number) => {
    const current = displayedTextRef.current;
    const target = targetTextRef.current;
    if (current === target) {
      creditRef.current = 0;
      lastTimestampRef.current = null;
      return;
    }
    if (!target.startsWith(current)) {
      displayedTextRef.current = target;
      setDisplayedText(target);
      creditRef.current = 0;
      lastTimestampRef.current = null;
      return;
    }

    const pending = target.slice(current.length);
    const pendingCharacters = Array.from(pending).length;
    const elapsed = Math.min(
      MAX_STREAM_FRAME_ELAPSED_MS,
      Math.max(0, timestamp - (lastTimestampRef.current ?? timestamp)),
    );
    const charactersPerSecond = Math.max(
      MIN_STREAM_CHARACTERS_PER_SECOND,
      (pendingCharacters * 1_000) / STREAM_CATCH_UP_MS,
    );
    creditRef.current += charactersPerSecond * (elapsed / 1_000);
    lastTimestampRef.current = timestamp;

    const characterBudget = Math.floor(creditRef.current);
    if (characterBudget > 0) {
      const suffix = takeCodePointPrefix(pending, characterBudget);
      const next = current + suffix;
      displayedTextRef.current = next;
      setDisplayedText(next);
      creditRef.current -= Array.from(suffix).length;
    }

    if (displayedTextRef.current !== targetTextRef.current) schedulePaint();
    else {
      creditRef.current = 0;
      lastTimestampRef.current = null;
    }
  }, [schedulePaint]);
  paintRef.current = paint;

  useEffect(() => {
    targetTextRef.current = text;
    const current = displayedTextRef.current;
    if (text === current) return;

    if (
      window.matchMedia("(prefers-reduced-motion: reduce)").matches
      || !text.startsWith(current)
    ) {
      if (animationRef.current !== null) {
        window.cancelAnimationFrame(animationRef.current);
        animationRef.current = null;
      }
      displayedTextRef.current = text;
      setDisplayedText(text);
      creditRef.current = 0;
      lastTimestampRef.current = null;
      return;
    }
    schedulePaint();
  }, [schedulePaint, text]);

  useEffect(() => () => {
    if (animationRef.current !== null) {
      window.cancelAnimationFrame(animationRef.current);
    }
  }, []);

  return (
    <span className="streaming-transcript">
      {displayedText}
      {!isFinal && <span className="streaming-transcript-caret" aria-hidden="true" />}
    </span>
  );
}
