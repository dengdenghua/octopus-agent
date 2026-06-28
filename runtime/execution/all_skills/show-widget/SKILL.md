---
name: show-widget
description: Render a live interactive HTML/JS widget inline in the chat (dashboards, calculators, forms, sortable tables, parameter explorers, small games). Use when an interactive visual beats text or a static image. Emit a fenced widget code block with self-contained HTML.
tags: [render, visual, widget, ui, interactive]
---

# show-widget — inline interactive widgets

To render a **live, interactive** widget inside your reply, emit a fenced code
block whose language is `widget` (aliases: `html-widget`, `octopus-widget`)
containing **self-contained HTML** (inline `<style>` and `<script>` allowed).
The chat renders it in a sandboxed frame that auto-sizes to its content.

Example (a tiny counter):

    ```widget
    <div id="n" style="font:600 24px system-ui">0</div>
    <button onclick="n.textContent=+n.textContent+1">+1</button>
    ```

## When to use
- **Interactive**: calculators, forms, sortable/filterable tables, parameter
  explorers, dashboards, small games, live previews.
- Prefer **```mermaid```** for diagrams, inline `<svg>` / `<canvas>` for static
  charts, and plain markdown for static text — reach for a widget only when the
  user benefits from *interacting*.

## Rules (important)
- **Self-contained**: inline all CSS and JS; do not depend on app globals or
  external scripts (external network may be blocked).
- The widget runs in a **sandboxed iframe with a null origin**: it CANNOT read
  the user's session/cookies, the app DOM, or call app `/api/...` endpoints.
  Build it to work fully standalone — never try to reach the host app.
- Keep it lightweight and accessible; the frame reports its height automatically.
