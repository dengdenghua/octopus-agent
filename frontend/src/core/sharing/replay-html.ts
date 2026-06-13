/**
 * Self-contained replay exporter — packages an agent run (a sequence of steps,
 * each with a title / detail / optional screenshot) into a single standalone
 * ``.html`` file with an embedded vanilla-JS player. No server, no login, no
 * network: double-click the file and it replays offline anywhere.
 *
 * The shape mirrors the in-app workbench replay, which steps through
 * ``WorkBlock``s (terminal / browser / file / search / …) rather than a screen
 * recording — so a step is primarily text (command + output), with an optional
 * inlined screenshot when one exists. That makes the export faithful for coding
 * runs, not just computer-use ones.
 *
 * This is the privacy-friendly answer to "shareable replay link": the artifact
 * is a file the user downloads (and can inspect) before sending, so redaction
 * happens at export time and nothing leaks beyond the steps handed in. Pure +
 * deterministic — given the same ReplayData, the same bytes — so it is fully
 * unit-testable without a browser. The caller (see ``replay-from-blocks``) maps
 * its ``WorkBlock``s into ``ReplayData`` and inlines any remote screenshots as
 * data-URLs first; this module never fetches.
 */

import { escapeXml } from "./share-card";

export interface ReplayStep {
  /** One-line headline for the step (e.g. the tool/title). */
  title: string;
  /** Short secondary line (e.g. the target path / url). */
  subtitle?: string;
  /** Longer detail shown in a monospace block (command, output preview). */
  body?: string;
  /** Block kind — drives the glyph. One of terminal/browser/file/read/search/todo/agent/skill/swarm. */
  kind?: string;
  /** Status — drives the colour dot. done/error/running/waiting_approval/pending. */
  status?: string;
  /** Optional inlined screenshot as a data-URL. Remote URLs must be inlined by the caller. */
  image?: string;
}

export interface ReplayData {
  title: string;
  steps: ReplayStep[];
  /** Brand line. Defaults to "Octopus Agent". */
  brand?: string;
  /** Footer note (e.g. a date). */
  footer?: string;
  /** Per-step dwell time in ms when playing. Default 1400. */
  frameMs?: number;
}

/**
 * Embed a JS value safely inside a ``<script>`` tag: JSON-encode, then break up
 * any ``</`` and ``<!--`` so hostile content can't close the script element or
 * open a comment early.
 */
