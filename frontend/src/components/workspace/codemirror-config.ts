import type { Extension } from "@codemirror/state";
import { basicLightInit } from "@uiw/codemirror-theme-basic";
import { monokaiInit } from "@uiw/codemirror-theme-monokai";

export const customDarkTheme = monokaiInit({
  settings: {
    background: "transparent",
    gutterBackground: "transparent",
    gutterForeground: "#555",
    gutterActiveForeground: "#fff",
    fontSize: "var(--text-sm)",
  },
});

export const customLightTheme = basicLightInit({
  settings: {
    background: "transparent",
    fontSize: "var(--text-sm)",
  },
});

function fileExtension(filePath?: string): string {
  if (!filePath) return "";
  const normalized = filePath.split(/[?#]/, 1)[0] ?? filePath;
  const dot = normalized.lastIndexOf(".");
  if (dot < 0) return "";
  return normalized.slice(dot).toLowerCase();
}

export async function loadCodeMirrorExtensions(
  filePath?: string,
): Promise<Extension[]> {
  const ext = fileExtension(filePath);

  if ([".css", ".scss", ".sass", ".less"].includes(ext)) {
    const { css } = await import("@codemirror/lang-css");
    return [css()];
  }

  if ([".html", ".htm"].includes(ext)) {
    const { html } = await import("@codemirror/lang-html");
    return [html()];
  }

  if ([".js", ".mjs", ".cjs", ".jsx"].includes(ext)) {
    const { javascript } = await import("@codemirror/lang-javascript");
    return [javascript({ jsx: ext === ".jsx" })];
  }

  if ([".ts", ".tsx"].includes(ext)) {
    const { javascript } = await import("@codemirror/lang-javascript");
    return [javascript({ typescript: true, jsx: ext === ".tsx" })];
  }

  if (ext === ".json") {
    const { json } = await import("@codemirror/lang-json");
    return [json()];
  }

  if ([".md", ".mdx", ".markdown"].includes(ext)) {
    const [{ markdown, markdownLanguage }, { languages }] = await Promise.all([
      import("@codemirror/lang-markdown"),
      import("@codemirror/language-data"),
    ]);
    return [
      markdown({
        base: markdownLanguage,
        codeLanguages: languages,
      }),
    ];
  }

  if (ext === ".py") {
    const { python } = await import("@codemirror/lang-python");
    return [python()];
  }

  return [];
}
