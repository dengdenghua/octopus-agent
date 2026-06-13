/**
 * Self-contained replay exporter — packages a process replay (a sequence of
 * frames + captions) into a single standalone ``.html`` file with an embedded
 * vanilla-JS player. No server, no login, no network: double-click the file
 * and it replays offline anywhere.
 *
 * This is the privacy-friendly answer to "shareable replay link": because the
 * artifact is a file the user downloads (and can inspect) before sending,
 * redaction happens at export time and nothing leaks beyond the frames handed
 * in. Pure + deterministic — given the same ReplayData, the same bytes — so it
 * is fully unit-testable without a browser. The caller maps its in-app replay
 * blocks (e.g. ``screenBlocks``) into ``ReplayData`` and inlines any remote
 * frame images as data-URLs first; this module never fetches.
 */

import { escapeXml } from "./share-card";

export interface ReplayFrame {
  /** A data-URL (``data:image/...``). Remote URLs must be inlined by the caller. */
  image: string;
  /** Step caption shown under the frame. */
  caption?: string;
}

export interface ReplayData {
  title: string;
  frames: ReplayFrame[];
  /** Brand line. Defaults to "Octopus Agent". */
  brand?: string;
  /** Footer note (e.g. a date). */
  footer?: string;
  /** Per-frame dwell time in ms when playing. Default 1200. */
  frameMs?: number;
}

/**
 * Embed a JS value safely inside a ``<script>`` tag: JSON-encode, then break up
 * any ``</`` so a hostile data-URL can't close the script element early.
 */
function embedJson(value: unknown): string {
  return JSON.stringify(value).replace(/<\//g, "<\\/").replace(/<!--/g, "<\\!--");
}

export function buildReplayHtml(replay: ReplayData): string {
  const title = (replay.title || "Octopus replay").trim();
  const brand = (replay.brand || "Octopus Agent").trim();
  const footer = (replay.footer || "").trim();
  const frameMs = Number.isFinite(replay.frameMs) ? Math.max(120, replay.frameMs as number) : 1200;
  const frames = (replay.frames || []).filter((f) => f && typeof f.image === "string" && f.image);

  const frameData = embedJson(
    frames.map((f) => ({ image: f.image, caption: (f.caption ?? "").toString() })),
  );

  const empty = frames.length === 0;

  // The player sets image .src + caption .textContent from the embedded data
  // (never innerHTML), so frame captions can't inject markup. The page chrome
  // (title/brand/footer) is XML-escaped here.
  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>${escapeXml(title)} · ${escapeXml(brand)}</title>
<style>
:root { color-scheme: dark; }
* { box-sizing: border-box; }
body { margin:0; background:#020617; color:#e2e8f0; font:14px/1.5 system-ui,-apple-system,sans-serif; }
.wrap { max-width: 980px; margin: 0 auto; padding: 20px 16px 40px; }
.bar { height:4px; background:#6366f1; border-radius:2px; margin-bottom:16px; }
.brand { color:#818cf8; font-weight:600; font-size:13px; }
h1 { font-size:20px; margin:4px 0 16px; color:#f8fafc; word-break:break-word; }
.stage { position:relative; background:#0f172a; border:1px solid #1e293b; border-radius:12px; overflow:hidden; min-height:200px; display:flex; align-items:center; justify-content:center; }
.stage img { max-width:100%; max-height:70vh; display:block; }
.empty { color:#64748b; padding:48px; text-align:center; }
.caption { min-height:22px; margin:12px 2px 0; color:#94a3b8; }
.controls { display:flex; align-items:center; gap:12px; margin-top:14px; }
button { background:#1e293b; color:#e2e8f0; border:1px solid #334155; border-radius:8px; padding:6px 12px; cursor:pointer; font:inherit; }
button:hover { background:#334155; }
input[type=range] { flex:1; accent-color:#6366f1; }
.counter { color:#64748b; font-variant-numeric:tabular-nums; min-width:60px; text-align:right; }
footer { margin-top:18px; color:#475569; font-size:12px; }
</style>
</head>
<body>
<div class="wrap">
<div class="bar"></div>
<div class="brand">${escapeXml(brand)} · replay</div>
<h1>${escapeXml(title)}</h1>
${
    empty
      ? `<div class="stage"><div class="empty">No frames in this replay.</div></div>`
      : `<div class="stage"><img id="frame" alt="replay frame"/></div>
<div class="caption" id="caption"></div>
<div class="controls">
<button id="prev" type="button">⟨ Prev</button>
<button id="play" type="button">▶ Play</button>
<button id="next" type="button">Next ⟩</button>
<input id="seek" type="range" min="0" value="0"/>
<span class="counter" id="counter"></span>
</div>`
  }
<footer>${escapeXml(footer)}</footer>
</div>
${
    empty
      ? ""
      : `<script>
(function(){
  var FRAMES = ${frameData};
  var MS = ${frameMs};
  var i = 0, timer = null;
  var img = document.getElementById('frame');
  var cap = document.getElementById('caption');
  var counter = document.getElementById('counter');
  var seek = document.getElementById('seek');
  var play = document.getElementById('play');
  seek.max = String(FRAMES.length - 1);
  function render(){
    var f = FRAMES[i] || {};
    img.src = f.image || '';
    cap.textContent = f.caption || '';
    counter.textContent = (i + 1) + ' / ' + FRAMES.length;
    seek.value = String(i);
  }
  function stop(){ if (timer){ clearInterval(timer); timer = null; } play.textContent = '▶ Play'; }
  function start(){
    if (i >= FRAMES.length - 1) i = 0;
    play.textContent = '❚❚ Pause';
    timer = setInterval(function(){
      if (i >= FRAMES.length - 1){ stop(); return; }
      i++; render();
    }, MS);
  }
  play.onclick = function(){ timer ? stop() : start(); };
  document.getElementById('prev').onclick = function(){ stop(); i = Math.max(0, i - 1); render(); };
  document.getElementById('next').onclick = function(){ stop(); i = Math.min(FRAMES.length - 1, i + 1); render(); };
  seek.oninput = function(){ stop(); i = Number(seek.value) || 0; render(); };
  render();
})();
</script>`
  }
</body>
</html>`;
}
