import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const css = readFileSync(join(process.cwd(), "src/styles/globals.css"), "utf8");

describe("global appearance chrome rules", () => {
  it("keeps structural sidebar chrome hard-edged", () => {
    expect(css).toContain('[data-slot="sidebar-container"]');
    expect(css).toContain('[data-slot="sidebar-inner"]');
    expect(css).toContain('[data-slot="sidebar-inset"]');
    expect(css).toMatch(
      /\[data-slot="sidebar-container"\][\s\S]*?\[data-slot="sidebar-inner"\][\s\S]*?\[data-slot="sidebar-inset"\][\s\S]*?border-radius:\s*0\s*!important;/,
    );
  });

  it("keeps card and dialog radius controlled by the appearance scale", () => {
    expect(css).toMatch(
      /\[data-slot="card"\][\s\S]*?\[data-slot="dialog-content"\][\s\S]*?border-radius:\s*var\(--appearance-radius-2xl\)\s*!important;/,
    );
  });
});
