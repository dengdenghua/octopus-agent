export interface ExtractedCodeBlocks {
  html: string;
  css: string;
  js: string;
}

const BLOCK_RE = /```(html?|css|js|javascript)\s*\n([\s\S]*?)```/gi;

export function extractCodeBlocks(markdown: string): ExtractedCodeBlocks {
  const result: ExtractedCodeBlocks = { html: "", css: "", js: "" };
  let match: RegExpExecArray | null;
  while ((match = BLOCK_RE.exec(markdown)) !== null) {
    const lang = match[1]!.toLowerCase();
    const code = match[2]!.trimEnd();
    if (lang === "html" || lang === "htm") {
      result.html = code;
    } else if (lang === "css") {
      result.css = code;
    } else if (lang === "js" || lang === "javascript") {
      result.js = code;
    }
  }
  BLOCK_RE.lastIndex = 0;
  return result;
}

export function hasPreviewableBlocks(blocks: ExtractedCodeBlocks): boolean {
  return blocks.html.length > 0;
}
