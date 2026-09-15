const PAGE_WIDTH = 595;
const PAGE_HEIGHT = 842;
const LEFT_MARGIN = 48;
const TOP_MARGIN = 794;
const BOTTOM_MARGIN = 52;
const LINE_HEIGHT = 14;
const MAX_FIELD_LENGTH = 8_000;

export function downloadTranscriptPdf(transcript) {
  const content = createTranscriptPdf(transcript);
  const objectUrl = URL.createObjectURL(new Blob([content], { type: "application/pdf" }));
  const link = document.createElement("a");
  link.href = objectUrl;
  link.download = "investigation-transcript.pdf";
  link.hidden = true;
  document.body.append(link);
  link.click();
  link.remove();
  globalThis.setTimeout(() => URL.revokeObjectURL(objectUrl), 60_000)?.unref?.();
}

export function createTranscriptPdf(transcript) {
  const lines = protocolLines(transcript);
  return buildPdf(paginate(lines));
}

function protocolLines(transcript) {
  const lines = [
    { text: "Industrial AI Agent", size: 14, color: "0.09 0.42 0.29" },
    { text: "Investigation Protocol", size: 18, color: "0.09 0.42 0.29" },
    { text: "Investigation ID: No persisted Investigation ID", size: 10 },
    { text: "Transcript-only protocol", size: 10 },
    { text: "", size: 8 },
  ];
  const turns = Array.isArray(transcript) ? transcript : [];
  for (const [index, turn] of turns.entries()) {
    if (!hasExportableTurn(turn)) continue;
    lines.push({ text: `Turn ${index + 1}`, size: 13, color: "0.09 0.42 0.29" });
    appendField(lines, "User", turn?.request);
    appendField(lines, "Agent", turn?.answer);
    if (turn?.error) {
      appendField(lines, "Error code", turn.error.code);
      appendField(lines, "Error", turn.error.message);
    }
    lines.push({ text: "", size: 8 });
  }
  return lines;
}

function appendField(lines, label, value) {
  const text = safeText(value);
  if (!text) return;
  lines.push({ text: label, size: 10, color: "0.11 0.20 0.16" });
  for (const line of wrap(text, 92)) lines.push({ text: line, size: 10 });
}

function hasExportableTurn(turn) {
  return Boolean(
    safeText(turn?.request) || safeText(turn?.answer) || safeText(turn?.error?.code),
  );
}

function safeText(value) {
  if (typeof value !== "string") return "";
  return value
    .slice(0, MAX_FIELD_LENGTH)
    .replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f-\u009f]/g, " ")
    .replace(/[^\u0020-\u00ff\n\t]/g, "?")
    .trim();
}

function wrap(value, maxLength) {
  const lines = [];
  for (const paragraph of value.split(/\r?\n/)) {
    let remaining = paragraph || " ";
    while (remaining.length > maxLength) {
      const boundary = remaining.lastIndexOf(" ", maxLength);
      const end = boundary > 0 ? boundary : maxLength;
      lines.push(remaining.slice(0, end));
      remaining = remaining.slice(end).trimStart();
    }
    lines.push(remaining);
  }
  return lines;
}

function paginate(lines) {
  const pages = [[]];
  let y = TOP_MARGIN;
  for (const line of lines) {
    const lineHeight = Math.max(LINE_HEIGHT, line.size + 4);
    if (y - lineHeight < BOTTOM_MARGIN) {
      pages.push([]);
      y = TOP_MARGIN;
    }
    pages.at(-1).push({ ...line, y });
    y -= lineHeight;
  }
  return pages;
}

function buildPdf(pages) {
  const objects = ["<< /Type /Catalog /Pages 2 0 R >>"];
  const pageObjectNumbers = pages.map((_, index) => 3 + index * 2);
  objects.push(`<< /Type /Pages /Kids [${pageObjectNumbers.map((number) => `${number} 0 R`).join(" ")}] /Count ${pages.length} >>`);
  for (const [index, page] of pages.entries()) {
    const content = pageContent(page);
    const contentObjectNumber = 4 + index * 2;
    objects.push(`<< /Type /Page /Parent 2 0 R /MediaBox [0 0 ${PAGE_WIDTH} ${PAGE_HEIGHT}] /Resources << /Font << /F1 << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> >> >> /Contents ${contentObjectNumber} 0 R >>`);
    objects.push(`<< /Length ${byteLength(content)} >>\nstream\n${content}\nendstream`);
  }

  let pdf = "%PDF-1.4\n%\xE2\xE3\xCF\xD3\n";
  const offsets = [0];
  for (const [index, object] of objects.entries()) {
    offsets.push(byteLength(pdf));
    pdf += `${index + 1} 0 obj\n${object}\nendobj\n`;
  }
  const startXref = byteLength(pdf);
  pdf += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n`;
  pdf += offsets.slice(1).map((offset) => `${String(offset).padStart(10, "0")} 00000 n \n`).join("");
  pdf += `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${startXref}\n%%EOF\n`;
  return latin1Bytes(pdf);
}

function pageContent(page) {
  return ["BT", ...page.flatMap((line) => [
    line.color ? `${line.color} rg` : "0 0 0 rg",
    `/F1 ${line.size} Tf`,
    `1 0 0 1 ${LEFT_MARGIN} ${line.y} Tm`,
    `(${pdfLiteral(line.text)}) Tj`,
  ]), "ET"].join("\n");
}

function pdfLiteral(value) {
  return safeText(value).replace(/([\\()])/g, "\\$1");
}

function byteLength(value) {
  return latin1Bytes(value).length;
}

function latin1Bytes(value) {
  const bytes = new Uint8Array(value.length);
  for (let index = 0; index < value.length; index += 1) bytes[index] = value.charCodeAt(index) & 0xff;
  return bytes;
}