function embedJson(value: unknown): string {
  return JSON.stringify(value).replace(/<\//g, "<\\/").replace(/<!--/g, "<\\!--");
}

function cleanStep(step: ReplayStep): ReplayStep {
  return {
    title: (step.title ?? "").toString(),
    subtitle: step.subtitle ? step.subtitle.toString() : "",
    body: step.body ? step.body.toString() : "",
    kind: step.kind ? step.kind.toString() : "",
    status: step.status ? step.status.toString() : "",
    image: typeof step.image === "string" && step.image ? step.image : "",
  };
}

export function buildReplayHtml(replay: ReplayData): string {
  const title = (replay.title || "Octopus replay").trim();
  const brand = (replay.brand || "Octopus Agent").trim();
  const footer = (replay.footer || "").trim();
  const frameMs = Number.isFinite(replay.frameMs) ? Math.max(200, replay.frameMs as number) : 1400;
  const steps = (replay.steps || [])
    .filter((s) => s && (s.title || s.body || s.image))
    .map(cleanStep);

  const stepData = embedJson(steps);
  const empty = steps.length === 0;

  // Every dynamic value (titles, bodies, captions) is written into the DOM via
  // textContent / img.src by the player — never innerHTML — so step content can
  // never inject markup. Only the static page chrome is XML-escaped here.
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
.wrap { max-width: 1040px; margin: 0 auto; padding: 20px 16px 48px; }
.bar { height:4px; background:#6366f1; border-radius:2px; margin-bottom:16px; }
.brand { color:#818cf8; font-weight:600; font-size:13px; }
h1 { font-size:20px; margin:4px 0 18px; color:#f8fafc; word-break:break-word; }
.layout { display:grid; grid-template-columns: 280px 1fr; gap:16px; align-items:start; }
@media (max-width:760px){ .layout { grid-template-columns:1fr; } }
.steps { border:1px solid #1e293b; border-radius:12px; overflow:hidden; max-height:60vh; overflow-y:auto; background:#0b1220; }
.row { display:flex; align-items:center; gap:8px; width:100%; padding:8px 10px; border:0; background:transparent; color:inherit; cursor:pointer; text-align:left; font:inherit; border-bottom:1px solid #131c2e; }
.row:hover { background:#111a2c; }
.row.active { background:#172033; }
.row .n { color:#475569; font-variant-numeric:tabular-nums; font-size:11px; min-width:26px; }
.row .glyph { width:18px; text-align:center; }
.row .t { flex:1; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-size:12px; }
.dot { width:8px; height:8px; border-radius:50%; flex:none; background:#475569; }
.detail { border:1px solid #1e293b; border-radius:12px; padding:16px; background:#0f172a; min-height:200px; }
.detail .dtitle { font-size:15px; font-weight:600; color:#f1f5f9; word-break:break-word; }
.detail .dsub { color:#94a3b8; font-size:12px; margin-top:2px; word-break:break-word; }
.detail img { max-width:100%; max-height:48vh; display:block; margin:12px 0; border-radius:8px; border:1px solid #1e293b; }
.detail pre { white-space:pre-wrap; word-break:break-word; background:#020617; border:1px solid #1e293b; border-radius:8px; padding:10px; font:12px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace; color:#cbd5e1; margin:12px 0 0; max-height:40vh; overflow:auto; }
.controls { display:flex; align-items:center; gap:12px; margin-top:16px; }
button { background:#1e293b; color:#e2e8f0; border:1px solid #334155; border-radius:8px; padding:6px 12px; cursor:pointer; font:inherit; }
button:hover { background:#334155; }
input[type=range] { flex:1; accent-color:#6366f1; }
.counter { color:#64748b; font-variant-numeric:tabular-nums; min-width:64px; text-align:right; }
.hint { margin-top:8px; color:#475569; font-size:11px; }
button[aria-pressed="true"] { background:#4338ca; border-color:#6366f1; color:#fff; }
.empty { color:#64748b; padding:48px; text-align:center; }
footer { margin-top:20px; color:#475569; font-size:12px; }
</style>
</head>
<body>
<div class="wrap">
<div class="bar"></div>
<div class="brand">${escapeXml(brand)} · replay</div>
<h1>${escapeXml(title)}</h1>
${
    empty
      ? `<div class="detail"><div class="empty">No steps in this replay.</div></div>`
      : `<div class="layout">
<div class="steps" id="steps"></div>
<div>
<div class="detail">
<div class="dtitle" id="dtitle"></div>
<div class="dsub" id="dsub"></div>
<img id="dimg" alt="" hidden/>
<pre id="dbody" hidden></pre>
</div>
<div class="controls">
<button id="prev" type="button">⟨ Prev</button>
<button id="play" type="button">▶ Play</button>
<button id="next" type="button">Next ⟩</button>
<button id="loop" type="button" aria-pressed="false" title="循环播放">⟲ Loop</button>
<button id="speed" type="button" title="播放速度">1×</button>
<input id="seek" type="range" min="0" value="0"/>
<span class="counter" id="counter"></span>
</div>
<div class="hint">← → 切换 · 空格 播放/暂停 · Home/End 首尾</div>
</div>
</div>`
  }
<footer>${escapeXml(footer)}</footer>
</div>
${
    empty
      ? ""
      : `<script>
(function(){
  var STEPS = ${stepData};
  var MS = ${frameMs};
  var GLYPH = { terminal:'❯', browser:'\u{1f310}', file:'\u{1f4c4}', read:'\u{1f4d6}', search:'\u{1f50d}', todo:'☑', agent:'\u{1f916}', skill:'\u{1f9e9}', swarm:'\u{1f41d}' };
  var DOT = { done:'#22c55e', error:'#ef4444', running:'#6366f1', waiting_approval:'#f59e0b' };
  var i = 0, timer = null, loop = false, speedIdx = 1;
  var SPEEDS = [0.5, 1, 2];
  var stepsEl = document.getElementById('steps');
  var dtitle = document.getElementById('dtitle');
  var dsub = document.getElementById('dsub');
  var dimg = document.getElementById('dimg');
  var dbody = document.getElementById('dbody');
  var counter = document.getElementById('counter');
  var seek = document.getElementById('seek');
  var play = document.getElementById('play');
  var loopBtn = document.getElementById('loop');
  var speedBtn = document.getElementById('speed');
  var rows = [];
  seek.max = String(STEPS.length - 1);
  STEPS.forEach(function(s, idx){
    var row = document.createElement('button');
    row.type = 'button'; row.className = 'row';
    var n = document.createElement('span'); n.className = 'n'; n.textContent = String(idx + 1);
    var g = document.createElement('span'); g.className = 'glyph'; g.textContent = GLYPH[s.kind] || '•';
    var t = document.createElement('span'); t.className = 't'; t.textContent = s.title || '(step)';
    var d = document.createElement('span'); d.className = 'dot'; d.style.background = DOT[s.status] || '#475569';
    row.appendChild(n); row.appendChild(g); row.appendChild(t); row.appendChild(d);
    row.onclick = function(){ stop(); i = idx; render(); };
    stepsEl.appendChild(row); rows.push(row);
  });
  function render(){
    var s = STEPS[i] || {};
    rows.forEach(function(r, idx){ r.classList.toggle('active', idx === i); });
    if (rows[i]) rows[i].scrollIntoView({ block: 'nearest' });
    dtitle.textContent = s.title || '';
    dsub.textContent = s.subtitle || '';
    if (s.image){ dimg.src = s.image; dimg.hidden = false; } else { dimg.removeAttribute('src'); dimg.hidden = true; }
    if (s.body){ dbody.textContent = s.body; dbody.hidden = false; } else { dbody.textContent = ''; dbody.hidden = true; }
    counter.textContent = (i + 1) + ' / ' + STEPS.length;
    seek.value = String(i);
  }
  function stop(){ if (timer){ clearInterval(timer); timer = null; } play.textContent = '▶ Play'; }
  function tick(){
    if (i >= STEPS.length - 1){ if (loop){ i = 0; render(); return; } stop(); return; }
    i++; render();
  }
  function start(){
    if (i >= STEPS.length - 1 && !loop) i = 0;
    play.textContent = '❚❚ Pause';
    timer = setInterval(tick, Math.round(MS / SPEEDS[speedIdx]));
  }
  function go(n){ stop(); i = Math.max(0, Math.min(STEPS.length - 1, n)); render(); }
  play.onclick = function(){ timer ? stop() : start(); };
  loopBtn.onclick = function(){ loop = !loop; loopBtn.setAttribute('aria-pressed', loop ? 'true' : 'false'); };
  speedBtn.onclick = function(){
    speedIdx = (speedIdx + 1) % SPEEDS.length;
    speedBtn.textContent = SPEEDS[speedIdx] + '×';
    if (timer){ clearInterval(timer); timer = setInterval(tick, Math.round(MS / SPEEDS[speedIdx])); }
  };
  document.getElementById('prev').onclick = function(){ go(i - 1); };
  document.getElementById('next').onclick = function(){ go(i + 1); };
  seek.oninput = function(){ go(Number(seek.value) || 0); };
  document.addEventListener('keydown', function(e){
    if (e.key === 'ArrowLeft'){ go(i - 1); }
    else if (e.key === 'ArrowRight'){ go(i + 1); }
    else if (e.key === 'Home'){ go(0); }
    else if (e.key === 'End'){ go(STEPS.length - 1); }
    else if (e.key === ' ' || e.key === 'Spacebar'){ e.preventDefault(); timer ? stop() : start(); }
  });
  render();
})();
</script>`
  }
</body>
</html>`;
}
