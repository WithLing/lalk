import { useEffect, useRef } from "react";
import type { RuntimeStage, RuntimeStatus } from "../../runtime/contracts";

const FRAME_INTERVAL_MS = 1_000 / 30;

const PALETTE = [
  [67, 129, 255],
  [79, 201, 255],
  [126, 99, 255],
  [255, 191, 92],
  [255, 112, 166],
] as const;

function clamp(value: number, min = 0, max = 1) {
  return Math.min(max, Math.max(min, value));
}

function smoothstep(edge0: number, edge1: number, value: number) {
  const amount = clamp((value - edge0) / (edge1 - edge0));
  return amount * amount * (3 - 2 * amount);
}

function hash(x: number, y: number) {
  const value = Math.sin(x * 127.1 + y * 311.7) * 43758.5453;
  return value - Math.floor(value);
}

function mixColor(a: readonly number[], b: readonly number[], amount: number) {
  return a.map((channel, index) => Math.round(channel + (b[index] - channel) * amount));
}

function samplePalette(position: number) {
  const scaled = ((position % 1) + 1) % 1 * PALETTE.length;
  const index = Math.floor(scaled) % PALETTE.length;
  return mixColor(PALETTE[index], PALETTE[(index + 1) % PALETTE.length], scaled - Math.floor(scaled));
}

