export type ChipKind = "strada" | "linea" | "fermata" | "luogo";

export type Segment =
  | { type: "text"; value: string }
  | { type: "number"; value: string }
  | { type: "chip"; kind: ChipKind; label: string };

export type Block =
  { type: "paragraph"; segments: Segment[] } | { type: "steps"; items: Segment[][] };

const WORD = String.raw`[\p{L}\p{N}]`;

// In ordine: chip `[[tipo:Etichetta]]`, numero esplicito `**8 min**`, quantità con unità (8 min,
// 6,79 km, 1158 m, 2 h, 30 %), orario `13:30`. Il resto è testo.
const INLINE = new RegExp(
  [
    String.raw`\[\[(strada|linea|fermata|luogo):([^\]\n]{1,80})\]\]`,
    String.raw`\*\*([^*\n]{1,40})\*\*`,
    String.raw`(?<!${WORD})\d+(?:[.,]\d+)?\s?(?:min|km|m|h|%)(?!${WORD})`,
    String.raw`(?<![\p{L}\p{N}:])\d{1,2}:\d{2}(?![\p{L}\p{N}:])`,
  ].join("|"),
  "gu",
);

const STEP = /^\s*\d+[.)]\s+(\S.*)$/;

/** Un testo in segmenti: testo semplice, numeri (da rendere in monospazio) e chip di entità. */
export function parseInline(line: string): Segment[] {
  const segments: Segment[] = [];
  let last = 0;
  for (const match of line.matchAll(INLINE)) {
    const start = match.index;
    if (start > last) segments.push({ type: "text", value: line.slice(last, start) });
    if (match[1]) {
      segments.push({ type: "chip", kind: match[1] as ChipKind, label: match[2].trim() });
    } else {
      segments.push({ type: "number", value: match[3] ?? match[0] });
    }
    last = start + match[0].length;
  }
  if (last < line.length) segments.push({ type: "text", value: line.slice(last) });
  return segments;
}

/** Il testo di una risposta in blocchi: paragrafi separati da una riga vuota ed elenchi di passi
 * numerati («1. …»). I numeri dei passi li rinumera l'interfaccia, non si fida del testo. */
export function parseAnswer(text: string): Block[] {
  const blocks: Block[] = [];
  let paragraph: string[] = [];
  let steps: Segment[][] = [];

  const flushParagraph = () => {
    if (paragraph.length > 0) {
      blocks.push({ type: "paragraph", segments: parseInline(paragraph.join("\n")) });
      paragraph = [];
    }
  };
  const flushSteps = () => {
    if (steps.length > 0) {
      blocks.push({ type: "steps", items: steps });
      steps = [];
    }
  };

  for (const raw of text.replace(/\r\n?/g, "\n").split("\n")) {
    const line = raw.trim();
    if (line === "") {
      flushParagraph();
      continue;
    }
    const step = STEP.exec(line);
    if (step) {
      flushParagraph();
      steps.push(parseInline(step[1]));
    } else {
      flushSteps();
      paragraph.push(line);
    }
  }
  flushParagraph();
  flushSteps();
  return blocks;
}
