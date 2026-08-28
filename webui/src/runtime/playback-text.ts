import type { AssistantPart, Turn } from "./contracts";

const ignorableTrailingCharacter = /[\s\p{P}\p{S}]/u;

function normalizePlaybackCharacter(character: string): string {
  return character.normalize("NFKC").toLocaleLowerCase();
}

export function sourcePrefixForPlayback(source: string, spokenText: string): number {
  const sourceCharacters: Array<{ raw: string; value: string; end: number }> = [];
  let sourceOffset = 0;
  for (const character of source) {
    sourceOffset += character.length;
    sourceCharacters.push({
      raw: character,
      value: normalizePlaybackCharacter(character),
      end: sourceOffset,
    });
  }

  let sourceIndex = 0;
  let visibleOffset = 0;
  for (const spokenCharacter of spokenText) {
    if (/\s/u.test(spokenCharacter)) continue;
    const target = normalizePlaybackCharacter(spokenCharacter);
    let candidateIndex = sourceIndex;
    while (candidateIndex < sourceCharacters.length) {
      const sourceCharacter = sourceCharacters[candidateIndex];
      candidateIndex += 1;
      if (sourceCharacter.value !== target) continue;
      sourceIndex = candidateIndex;
      visibleOffset = sourceCharacter.end;
      break;
    }
  }

  while (
    sourceIndex < sourceCharacters.length
    && ignorableTrailingCharacter.test(sourceCharacters[sourceIndex].raw)
  ) {
    visibleOffset = sourceCharacters[sourceIndex++].end;
  }
  return visibleOffset;
}

export function alignPartsToPlayback(
  parts: AssistantPart[],
  spokenText: string,
): AssistantPart[] {
  const source = parts
    .filter((part) => part.type === "text")
    .map((part) => part.text)
    .join("");
  const visibleSourceLength = sourcePrefixForPlayback(source, spokenText);
  let sourceOffset = 0;
  let precedingTextComplete = true;
  return parts.flatMap<AssistantPart>((part) => {
    if (part.type === "tool") return precedingTextComplete ? [part] : [];

    const visibleLength = Math.max(
      0,
      Math.min(visibleSourceLength - sourceOffset, part.text.length),
    );
    const text = part.text.slice(0, visibleLength);
    sourceOffset += part.text.length;
    if (visibleLength < part.text.length) precedingTextComplete = false;
    return text ? [{ ...part, text }] : [];
  });
}

export function conversationScrollKey(turns: Turn[]): string {
  const turn = turns.at(-1);
  if (!turn) return "empty";

  const tools = turn.assistant.parts
    .filter((part) => part.type === "tool")
    .map((part) => `${part.call_id}:${part.state}`)
    .join(",");
  return [
    turns.length,
    turn.turn_id,
    turn.assistant.spoken_text.length,
    tools,
    turn.state,
    turn.error?.message ?? "",
  ].join("|");
}