export function useVoiceAnimation(
  stage: RuntimeStage,
  runtimeState: RuntimeStatus,
  inputLevel: number,
) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const runtimeVisualRef = useRef({ stage, runtimeState, inputLevel });
  runtimeVisualRef.current = { stage, runtimeState, inputLevel };

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const context = canvas.getContext("2d");
    if (!context) return;

    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let animationFrame = 0;
    let width = 1;
    let height = 1;
    let dpr = 1;
    let previousFrame = performance.now();
    let previousDraw = 0;
    let smoothedEnergy = 0.08;
    let flowClock = 0;
    let firstFrame = true;

    const resize = () => {
      const bounds = canvas.getBoundingClientRect();
      dpr = Math.min(window.devicePixelRatio || 1, 2);
      width = Math.max(1, bounds.width);
      height = Math.max(1, bounds.height);
      canvas.width = Math.round(width * dpr);
      canvas.height = Math.round(height * dpr);
      context.setTransform(dpr, 0, 0, dpr, 0, 0);
    };

    const observer = new ResizeObserver(resize);
    observer.observe(canvas);
    resize();

    const startedAt = performance.now();

    const draw = (now: number) => {
      if (!reducedMotion && now - previousDraw < FRAME_INTERVAL_MS) {
        animationFrame = requestAnimationFrame(draw);
        return;
      }
      previousDraw = now;
      const seconds = reducedMotion ? 4.5 : (now - startedAt) / 1000;
      const deltaSeconds = Math.min((now - previousFrame) / 1000, 0.05);
      previousFrame = now;
      const runtimeVisual = runtimeVisualRef.current;
      const runtimeVoice = runtimeVisual.stage === "playing"
        ? 1
        : runtimeVisual.stage === "user_speaking"
          ? clamp(runtimeVisual.inputLevel * 5, 0.08, 1)
          : ["transcribing", "thinking", "tool_running", "synthesizing"].includes(runtimeVisual.stage)
            ? 0.2
            : runtimeVisual.runtimeState === "running"
              ? 0.075
              : 0.025;
      const voice = runtimeVoice;

      const syllables =
        0.34 +
        0.22 * Math.sin(seconds * 7.1) +
        0.16 * Math.sin(seconds * 11.7 + 1.4) +
        0.1 * Math.sin(seconds * 19.3 + 0.2);
      const rawEnergy = 0.07 + voice * clamp(syllables, 0.08, 0.82);
      const smoothing = 1 - Math.exp(-deltaSeconds * (rawEnergy > smoothedEnergy ? 7 : 3.4));
      smoothedEnergy += (rawEnergy - smoothedEnergy) * smoothing;
      const energy = smoothedEnergy;
      const breath = 0.5 + 0.5 * Math.sin(seconds * 0.82);
      flowClock += deltaSeconds * (0.34 + energy * 1.05);

      if (firstFrame || reducedMotion) {
        context.clearRect(0, 0, width, height);
        firstFrame = false;
      } else {
        context.save();
        context.globalCompositeOperation = "destination-out";
        context.fillStyle = "rgba(0, 0, 0, 0.48)";
        context.fillRect(0, 0, width, height);
        context.restore();
      }

      const cell = width < 520 ? 11 : 13;
      const gap = width < 520 ? 3 : 3.5;
      const columns = Math.ceil(width / cell) + 2;
      const rows = Math.ceil(height / cell) + 2;
      const centerX = width * (0.5 + Math.sin(flowClock * 0.38) * 0.012);
      const centerY = height * (0.49 + Math.cos(flowClock * 0.32) * 0.01);
      const radiusX = width * (0.3 + breath * 0.018 + energy * 0.075);
      const radiusY = height * (0.31 + breath * 0.014 + energy * 0.06);

      for (let row = -1; row < rows; row += 1) {
        for (let column = -1; column < columns; column += 1) {
          const x = column * cell;
          const y = row * cell;
          const sourceX = (x - centerX) / radiusX;
          const sourceY = (y - centerY) / radiusY;
          const nx = sourceX;
          const ny = sourceY;
          const swirlX = nx + Math.sin(ny * 2.7 + flowClock * 1.1) * (0.07 + energy * 0.06);
          const swirlY = ny + Math.cos(nx * 2.45 - flowClock * 0.92) * (0.065 + energy * 0.05);
          const core1X = Math.sin(flowClock * 0.52) * 0.17;
          const core1Y = Math.cos(flowClock * 0.46) * 0.12;
          const core2X = Math.cos(flowClock * 0.39 + 1.7) * 0.39;
          const core2Y = Math.sin(flowClock * 0.48 + 0.4) * 0.26;
          const core3X = Math.sin(flowClock * 0.34 + 3.2) * 0.35;
          const core3Y = Math.cos(flowClock * 0.53 + 2.1) * 0.27;
          const d1 = (swirlX - core1X) ** 2 + (swirlY - core1Y) ** 2;
          const d2 = (swirlX - core2X) ** 2 + (swirlY - core2Y) ** 2;
          const d3 = (swirlX - core3X) ** 2 + (swirlY - core3Y) ** 2;
          const field = Math.exp(-d1 * 2.25) * 0.61 + Math.exp(-d2 * 5.1) * 0.38 + Math.exp(-d3 * 5.6) * 0.34;
          const distance = Math.sqrt(swirlX * swirlX + swirlY * swirlY);
          const angle = Math.atan2(swirlY, swirlX);
          const wave = Math.sin(distance * 9.2 - flowClock * 2.35 + angle * 2.7);
          const drift =
            Math.sin(column * 0.3 + flowClock * 0.8) *
            Math.cos(row * 0.27 - flowClock * 0.63);
          const orbit = 1.04 + Math.sin(angle * 3 - flowClock * 0.42) * 0.06;
          const orbitBand = Math.exp(-((distance - orbit) ** 2) * 42);
          const orbitPulse = smoothstep(0.52, 0.98, 0.5 + 0.5 * Math.sin(angle * 7 + flowClock * 0.56 + distance * 4));
          const satellites = orbitBand * orbitPulse * (0.035 + energy * 0.055);
          const body = smoothstep(0.085 - energy * 0.025, 0.68, field + satellites + wave * 0.018 + drift * 0.025);

          const grain = hash(column, row);
          const activation = body * (0.42 + energy * 1.12) + wave * energy * 0.08;
          const presence = smoothstep(grain * 0.68 - 0.12, grain * 0.68 + 0.18, activation);

          const shimmer = 0.84 + 0.16 * Math.sin(seconds * 1.35 + column * 0.19 - row * 0.14);
          const opacity = clamp(presence * body * (0.25 + activation * 0.72) * shimmer, 0, 0.82);
          if (opacity < 0.004) continue;
          const colorPosition =
            column * 0.028 + row * 0.021 + flowClock * 0.032 + field * 0.24 + wave * 0.055;
          const [red, green, blue] = samplePalette(colorPosition);
          const sizeJitter = 0.78 + grain * 0.14 + presence * 0.08 + energy * 0.06;
          const squareSize = (cell - gap) * sizeJitter;
          const flowStrength = 0.25 + energy * 1.15;
          const flowX = Math.sin(flowClock * 1.45 + row * 0.16 + column * 0.045) * flowStrength;
          const flowY = Math.cos(flowClock * 1.21 + column * 0.14 - row * 0.04) * flowStrength;

          context.fillStyle = `rgba(${red}, ${green}, ${blue}, ${opacity})`;
          context.beginPath();
          context.roundRect(
            x + (cell - squareSize) / 2 + flowX,
            y + (cell - squareSize) / 2 + flowY,
            squareSize,
            squareSize,
            Math.min(2.2, squareSize * 0.22),
          );
          context.fill();
        }
      }

      if (!reducedMotion) animationFrame = requestAnimationFrame(draw);
    };

    const handleVisibilityChange = () => {
      if (document.hidden) {
        cancelAnimationFrame(animationFrame);
        animationFrame = 0;
        return;
      }
      previousFrame = performance.now();
      previousDraw = 0;
      animationFrame = requestAnimationFrame(draw);
    };

    document.addEventListener("visibilitychange", handleVisibilityChange);
    if (!document.hidden) animationFrame = requestAnimationFrame(draw);
    return () => {
      observer.disconnect();
      document.removeEventListener("visibilitychange", handleVisibilityChange);
      cancelAnimationFrame(animationFrame);
    };
  }, []);

  return canvasRef;
}
