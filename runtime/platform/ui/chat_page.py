

_CHAT_HTML = r"""<!doctype html>
<html lang="zh-CN" class="dark">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>🐙 Octopus · Chat</title>
<style>
  :root {
    --ink-950: #070a10;
    --ink-900: #0a0e14;
    --ink-800: #111721;
    --ink-700: #1a2433;
    --ink-600: #1f2733;
    --cephalo: #7a4dff;
    --cephalo-light: #b5a4ff;
    --sucker: #38bdf8;
    --ok: #a6e3a1;
    --warn: #f9e2af;
    --bad: #f38ba8;
    --mute: #6e7278;
    --slate: #d3d7de;
  }
  * { box-sizing: border-box; }
  html, body { margin: 0; padding: 0; height: 100%; }
  body {
    background: var(--ink-900);
    color: var(--slate);
    font-family: -apple-system, "Segoe UI", Roboto, sans-serif;
    font-size: 14px;
    display: flex;
    align-items: center;
    justify-content: center;
  }
  ::-webkit-scrollbar { width: 8px; height: 8px; }
  ::-webkit-scrollbar-track { background: var(--ink-950); }
  ::-webkit-scrollbar-thumb { background: var(--ink-600); border-radius: 4px; }
  ::-webkit-scrollbar-thumb:hover { background: var(--cephalo); }

  /* ─── Login ─── */
  .login-root {
    max-width: 380px;
    width: 100%;
    padding: 24px;
  }
  .login-root h1 {
    text-align: center;
    color: white;
    margin: 0 0 4px 0;
    font-weight: 600;
  }
  .login-root .sub {
    text-align: center;
    color: var(--mute);
    margin: 0 0 24px 0;
    font-size: 13px;
  }
  .card {
    background: var(--ink-800);
    border: 1px solid var(--ink-600);
    border-radius: 12px;
    padding: 20px;
  }
  .tabs {
    display: flex;
    gap: 4px;
    background: var(--ink-900);
    border: 1px solid var(--ink-700);
    border-radius: 6px;
    padding: 4px;
    margin-bottom: 16px;
  }
  .tabs button {
    flex: 1;
    padding: 8px 12px;
    border: none;
    background: transparent;
    color: var(--mute);
    border-radius: 4px;
    cursor: pointer;
    font-size: 13px;
  }
  .tabs button.active {
    background: rgba(122, 77, 255, 0.2);
    color: white;
  }
  label {
    display: block;
    font-size: 12px;
    color: var(--slate);
    margin-bottom: 4px;
    margin-top: 12px;
  }
  input, select {
    width: 100%;
    padding: 10px 12px;
    background: var(--ink-900);
    color: var(--slate);
    border: 1px solid var(--ink-600);
    border-radius: 6px;
    font-size: 14px;
    font-family: inherit;
  }
  input:focus, select:focus {
    outline: none;
    border-color: var(--cephalo);
  }
  input.code {
    font-family: "SF Mono", Consolas, monospace;
    font-size: 20px;
    letter-spacing: 6px;
    text-align: center;
  }
  button.primary {
    width: 100%;
    padding: 12px;
    background: var(--cephalo);
    color: white;
    border: none;
    border-radius: 6px;
    font-size: 14px;
    font-weight: 600;
    cursor: pointer;
    margin-top: 16px;
  }
  button.primary:hover:not(:disabled) {
    background: #5f2df0;
  }
  button.primary:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
  button.secondary {
    padding: 8px 12px;
    background: var(--ink-700);
    color: var(--slate);
    border: 1px solid var(--ink-600);
    border-radius: 6px;
    font-size: 13px;
    cursor: pointer;
  }
  button.secondary:hover { background: var(--ink-600); }
  .row { display: flex; gap: 8px; align-items: center; }
  .mock-hint {
    background: rgba(249, 226, 175, 0.1);
    border: 1px solid rgba(249, 226, 175, 0.3);
    color: var(--warn);
    padding: 8px 10px;
    border-radius: 6px;
    font-size: 11px;
    margin-bottom: 12px;
  }
  .dev-code {
    background: rgba(122, 77, 255, 0.15);
    border: 1px solid rgba(122, 77, 255, 0.4);
    color: var(--cephalo-light);
    padding: 8px 10px;
    border-radius: 6px;
    font-family: "SF Mono", Consolas, monospace;
    font-size: 12px;
    margin-bottom: 12px;
  }
  .err {
    color: var(--bad);
    background: rgba(243, 139, 168, 0.1);
    border: 1px solid rgba(243, 139, 168, 0.3);
    padding: 8px 10px;
    border-radius: 6px;
    font-size: 12px;
    margin-top: 10px;
  }
  .link {
    color: var(--cephalo-light);
    cursor: pointer;
    text-decoration: underline;
    background: none;
    border: none;
    font-size: 12px;
    padding: 0;
  }
  .link:disabled { color: var(--mute); text-decoration: none; cursor: default; }
  .footer {
    text-align: center;
    color: var(--mute);
    font-size: 11px;
    margin-top: 16px;
  }

  /* ═══════════════════════════════════════════════════════
     Chat · 参考 ChatGPT/Claude 的比例与节奏
  ═══════════════════════════════════════════════════════ */
  body.chatting {
    align-items: stretch;
    justify-content: center;
  }
  .chat-root {
    width: 100%;
    max-width: 820px;
    height: 100vh;
    display: flex;
    flex-direction: column;
  }

  /* Section styles. */
  .chat-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 12px 20px;
    border-bottom: 1px solid var(--ink-700);
    background: var(--ink-900);
  }
  .chat-header .who {
    display: flex;
    align-items: center;
    gap: 10px;
    min-width: 0;
    flex: 1;
  }
  .chat-header h2 {
    margin: 0;
    color: white;
    font-size: 14px;
    font-weight: 600;
  }
  .chat-header .info {
    font-size: 11px;
    color: var(--mute);
    margin-top: 2px;
    display: flex;
    align-items: center;
    gap: 6px;
  }
  .header-actions { display: flex; gap: 8px; flex-shrink: 0; }
  .icon-btn {
    width: 32px;
    height: 32px;
    border-radius: 6px;
    border: 1px solid var(--ink-600);
    background: transparent;
    color: var(--slate);
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 14px;
    transition: all 0.15s;
  }
  .icon-btn:hover { background: var(--ink-700); border-color: var(--cephalo); }

  .badge {
    display: inline-block;
    padding: 2px 7px;
    border-radius: 10px;
    font-size: 10px;
    border: 1px solid;
    font-weight: 500;
  }
  .badge.ok { background: rgba(166,227,161,0.12); color: var(--ok); border-color: rgba(166,227,161,0.3); }
  .badge.accent { background: rgba(122,77,255,0.2); color: var(--cephalo-light); border-color: rgba(122,77,255,0.5); }
  .badge.plain { background: var(--ink-800); color: var(--mute); border-color: var(--ink-600); }

  /* Section styles. */
  .chat-toolbar {
    display: flex;
    gap: 10px;
    align-items: center;
    padding: 10px 20px;
    border-bottom: 1px solid var(--ink-700);
    font-size: 12px;
  }
  .chat-toolbar label {
    margin: 0;
    color: var(--mute);
    font-size: 11px;
  }
  .chat-toolbar select {
    padding: 5px 10px;
    background: var(--ink-800);
    border: 1px solid var(--ink-600);
    border-radius: 6px;
    color: var(--slate);
    font-size: 12px;
    cursor: pointer;
    width: auto;
  }
  /* Section styles. */
  .switch {
    position: relative;
    display: inline-block;
    width: 34px;
    height: 18px;
    flex-shrink: 0;
  }
  .switch input { display: none; }
  .switch-slider {
    position: absolute;
    cursor: pointer;
    inset: 0;
    background: var(--ink-600);
    border-radius: 10px;
    transition: 0.18s;
  }
  .switch-slider::before {
    content: "";
    position: absolute;
    width: 14px; height: 14px;
    left: 2px; top: 2px;
    background: var(--slate);
    border-radius: 50%;
    transition: 0.18s;
  }
  .switch input:checked + .switch-slider {
    background: var(--cephalo);
  }
  .switch input:checked + .switch-slider::before {
    transform: translateX(16px);
    background: white;
  }
  .switch-wrap {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    font-size: 12px;
    color: var(--mute);
    cursor: pointer;
    user-select: none;
  }
  .switch-wrap.active { color: var(--cephalo-light); }

  /* Section styles. */
  .md-picker { position: relative; display: inline-block; }
  .md-trigger {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 5px 10px;
    background: var(--ink-800);
    border: 1px solid var(--ink-600);
    border-radius: 6px;
    color: var(--slate);
    font-size: 12px;
    cursor: pointer;
    min-width: 160px;
  }
  .md-trigger:hover { border-color: var(--cephalo); }
  .md-trigger .arrow { margin-left: auto; font-size: 10px; color: var(--mute); }
  .md-popup {
    position: absolute;
    top: calc(100% + 4px);
    left: 0;
    z-index: 50;
    min-width: 260px;
    background: var(--ink-800);
    border: 1px solid var(--ink-600);
    border-radius: 8px;
    box-shadow: 0 8px 24px rgba(0,0,0,0.5);
    overflow: hidden;
    animation: fadein 0.12s ease-out;
  }
  .md-tabs {
    display: flex;
    padding: 4px;
    gap: 2px;
    background: var(--ink-900);
    border-bottom: 1px solid var(--ink-700);
  }
  .md-tabs button {
    flex: 1;
    padding: 6px 10px;
    border: none;
    background: transparent;
    color: var(--mute);
    border-radius: 5px;
    font-size: 12px;
    cursor: pointer;
    transition: all 0.15s;
  }
  .md-tabs button.active {
    background: var(--cephalo);
    color: white;
  }
  .md-tabs button:not(.active):hover {
    color: var(--slate);
    background: var(--ink-800);
  }
  .md-list {
    max-height: 280px;
    overflow-y: auto;
    padding: 4px;
  }
  .md-item {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 7px 10px;
    border-radius: 5px;
    cursor: pointer;
    font-size: 13px;
    color: var(--slate);
  }
  .md-item:hover { background: var(--ink-700); }
  .md-item.active {
    background: rgba(122,77,255,0.18);
    color: white;
  }
  .md-item .m-id {
    margin-left: auto;
    font-family: "SF Mono", Consolas, monospace;
    font-size: 10px;
    color: var(--mute);
  }
  .md-item .m-badge {
    font-size: 9px;
    padding: 1px 5px;
    border-radius: 3px;
    background: rgba(56,189,248,0.15);
    color: var(--sucker);
    border: 1px solid rgba(56,189,248,0.4);
  }
  .md-empty {
    padding: 20px 12px;
    text-align: center;
    color: var(--mute);
    font-size: 12px;
  }
  .md-foot {
    border-top: 1px solid var(--ink-700);
    padding: 6px;
    display: flex;
    justify-content: flex-end;
  }
  .md-foot button {
    padding: 5px 10px;
    background: transparent;
    border: 1px solid var(--ink-600);
    color: var(--slate);
    border-radius: 5px;
    cursor: pointer;
    font-size: 11px;
  }
  .md-foot button:hover { background: var(--ink-700); border-color: var(--cephalo); }

  .mode-pill {
    display: inline-flex;
    gap: 2px;
    padding: 2px;
    background: var(--ink-900);
    border: 1px solid var(--ink-600);
    border-radius: 8px;
  }
  .mode-pill button {
    padding: 5px 12px;
    border: none;
    background: transparent;
    color: var(--mute);
    border-radius: 6px;
    font-size: 12px;
    cursor: pointer;
    transition: all 0.15s;
  }
  .mode-pill button.active {
    background: var(--cephalo);
    color: white;
  }
  .mode-pill button:not(.active):hover {
    color: var(--slate);
    background: var(--ink-800);
  }
  .chat-toolbar .credits {
    margin-left: auto;
    font-family: "SF Mono", Consolas, monospace;
    font-size: 12px;
    color: var(--ok);
    display: flex;
    align-items: center;
    gap: 4px;
  }

  /* Section styles. */
  .messages {
    flex: 1;
    overflow-y: auto;
    padding: 24px 20px 16px;
  }
  .messages-inner {
    max-width: 704px;
    margin: 0 auto;
    display: flex;
    flex-direction: column;
    gap: 20px;
  }

  .msg-row {
    display: flex;
    gap: 12px;
    align-items: flex-start;
    animation: fadein 0.18s ease-out;
  }
  @keyframes fadein {
    from { opacity: 0; transform: translateY(4px); }
    to   { opacity: 1; transform: translateY(0); }
  }
  .msg-avatar {
    width: 32px;
    height: 32px;
    border-radius: 50%;
    flex-shrink: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 16px;
    margin-top: 2px;
    user-select: none;
  }
  .msg-row.user .msg-avatar {
    background: linear-gradient(135deg, #7a4dff 0%, #38bdf8 100%);
    color: white;
    font-weight: 600;
    font-size: 13px;
  }
  .msg-row.assistant .msg-avatar {
    background: var(--ink-800);
    border: 1px solid var(--ink-600);
  }

  .msg-body {
    flex: 1;
    min-width: 0;
    padding-top: 4px;
  }
  .msg-meta {
    display: flex;
    align-items: baseline;
    gap: 8px;
    margin-bottom: 4px;
    font-size: 12px;
  }
  .msg-meta .role {
    font-weight: 600;
    color: white;
  }
  .msg-meta .model {
    font-size: 11px;
    color: var(--mute);
    font-family: "SF Mono", Consolas, monospace;
  }
  .msg-content {
    color: var(--slate);
    line-height: 1.65;
    font-size: 14.5px;
    white-space: pre-wrap;
    word-break: break-word;
  }
  .msg-content code {
    background: var(--ink-800);
    border: 1px solid var(--ink-700);
    padding: 1px 6px;
    border-radius: 3px;
    font-family: "SF Mono", Consolas, monospace;
    font-size: 13px;
  }
  .msg-content pre {
    background: var(--ink-950);
    border: 1px solid var(--ink-700);
    padding: 10px 14px;
    border-radius: 6px;
    overflow-x: auto;
    margin: 8px 0;
  }
  .msg-content pre code {
    background: transparent;
    border: 0;
    padding: 0;
    font-size: 12.5px;
  }
  .msg-usage {
    margin-top: 6px;
    font-size: 10.5px;
    color: var(--mute);
    font-family: "SF Mono", Consolas, monospace;
  }
  .msg-row.error .msg-content { color: var(--bad); }

  /* Section styles. */
  .composer-wrap {
    padding: 16px 20px 24px;
    background: var(--ink-900);
    border-top: 1px solid var(--ink-700);
  }
  .composer {
    max-width: 704px;
    margin: 0 auto;
    position: relative;
    background: var(--ink-800);
    border: 1px solid var(--ink-600);
    border-radius: 14px;
    transition: border-color 0.15s, box-shadow 0.15s;
  }
  .composer:focus-within {
    border-color: var(--cephalo);
    box-shadow: 0 0 0 3px rgba(122, 77, 255, 0.15);
  }
  .composer textarea {
    width: 100%;
    padding: 14px 56px 14px 18px;
    background: transparent;
    border: none;
    outline: none;
    color: var(--slate);
    font-size: 14.5px;
    line-height: 1.5;
    font-family: inherit;
    resize: none;
    min-height: 52px;
    max-height: 240px;
    display: block;
  }
  .composer textarea::placeholder { color: var(--mute); }
  .send-btn {
    position: absolute;
    right: 8px;
    bottom: 8px;
    width: 36px;
    height: 36px;
    border-radius: 10px;
    border: none;
    background: var(--cephalo);
    color: white;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: all 0.15s;
  }
  .send-btn:hover:not(:disabled) {
    background: #5f2df0;
    transform: scale(1.05);
  }
  .send-btn:disabled {
    background: var(--ink-700);
    color: var(--mute);
    cursor: not-allowed;
    transform: none;
  }
  .send-btn svg { width: 18px; height: 18px; }

  .composer-hint {
    max-width: 704px;
    margin: 6px auto 0;
    font-size: 10.5px;
    color: var(--mute);
    text-align: center;
  }

  /* Section styles. */
  .empty {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    text-align: center;
    color: var(--slate);
    padding: 40px 20px;
  }
  .empty-icon { font-size: 48px; margin-bottom: 16px; }
  .empty-title { font-size: 18px; color: white; font-weight: 600; margin-bottom: 6px; }
  .empty-sub { font-size: 13px; color: var(--mute); max-width: 400px; line-height: 1.6; }

  .hint-kbd {
    display: inline-block;
    padding: 1px 6px;
    background: var(--ink-800);
    border: 1px solid var(--ink-600);
    border-radius: 3px;
    font-family: "SF Mono", Consolas, monospace;
    font-size: 10px;
    color: var(--slate);
  }

  .thinking {
    display: flex;
    gap: 12px;
    align-items: center;
    padding: 4px 0;
    color: var(--mute);
    font-size: 13px;
  }
  .thinking-dot {
    width: 6px; height: 6px; border-radius: 50%;
    background: var(--cephalo-light);
    animation: bounce 1.4s infinite;
  }
  .thinking-dot:nth-child(2) { animation-delay: 0.2s; }
  .thinking-dot:nth-child(3) { animation-delay: 0.4s; }
  @keyframes bounce {
    0%, 60%, 100% { transform: translateY(0); opacity: 0.4; }
    30% { transform: translateY(-6px); opacity: 1; }
  }

  /* Section styles. */
  .modal-backdrop {
    position: fixed; inset: 0;
    background: rgba(7, 10, 16, 0.75);
    display: flex; align-items: center; justify-content: center;
    z-index: 100;
    animation: fadein 0.15s ease-out;
  }
  .modal {
    background: var(--ink-800);
    border: 1px solid var(--ink-600);
    border-radius: 12px;
    width: min(560px, 92vw);
    max-height: 88vh;
    overflow: hidden;
    display: flex;
    flex-direction: column;
  }
  .modal-head {
    padding: 14px 18px;
    border-bottom: 1px solid var(--ink-700);
    display: flex;
    justify-content: space-between;
    align-items: center;
  }
  .modal-head h3 { margin: 0; color: white; font-size: 15px; }
  .modal-body { padding: 16px 18px; overflow-y: auto; }
  .modal-foot {
    padding: 12px 18px;
    border-top: 1px solid var(--ink-700);
    display: flex;
    justify-content: flex-end;
    gap: 8px;
  }
  .model-list { display: flex; flex-direction: column; gap: 6px; margin-bottom: 12px; }
  .model-item {
    padding: 8px 12px;
    background: var(--ink-900);
    border: 1px solid var(--ink-700);
    border-radius: 6px;
    display: flex;
    align-items: center;
    gap: 10px;
    font-size: 13px;
  }
  .model-item .mid { flex: 1; font-family: "SF Mono", Consolas, monospace; font-size: 12px; }
  .model-item .mlabel { color: var(--slate); font-weight: 500; }
  .model-item.builtin { opacity: 0.65; }
  .model-item .tag {
    font-size: 10px;
    padding: 1px 6px;
    border-radius: 3px;
    border: 1px solid;
  }
  .model-item .tag.b { background: var(--ink-700); color: var(--mute); border-color: var(--ink-600); }
  .model-item .tag.c { background: rgba(122,77,255,0.2); color: var(--cephalo-light); border-color: rgba(122,77,255,0.5); }
  .model-item .tag.ext { background: rgba(56,189,248,0.15); color: var(--sucker); border-color: rgba(56,189,248,0.4); }
  .model-item button {
    border: none;
    background: transparent;
    color: var(--bad);
    cursor: pointer;
    padding: 2px 6px;
    font-size: 13px;
    opacity: 0.6;
  }
  .model-item button:hover { opacity: 1; }
  .add-form { background: var(--ink-900); border: 1px dashed var(--ink-600); border-radius: 6px; padding: 12px; margin-top: 8px; }
  .add-form label { margin-top: 0; font-size: 11px; }
  .add-form input { padding: 7px 10px; font-size: 13px; margin-bottom: 4px; }
  .add-form .row { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
  .form-hint { font-size: 10px; color: var(--mute); margin-top: 2px; line-height: 1.4; }
</style>
</head>
<body>
<div id="root"></div>

<script>
// ═══════════════════════════════════════════════════════════
// Section logic.
// ═══════════════════════════════════════════════════════════

const LS = {
  get(k) { return localStorage.getItem(k); },
  set(k, v) { localStorage.setItem(k, v); },
  del(k) { localStorage.removeItem(k); },
};

function authHeaders() {
  const jwt = LS.get('octopus.jwt');
  return jwt ? { 'Authorization': 'Bearer ' + jwt } : {};
}

async function api(method, path, body = null) {
  const isAuthEndpoint = path.startsWith('/api/auth/');
  const r = await fetch(path, {
    method,
    headers: {
      'Content-Type': 'application/json',
      ...authHeaders(),
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  const text = await r.text();
  if (!r.ok) {
    // Section logic.
    if (r.status === 401 && !isAuthEndpoint && LS.get('octopus.jwt')) {
      console.warn('JWT 401 · clearing session and returning to login');
      ['octopus.jwt','octopus.actor_id','octopus.provider','octopus.display','octopus.model']
        .forEach(k => LS.del(k));
      setTimeout(() => render(), 100);
    }
    const err = new Error(`HTTP ${r.status}: ${text.slice(0, 200)}`);
    err.status = r.status;
    err.body = text;
    throw err;
  }
  try { return JSON.parse(text); }
  catch { return text; }
}

// ═══════════════════════════════════════════════════════════
// Router
// ═══════════════════════════════════════════════════════════

function render() {
  if (LS.get('octopus.jwt')) {
    renderChat();
  } else {
    renderLogin();
  }
}

// ═══════════════════════════════════════════════════════════
// Login page
// ═══════════════════════════════════════════════════════════

async function renderLogin() {
  const root = document.getElementById('root');
  root.innerHTML = `
    <div class="login-root">
      <h1>🐙 Octopus</h1>
      <p class="sub">登录使用 agent + 官方大模型</p>
      <div class="card" id="login-card">
        <div class="loading">加载登录方式…</div>
      </div>
      <p class="footer">
        JWT 存本地 · 退出即清 · 无密码模式仅限内网
      </p>
    </div>
  `;

  let providers = [];
  try {
    const r = await api('GET', '/api/auth/providers');
    providers = r.providers || [];
  } catch (e) {
    document.getElementById('login-card').innerHTML = `
      <div class="err">加载登录方式失败：${e.message}</div>
    `;
    return;
  }

  if (providers.length === 0) {
    document.getElementById('login-card').innerHTML = `
      <div class="err">
        ⚠️ 服务端没开启任何登录方式<br>
        <span style="font-size:11px;color:var(--mute);margin-top:8px;display:block">
          设 <code>config.molili.enabled=true</code> 或 <code>config.local_auth.enabled=true</code>
        </span>
      </div>
    `;
    return;
  }

  const hasMolili = providers.find(p => p.id === 'molili');
  const hasLocal = providers.find(p => p.id === 'local');
  let activeTab = hasMolili ? 'molili' : 'local';

  const mockMode = hasMolili?.mock_mode;
  const localPwRequired = Boolean(hasLocal?.password_required);

  function paint() {
    const c = document.getElementById('login-card');
    c.innerHTML = `
      ${providers.length > 1 ? `
        <div class="tabs">
          ${hasMolili ? `<button class="${activeTab==='molili'?'active':''}" data-tab="molili">📱 手机号</button>` : ''}
          ${hasLocal ? `<button class="${activeTab==='local'?'active':''}" data-tab="local">💻 本地</button>` : ''}
        </div>
      ` : ''}
      <div id="tab-body"></div>
    `;
    c.querySelectorAll('[data-tab]').forEach(b => {
      b.onclick = () => { activeTab = b.dataset.tab; paint(); };
    });
    if (activeTab === 'molili') smsForm(mockMode);
    else localForm(localPwRequired);
  }
  paint();
}

function smsForm(mockMode) {
  const body = document.getElementById('tab-body');
  body.innerHTML = `
    ${mockMode ? `<div class="mock-hint">⚙️ Mock 模式 · 无真实短信 · 仅 dev/demo</div>` : ''}
    <div id="sms-step-phone">
      <label>手机号</label>
      <input id="phone" type="tel" placeholder="13800001234" autocomplete="tel" autofocus>
      <button class="primary" id="send-btn">获取验证码</button>
    </div>
    <div id="sms-step-code" style="display:none">
      <div class="info" style="font-size:12px;color:var(--mute);margin-bottom:6px">
        已发至 <span id="phone-mask" style="color:var(--slate);font-family:monospace"></span> ·
        <button class="link" id="resend-btn">重发</button>
      </div>
      <div id="dev-code-hint" style="display:none"></div>
      <label>验证码</label>
      <input id="code" class="code" type="text" maxlength="8" inputmode="numeric" autocomplete="one-time-code" placeholder="••••••">
      <div class="row" style="margin-top:12px">
        <button class="secondary" id="back-btn" style="flex:1">返回</button>
        <button class="primary" id="verify-btn" style="flex:2;margin-top:0">登录</button>
      </div>
    </div>
    <div id="sms-err"></div>
  `;

  const phoneInput = document.getElementById('phone');
  const codeInput = document.getElementById('code');
  const sendBtn = document.getElementById('send-btn');
  const verifyBtn = document.getElementById('verify-btn');
  const backBtn = document.getElementById('back-btn');
  const resendBtn = document.getElementById('resend-btn');
  const errBox = document.getElementById('sms-err');
  let cooldown = 0, cooldownTimer = null;

  function showErr(msg) {
    errBox.innerHTML = msg ? `<div class="err">${msg}</div>` : '';
  }
  function tick() {
    if (cooldown > 0) {
      cooldown--;
      sendBtn.textContent = `${cooldown}s 后重试`;
      resendBtn.textContent = `${cooldown}s 后重发`;
      resendBtn.disabled = true;
      sendBtn.disabled = true;
    } else {
      sendBtn.textContent = '获取验证码';
      resendBtn.textContent = '重发';
      resendBtn.disabled = false;
      sendBtn.disabled = false;
      clearInterval(cooldownTimer);
    }
  }
  function cleanPhone() {
    return (phoneInput.value || '').replace(/\D/g, '');
  }
  function maskPhone(p) {
    return p.length >= 7 ? p.slice(0,3) + '****' + p.slice(-4) : p;
  }

  async function doSend() {
    const phone = cleanPhone();
    if (phone.length < 11) return;
    showErr('');
    sendBtn.disabled = true; resendBtn.disabled = true;
    try {
      const r = await api('POST', '/api/auth/molili/sms/send', { phone });
      document.getElementById('sms-step-phone').style.display = 'none';
      document.getElementById('sms-step-code').style.display = '';
      document.getElementById('phone-mask').textContent = maskPhone(phone);
      const hint = document.getElementById('dev-code-hint');
      if (mockMode && r?.upstream?.code_for_dev) {
        hint.style.display = '';
        hint.className = 'dev-code';
        hint.textContent = '[mock] 验证码 · ' + r.upstream.code_for_dev;
      } else if (mockMode) {
        hint.style.display = '';
        hint.className = 'dev-code';
        hint.textContent = '[mock] 服务端 log 里看验证码 · 搜 [MOCK SMS]';
      }
      codeInput.focus();
      cooldown = 60;
      cooldownTimer = setInterval(tick, 1000); tick();
    } catch (e) {
      showErr(explainErr(e));
      sendBtn.disabled = false;
    }
  }
  async function doVerify() {
    const phone = cleanPhone();
    const code = (codeInput.value || '').trim();
    if (code.length < 4) return;
    showErr('');
    verifyBtn.disabled = true;
    try {
      const r = await api('POST', '/api/auth/molili/sms/verify', { phone, code });
      if (!r?.access_token) throw new Error('no access_token');
      LS.set('octopus.jwt', r.access_token);
      LS.set('octopus.actor_id', r.actor_id);
      LS.set('octopus.provider', 'molili');
      LS.set('octopus.display', r.user?.mobile || phone);
      render();
    } catch (e) {
      showErr(explainErr(e));
      verifyBtn.disabled = false;
    }
  }

  sendBtn.onclick = doSend;
  resendBtn.onclick = doSend;
  verifyBtn.onclick = doVerify;
  backBtn.onclick = () => {
    document.getElementById('sms-step-phone').style.display = '';
    document.getElementById('sms-step-code').style.display = 'none';
    codeInput.value = '';
  };
  phoneInput.onkeydown = (e) => { if (e.key === 'Enter') doSend(); };
  codeInput.onkeydown = (e) => { if (e.key === 'Enter') doVerify(); };
}

function localForm(passwordRequired) {
  const body = document.getElementById('tab-body');
  body.innerHTML = `
    <div class="mock-hint" style="color:var(--warn)">
      ${passwordRequired
        ? '🔒 需账号密码 · 询问管理员'
        : '⚠️ 无密码 · 输入用户名即可登录 · 仅限本机/内网'}
    </div>
    <label>用户名</label>
    <input id="username" placeholder="${passwordRequired ? 'admin' : 'alice'}" maxlength="64" autofocus>
    ${passwordRequired ? `
      <label>密码</label>
      <input id="password" type="password" maxlength="256" placeholder="••••••••">
    ` : `
      <label>显示名（可选）</label>
      <input id="display" placeholder="Alice" maxlength="128">
    `}
    <button class="primary" id="local-btn">登录</button>
    <div id="local-err"></div>
  `;
  const btn = document.getElementById('local-btn');
  const errBox = document.getElementById('local-err');
  async function doLogin() {
    const u = document.getElementById('username').value.trim();
    const p = passwordRequired
      ? document.getElementById('password').value
      : null;
    const d = passwordRequired
      ? null
      : document.getElementById('display').value.trim();
    if (!/^[A-Za-z0-9._@-]{1,64}$/.test(u)) {
      errBox.innerHTML = `<div class="err">用户名只能含字母/数字/._@-</div>`;
      return;
    }
    if (passwordRequired && !p) {
      errBox.innerHTML = `<div class="err">请输入密码</div>`;
      return;
    }
    btn.disabled = true;
    errBox.innerHTML = '';
    try {
      const payload = { username: u };
      if (p) payload.password = p;
      if (d) payload.display_name = d;
      const r = await api('POST', '/api/auth/local/login', payload);
      if (!r?.access_token) throw new Error('no access_token');
      LS.set('octopus.jwt', r.access_token);
      LS.set('octopus.actor_id', r.actor_id);
      LS.set('octopus.provider', 'local');
      LS.set('octopus.display', r.user?.display_name || r.user?.username || u);
      render();
    } catch (e) {
      errBox.innerHTML = `<div class="err">${explainErr(e)}</div>`;
      btn.disabled = false;
    }
  }
  btn.onclick = doLogin;
  document.getElementById('username').onkeydown = (e) => { if (e.key === 'Enter') doLogin(); };
  if (passwordRequired) {
    document.getElementById('password').onkeydown = (e) => { if (e.key === 'Enter') doLogin(); };
  } else {
    document.getElementById('display').onkeydown = (e) => { if (e.key === 'Enter') doLogin(); };
  }
}

function explainErr(e) {
  if (e.status === 503) return '服务未开启 · 请联系管理员';
  if (e.status === 502) return '上游不可达 · 请稍后重试';
  if (e.status === 401) return '验证码错误或已过期';
  if (e.status === 403) return '无权限 / 不在白名单';
  if (e.status === 400) return '请求参数错误：' + (e.body || '').slice(0, 100);
  return e.message || String(e);
}

// ═══════════════════════════════════════════════════════════
// Chat page
// ═══════════════════════════════════════════════════════════

// Section logic.
const BUILTIN_MODELS = [
  { id: 'molili',        label: '🎯 自动路由',   provider: 'official' },
  { id: 'kimi-k2.5',     label: 'Kimi K2.5',     provider: 'official' },
  { id: 'glm-4.7',       label: 'GLM-4.7',       provider: 'official' },
  { id: 'deepseek-v3.2', label: 'DeepSeek-V3.2', provider: 'official' },
  { id: 'minimax-m2.5',  label: 'MiniMax M2.5',  provider: 'official' },
  { id: 'qwen3-max',     label: 'Qwen3-Max',     provider: 'official' },
];

// Section logic.
function loadCustomModels() {
  try { return JSON.parse(LS.get('octopus.customModels') || '[]'); }
  catch { return []; }
}
function saveCustomModels(arr) {
  LS.set('octopus.customModels', JSON.stringify(arr));
}
function allModels() {
  return [...BUILTIN_MODELS, ...loadCustomModels()];
}
function modelById(id) {
  return allModels().find(m => m.id === id);
}
// Section logic.
function renderBuiltinOptions(selectedId) {
  return BUILTIN_MODELS.map(m =>
    `<option value="${escapeHtml(m.id)}" ${m.id===selectedId?'selected':''}>${escapeHtml(m.label)}</option>`
  ).join('');
}
// Section logic.
function renderCustomOptions(selectedId) {
  const custom = loadCustomModels();
  if (custom.length === 0) {
    return `<option disabled selected>（无 · 点 ⚙️ 添加）</option>`;
  }
  return custom.map(m =>
    `<option value="${escapeHtml(m.id)}" ${m.id===selectedId?'selected':''}>${escapeHtml(m.label || m.id)}${m.base_url ? ' · 🌐' : ''}</option>`
  ).join('');
}
// Section logic.
function effectiveModelId() {
  if (modelSource === 'custom') {
    const customModelId = LS.get('octopus.customModel');
    const custom = loadCustomModels();
    if (customModelId && custom.find(m => m.id === customModelId)) return customModelId;
    if (custom.length > 0) return custom[0].id;
    return null;   // 没有自定义 · 兜底到内置
  }
  return LS.get('octopus.builtinModel') || currentModel;
}

// Section logic.
let currentModel = LS.get('octopus.model') || 'molili';
// Section logic.
const LEGACY_AGENT_IDS = new Set(['desktop_operator']);
let _storedAgent = LS.get('octopus.agent') || 'general';
if (LEGACY_AGENT_IDS.has(_storedAgent)) {
  console.info('[octopus] 清理弃用 agent:', _storedAgent);
  LS.del('octopus.agent');
  _storedAgent = 'general';
}
let currentAgent = _storedAgent;
let modelSource = LS.get('octopus.modelSource') || 'builtin';
let availableAgents = [];
let sending = false;
let credits = null;

// Section logic.
function loadAllConvs() {
  try { return JSON.parse(LS.get('octopus.convs') || '{}'); }
  catch { return {}; }
}
function saveAllConvs(all) {
  LS.set('octopus.convs', JSON.stringify(all));
}
function convIdFor(agentId) { return 'a:' + agentId; }
function getConv(agentId) {
  const all = loadAllConvs();
  const id = convIdFor(agentId);
  return all[id] || { messages: [], agent: agentId, createdAt: 0, lastAt: 0 };
}
function saveConv(agentId, conv) {
  const all = loadAllConvs();
  all[convIdFor(agentId)] = conv;
  saveAllConvs(all);
}
function clearConv(agentId) {
  const all = loadAllConvs();
  delete all[convIdFor(agentId)];
  saveAllConvs(all);
}

// Section logic.
function currentMessages() {
  return getConv(currentAgent).messages;
}
function setCurrentMessages(msgs) {
  const conv = getConv(currentAgent);
  conv.messages = msgs;
  conv.lastAt = Date.now();
  if (!conv.createdAt) conv.createdAt = Date.now();
  saveConv(currentAgent, conv);
}

// Section logic.
let chatMode = LS.get('octopus.chatMode') || 'agent';

async function renderChat() {
  const provider = LS.get('octopus.provider');
  const display = LS.get('octopus.display') || LS.get('octopus.actor_id');
  const isMolili = provider === 'molili';

  function getChatEndpoint() {
    if (chatMode === 'direct' && isMolili) {
      return '/api/molili/openai/v1/chat/completions';
    }
    return '/v1/chat/completions';
  }

  document.body.classList.add('chatting');

  // Section logic.
  if (!isMolili) {
    renderNoBackend(display);
    return;
  }
  // Section logic.
  try {
    const linkResp = await fetch('/api/account/molili', { headers: authHeaders() });
    if (linkResp.status === 404) {
      renderNoBackend(display);
      return;
    }
    if (!linkResp.ok && linkResp.status === 401) {
      // Section logic.
      ['octopus.jwt','octopus.actor_id','octopus.provider','octopus.display']
        .forEach(k => LS.del(k));
      render();
      return;
    }
  } catch (e) { /* 网络错 · 继续让用户试 · 后续请求会再报 */ }
  const root = document.getElementById('root');
  const initials = (display || '?').slice(0, 2).toUpperCase();

  root.innerHTML = `
    <div class="chat-root">
      <div class="chat-header">
        <div class="who">
          <span style="font-size:22px">🐙</span>
          <div style="min-width:0">
            <h2>Octopus Chat</h2>
            <div class="info">
              <span class="badge ${isMolili?'accent':'plain'}">${isMolili?'📱 手机号':'💻 本地'}</span>
              <span style="color:var(--slate)">${escapeHtml(display || '')}</span>
              <span id="credits-badge"></span>
            </div>
          </div>
        </div>
        <div class="header-actions">
          ${isMolili ? `<button class="icon-btn" id="new-conv-btn" title="新建对话（清当前 agent 的聊天记录）">🗘</button>` : ''}
          ${isMolili ? `<button class="icon-btn" id="refresh-btn" title="刷新余额">🔄</button>` : ''}
          <button class="icon-btn" id="logout-btn" title="退出登录">⏻</button>
        </div>
      </div>

      ${isMolili ? `
      <div class="chat-toolbar">
        <div class="mode-pill" id="mode-pill">
          <button data-mode="agent" class="${chatMode==='agent'?'active':''}" title="经 planner + skills · 可调工具">🤖 Agent</button>
          <button data-mode="direct" class="${chatMode==='direct'?'active':''}" title="直接打 LLM · 不过 planner">⚡ 直聊</button>
        </div>
        <span id="agent-group" style="display:${chatMode==='agent'?'inline-flex':'none'};gap:6px;align-items:center">
          <label>Agent</label>
          <select id="agent-sel"><option>loading…</option></select>
        </span>
        <label style="margin-left:12px">模型</label>
        <div class="md-picker" id="md-picker">
          <button class="md-trigger" id="md-trigger">
            <span id="md-trigger-label">…</span>
            <span class="arrow">▾</span>
          </button>
        </div>
        <span class="credits" id="credits-inline"></span>
      </div>
      ` : ''}

      <div class="messages" id="messages">
        <div class="messages-inner" id="messages-inner"></div>
      </div>

      <div class="composer-wrap">
        <div class="composer">
          <textarea
            id="input"
            rows="1"
            ${isMolili ? '' : 'disabled'}
            placeholder="${isMolili ? '给 ' + (modelById(currentModel)?.label || currentModel) + ' 发消息…' : '本地模式不接 LLM · 请切手机号登录'}"
          ></textarea>
          <button class="send-btn" id="send-btn" ${isMolili ? '' : 'disabled'} title="发送 (Enter)">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12l7-7 7 7"/><path d="M12 19V5"/></svg>
          </button>
        </div>
        <div class="composer-hint">
          ${isMolili
            ? '<span class="hint-kbd">Enter</span> 发送 · <span class="hint-kbd">Shift+Enter</span> 换行 · 每次对话扣 Molili 积分'
            : '本地账号无 LLM 对话能力 · 点右上角 ⏻ 退出后选"手机号登录"'}
        </div>
      </div>
    </div>
  `;

  // Section logic.
  paintMessages();

  document.getElementById('logout-btn').onclick = () => {
    ['octopus.jwt','octopus.actor_id','octopus.provider','octopus.display','octopus.model']
      .forEach(k => LS.del(k));
    document.body.classList.remove('chatting');
    messages = [];
    render();
  };
  const refreshBtn = document.getElementById('refresh-btn');
  if (refreshBtn) refreshBtn.onclick = loadCredits;
  const newConvBtn = document.getElementById('new-conv-btn');
  if (newConvBtn) newConvBtn.onclick = () => {
    if (currentMessages().length === 0) return;
    if (confirm('清空当前 agent (' + currentAgent + ') 的对话记录？')) {
      clearConv(currentAgent);
      paintMessages();
    }
  };
  // Section logic.
  function triggerLabel() {
    const m = modelById(currentModel);
    if (!m) return '选模型…';
    return m.label;
  }
  function renderTriggerLabel() {
    document.getElementById('md-trigger-label').textContent = triggerLabel();
  }
  function closePopup() {
    const p = document.querySelector('.md-popup');
    if (p) p.remove();
  }
  function openPopup() {
    closePopup();
    const picker = document.getElementById('md-picker');
    const popup = document.createElement('div');
    popup.className = 'md-popup';
    popup.innerHTML = `
      <div class="md-tabs">
        <button data-tab="builtin" class="${modelSource==='builtin'?'active':''}">官方</button>
        <button data-tab="custom"  class="${modelSource==='custom'?'active':''}">自定义</button>
      </div>
      <div class="md-list" id="md-list"></div>
      <div class="md-foot">
        <button id="md-manage">⚙️ 管理自定义模型</button>
      </div>
    `;
    picker.appendChild(popup);

    const paintList = () => {
      const list = popup.querySelector('#md-list');
      if (modelSource === 'builtin') {
        list.innerHTML = BUILTIN_MODELS.map(m => `
          <div class="md-item ${m.id===currentModel?'active':''}" data-id="${escapeHtml(m.id)}">
            <span>${escapeHtml(m.label)}</span>
            <span class="m-id">${escapeHtml(m.id)}</span>
          </div>
        `).join('');
      } else {
        const custom = loadCustomModels();
        if (custom.length === 0) {
          list.innerHTML = `<div class="md-empty">
            还没添加自定义模型<br>
            <span style="font-size:11px">点下方"⚙️ 管理"添加</span>
          </div>`;
        } else {
          list.innerHTML = custom.map(m => `
            <div class="md-item ${m.id===currentModel?'active':''}" data-id="${escapeHtml(m.id)}">
              <span>${escapeHtml(m.label || m.id)}</span>
              ${m.base_url ? '<span class="m-badge" title="'+escapeHtml(m.base_url)+'">外部</span>' : ''}
              <span class="m-id">${escapeHtml(m.id)}</span>
            </div>
          `).join('');
        }
      }
      list.querySelectorAll('.md-item').forEach(it => {
        it.onclick = () => {
          currentModel = it.dataset.id;
          LS.set('octopus.model', currentModel);
          renderTriggerLabel();
          updateComposerPlaceholder();
          closePopup();
        };
      });
    };
    paintList();

    popup.querySelectorAll('.md-tabs button').forEach(btn => {
      btn.onclick = () => {
        modelSource = btn.dataset.tab;
        LS.set('octopus.modelSource', modelSource);
        popup.querySelectorAll('.md-tabs button').forEach(b =>
          b.classList.toggle('active', b.dataset.tab === modelSource));
        paintList();
      };
    });
    popup.querySelector('#md-manage').onclick = () => {
      closePopup();
      openModelsModal();
    };

    // Section logic.
    setTimeout(() => {
      const off = (e) => {
        if (!popup.contains(e.target) &&
            !document.getElementById('md-trigger').contains(e.target)) {
          closePopup();
          document.removeEventListener('click', off);
        }
      };
      document.addEventListener('click', off);
    }, 0);
  }

  document.getElementById('md-trigger').onclick = (e) => {
    e.stopPropagation();
    if (document.querySelector('.md-popup')) closePopup();
    else openPopup();
  };

  function updateComposerPlaceholder() {
    const ta = document.getElementById('input');
    if (!ta) return;
    const m = modelById(currentModel);
    if (!m) { ta.placeholder = '先选一个模型'; return; }
    if (m.id === 'molili') ta.placeholder = '🎯 自动路由 · 系统挑最合适的模型';
    else if (m.base_url) ta.placeholder = `🌐 直连 ${m.label} @ ${new URL(m.base_url).host}`;
    else ta.placeholder = '给 ' + m.label + ' 发消息…';
  }
  renderTriggerLabel();
  updateComposerPlaceholder();
  // Section logic.
  const modePill = document.getElementById('mode-pill');
  if (modePill) {
    modePill.querySelectorAll('button').forEach(btn => {
      btn.onclick = () => {
        chatMode = btn.dataset.mode;
        LS.set('octopus.chatMode', chatMode);
        modePill.querySelectorAll('button').forEach(b =>
          b.classList.toggle('active', b.dataset.mode === chatMode));
        // Section logic.
        const group = document.getElementById('agent-group');
        if (group) group.style.display = chatMode === 'agent' ? 'inline-flex' : 'none';
        if (messages.length === 0) paintMessages();
      };
    });
  }

  // Section logic.
  if (isMolili) loadAgents();

  async function loadAgents() {
    const sel = document.getElementById('agent-sel');
    if (!sel) return;
    try {
      const r = await fetch('/api/agents', { headers: authHeaders() });
      if (!r.ok) throw new Error('HTTP ' + r.status);
      const data = await r.json();
      // Section logic.
      availableAgents = Array.isArray(data) ? data : (data.agents || []);
      if (availableAgents.length === 0) {
        sel.innerHTML = '<option>(未注册 agent)</option>';
        sel.disabled = true;
        return;
      }
      // Section logic.
      const idOf = (a) => a.agent_id || a.name;
      sel.disabled = false;
      sel.innerHTML = availableAgents.map(a => {
        const id = idOf(a);
        return `<option value="${escapeHtml(id)}" ${id === currentAgent ? 'selected' : ''} title="${escapeHtml((a.description||'').slice(0,120))}">${a.icon || '🤖'} ${escapeHtml(a.display_name || id)}</option>`;
      }).join('');
      // Section logic.
      if (!availableAgents.some(a => idOf(a) === currentAgent)) {
        currentAgent = idOf(availableAgents[0]);
        LS.set('octopus.agent', currentAgent);
        sel.value = currentAgent;
      }
      sel.onchange = (e) => {
        currentAgent = e.target.value;
        LS.set('octopus.agent', currentAgent);
        const a = availableAgents.find(x => idOf(x) === currentAgent);
        const ta = document.getElementById('input');
        if (ta && a) ta.placeholder = `和 ${a.icon||'🤖'} ${a.display_name||currentAgent} 聊…`;
        // Section logic.
        paintMessages();
      };
    } catch (e) {
      sel.innerHTML = '<option>(加载失败)</option>';
      sel.disabled = true;
    }
  }

  const ta = document.getElementById('input');
  const sendBtn = document.getElementById('send-btn');
  ta.oninput = () => {
    ta.style.height = 'auto';
    ta.style.height = Math.min(140, ta.scrollHeight) + 'px';
  };
  ta.onkeydown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  };
  sendBtn.onclick = send;

  if (isMolili) loadCredits();

  async function loadCredits() {
    try {
      const r = await api('POST', '/api/account/molili/refresh');
      credits = r?.credits?.surplusCredits;
      if (typeof credits === 'number') {
        const text = `💎 ${credits.toLocaleString()}`;
        const el = document.getElementById('credits-inline');
        const el2 = document.getElementById('credits-badge');
        if (el) el.textContent = text;
        if (el2) {
          el2.className = 'badge ok';
          el2.textContent = text;
        }
      }
    } catch (e) { /* ignore */ }
  }

  async function send() {
    if (sending) return;
    const content = ta.value.trim();
    if (!content) return;
    sending = true;
    ta.value = '';
    ta.style.height = 'auto';
    sendBtn.disabled = true;

    // Section logic.
    const msgs = currentMessages();
    msgs.push({ role: 'user', content });
    setCurrentMessages(msgs);
    paintMessages();

    const agentMeta = availableAgents.find(a => (a.agent_id || a.name) === currentAgent);
    const agentIcon = agentMeta?.icon || '🤖';
    const agentLabel = agentMeta?.display_name || currentAgent;

    // Section logic.
    const inner = document.getElementById('messages-inner');
    const thinking = document.createElement('div');
    thinking.className = 'msg-row assistant';
    thinking.innerHTML = `
      <div class="msg-avatar">${agentIcon}</div>
      <div class="msg-body">
        <div class="msg-meta"><span class="role">${escapeHtml(agentLabel)}</span>
          <span class="model">${escapeHtml(currentModel)}</span></div>
        <div class="thinking">
          <span class="thinking-dot"></span>
          <span class="thinking-dot"></span>
          <span class="thinking-dot"></span>
          <span style="margin-left:4px">思考中</span>
        </div>
      </div>
    `;
    inner.appendChild(thinking);
    scrollToBottom();

    try {
      const sel = modelById(currentModel);
      if (!sel) throw new Error('请先选一个模型');

      // Section logic.
      const apiMessages = msgs.map(m => ({ role: m.role, content: m.content }));

      let r;
      if (sel.base_url && sel.api_key) {
        r = await sendToExternalEndpoint(sel, apiMessages);
      } else {
        const payload = { model: sel.id, messages: apiMessages, stream: false };
        if (chatMode === 'agent' && isMolili) payload.agent = currentAgent;
        r = await api('POST', getChatEndpoint(), payload);
      }
      const reply = r?.choices?.[0]?.message;
      const usage = r?.usage;
      if (reply) {
        msgs.push({
          role: 'assistant', content: reply.content || '',
          _usage: usage,
          _model: currentModel,
          _agent: currentAgent,
          _agentIcon: agentIcon,
          _agentLabel: agentLabel,
        });
        setCurrentMessages(msgs);
      }
      thinking.remove();
      paintMessages();
      if (isMolili) loadCredits();
    } catch (e) {
      msgs.push({
        role: 'assistant',
        content: '调用失败：' + (e.message || e),
        _error: true,
        _model: currentModel,
        _agent: currentAgent,
        _agentIcon: agentIcon,
        _agentLabel: agentLabel,
      });
      setCurrentMessages(msgs);
      thinking.remove();
      paintMessages();
    } finally {
      sending = false;
      sendBtn.disabled = false;
      ta.focus();
    }
  }

  function scrollToBottom() {
    const box = document.getElementById('messages');
    box.scrollTop = box.scrollHeight;
  }

  function paintMessages() {
    const inner = document.getElementById('messages-inner');
    const messages = currentMessages();
    if (messages.length === 0) {
      const modeTxt = chatMode === 'agent'
      ? '🤖 Agent 模式 · 经过 planner → skills → LLM · 可自动调工具'
      : '⚡ 直聊模式 · 直接发给 LLM · 无 agent 参与';
    const m = modelById(currentModel);
    let routeTxt;
    if (!m) routeTxt = '⚠️ 未选模型';
    else if (m.id === 'molili') routeTxt = '🎯 自动路由 · 系统挑最合适的模型';
    else if (m.base_url) routeTxt = `🌐 外部直连 · ${m.label} @ ${new URL(m.base_url).host}`;
    else routeTxt = '📌 固定 · ' + m.label;
    inner.innerHTML = `
        <div class="empty">
          <div class="empty-icon">🐙</div>
          <div class="empty-title">和官方大模型聊聊</div>
          <div class="empty-sub">
            ${modeTxt}
            <br><br>
            ${routeTxt}
            <br><br>
            <span class="hint-kbd">Enter</span> 发送 · <span class="hint-kbd">Shift+Enter</span> 换行 · 积分实时扣
          </div>
        </div>
      `;
      return;
    }
    inner.innerHTML = messages.map(m => {
      if (m.role === 'user') {
        return `<div class="msg-row user">
          <div class="msg-avatar">${escapeHtml(initials)}</div>
          <div class="msg-body">
            <div class="msg-meta"><span class="role">你</span></div>
            <div class="msg-content">${escapeHtml(m.content)}</div>
          </div>
        </div>`;
      }
      // Section logic.
      const icon = m._error ? '⚠️' : (m._agentIcon || '🤖');
      const label = m._error ? '错误' : (m._agentLabel || 'Assistant');
      const modelTag = m._model || currentModel;
      const u = m._usage ? `<div class="msg-usage">
        ↑ ${m._usage.prompt_tokens||0} · ↓ ${m._usage.completion_tokens||0}${
          m._usage.total_tokens ? ' · total ' + m._usage.total_tokens : ''
        }</div>` : '';
      return `<div class="msg-row assistant ${m._error?'error':''}">
        <div class="msg-avatar">${icon}</div>
        <div class="msg-body">
          <div class="msg-meta">
            <span class="role">${escapeHtml(label)}</span>
            <span class="model">${escapeHtml(modelTag)}</span>
          </div>
          <div class="msg-content">${escapeHtml(m.content)}</div>
          ${u}
        </div>
      </div>`;
    }).join('');
    scrollToBottom();
  }
}

function escapeHtml(s) {
  return (s || '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

// ═══════════════════════════════════════════════════════════
// Section logic.
// ═══════════════════════════════════════════════════════════

function openModelsModal() {
  const existing = document.querySelector('.modal-backdrop');
  if (existing) existing.remove();

  function paint() {
    const custom = loadCustomModels();
    const backdrop = document.createElement('div');
    backdrop.className = 'modal-backdrop';
    backdrop.innerHTML = `
      <div class="modal">
        <div class="modal-head">
          <h3>⚙️ 模型管理</h3>
          <button class="icon-btn" id="modal-close">✕</button>
        </div>
        <div class="modal-body">
          <div style="font-size:12px;color:var(--mute);margin-bottom:10px">
            官方模型走内置代理 · 自定义模型可选走代理或自己的 base_url+api_key 直连
          </div>

          <div class="model-list">
            ${BUILTIN_MODELS.map(m => `
              <div class="model-item builtin">
                <span class="tag b">内置</span>
                <span class="mlabel">${escapeHtml(m.label)}</span>
                <span class="mid">${escapeHtml(m.id)}</span>
              </div>
            `).join('')}
            ${custom.map((m, i) => `
              <div class="model-item">
                <span class="tag c">自定义</span>
                <span class="mlabel">${escapeHtml(m.label || m.id)}</span>
                <span class="mid">${escapeHtml(m.id)}</span>
                ${m.base_url ? `<span class="tag ext" title="${escapeHtml(m.base_url)}">外部</span>` : ''}
                <button data-del="${i}" title="删除">🗑</button>
              </div>
            `).join('')}
          </div>

          <h4 style="margin:20px 0 8px 0;color:white;font-size:13px">➕ 添加模型</h4>
          <div class="add-form">
            <div class="row">
              <div>
                <label>模型 ID *</label>
                <input id="add-id" placeholder="gpt-4o-mini / claude-haiku-4-5 / ...">
              </div>
              <div>
                <label>显示名（可选）</label>
                <input id="add-label" placeholder="GPT-4o Mini">
              </div>
            </div>
            <details style="margin-top:8px">
              <summary style="cursor:pointer;color:var(--cephalo-light);font-size:12px">
                外部端点（绕过 Molili · 用自己的 API key）
              </summary>
              <div style="margin-top:8px">
                <label>Base URL（OpenAI-compat · 含 /v1）</label>
                <input id="add-base" placeholder="https://api.openai.com/v1 · 留空走 Molili">
                <div class="form-hint">例：OpenAI · https://api.openai.com/v1 · DeepSeek · https://api.deepseek.com/v1</div>
                <label>API Key</label>
                <input id="add-key" type="password" placeholder="sk-...">
                <div class="form-hint">
                  ⚠️ 存 localStorage · 仅本浏览器 · 不上传服务器<br>
                  用这个直连后不扣 Molili 积分 · 按你自己的 provider 计费
                </div>
              </div>
            </details>
            <button class="primary" id="add-btn" style="margin-top:12px;width:100%;padding:9px;border:none;border-radius:6px;background:var(--cephalo);color:white;cursor:pointer">添加</button>
          </div>
        </div>
        <div class="modal-foot">
          <button class="secondary" id="modal-done" style="padding:7px 16px;border:1px solid var(--ink-600);background:var(--ink-700);color:var(--slate);border-radius:6px;cursor:pointer">完成</button>
        </div>
      </div>
    `;
    document.body.appendChild(backdrop);

    // Section logic.
    const close = () => {
      backdrop.remove();
      // Section logic.
      const sel = document.getElementById('model-sel');
      if (sel) sel.innerHTML = renderModelOptions(currentModel);
    };
    backdrop.onclick = (e) => { if (e.target === backdrop) close(); };
    backdrop.querySelector('#modal-close').onclick = close;
    backdrop.querySelector('#modal-done').onclick = close;

    // Section logic.
    backdrop.querySelectorAll('[data-del]').forEach(btn => {
      btn.onclick = () => {
        const i = parseInt(btn.dataset.del);
        const arr = loadCustomModels();
        arr.splice(i, 1);
        saveCustomModels(arr);
        // Section logic.
        if (!modelById(currentModel)) {
          currentModel = BUILTIN_MODELS[0].id;
          LS.set('octopus.model', currentModel);
        }
        backdrop.remove();
        paint();
      };
    });

    // Section logic.
    backdrop.querySelector('#add-btn').onclick = () => {
      const id = backdrop.querySelector('#add-id').value.trim();
      const label = backdrop.querySelector('#add-label').value.trim();
      const baseUrl = backdrop.querySelector('#add-base').value.trim();
      const apiKey = backdrop.querySelector('#add-key').value.trim();
      if (!id) {
        alert('模型 ID 必填');
        return;
      }
      if (BUILTIN_MODELS.some(m => m.id === id)) {
        alert('ID 和内置模型冲突 · 换一个');
        return;
      }
      if (baseUrl && !/^https?:\/\//.test(baseUrl)) {
        alert('base_url 需以 http(s):// 开头');
        return;
      }
      const arr = loadCustomModels();
      // Section logic.
      const exist = arr.findIndex(m => m.id === id);
      const entry = { id, label: label || id, provider: baseUrl ? 'external' : 'molili' };
      if (baseUrl) entry.base_url = baseUrl;
      if (apiKey) entry.api_key = apiKey;
      if (exist >= 0) arr[exist] = entry; else arr.push(entry);
      saveCustomModels(arr);
      backdrop.remove();
      paint();
    };
  }
  paint();
}

// ═══════════════════════════════════════════════════════════
// Section logic.
// ═══════════════════════════════════════════════════════════

async function sendToExternalEndpoint(model, messages) {
  const payload = {
    model: model.id,
    messages,
    stream: false,
  };
  const r = await fetch(model.base_url.replace(/\/$/, '') + '/chat/completions', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': 'Bearer ' + model.api_key,
    },
    body: JSON.stringify(payload),
  });
  const text = await r.text();
  if (!r.ok) {
    throw new Error(`${model.base_url} HTTP ${r.status}: ${text.slice(0, 200)}`);
  }
  try { return JSON.parse(text); }
  catch { throw new Error(`${model.base_url} non-JSON: ${text.slice(0, 200)}`); }
}

// ═══════════════════════════════════════════════════════════
// Section logic.
// ═══════════════════════════════════════════════════════════

function renderNoBackend(display) {
  document.body.classList.add('chatting');
  const root = document.getElementById('root');
  root.innerHTML = `
    <div class="chat-root">
      <div class="chat-header">
        <div class="who">
          <span style="font-size:22px">🐙</span>
          <div style="min-width:0">
            <h2>Octopus Chat</h2>
            <div class="info">
              <span class="badge plain">💻 本地</span>
              <span style="color:var(--slate)">${escapeHtml(display || '')}</span>
            </div>
          </div>
        </div>
        <div class="header-actions">
          <button class="icon-btn" id="logout-btn" title="退出登录">⏻</button>
        </div>
      </div>
      <div style="flex:1;display:flex;align-items:center;justify-content:center;padding:40px 20px">
        <div style="max-width:420px;text-align:center">
          <div style="font-size:56px;margin-bottom:16px">🔌</div>
          <h2 style="color:white;margin:0 0 8px 0">当前账号没有 LLM 后端</h2>
          <p style="color:var(--mute);font-size:14px;line-height:1.6;margin:0 0 24px 0">
            你用的是 <b style="color:var(--slate)">本地账号</b> · 没绑任何大模型账号 · 无法聊天。
            <br><br>
            换"📱 手机号"登录即可 · 会自动绑到 Molili 官方大模型（Kimi / GLM / DeepSeek ...）
          </p>
          <button class="primary" style="padding:12px 28px;font-size:14px;border:none;border-radius:8px;background:var(--cephalo);color:white;cursor:pointer;font-weight:600" id="switch-btn">
            🔄 切换到手机号登录
          </button>
          <p style="color:var(--mute);font-size:11px;margin-top:16px">
            本地账号仍可访问 <code class="hint-kbd">/api/agents</code> · <code class="hint-kbd">/api/skills</code> 等元数据端点
          </p>
        </div>
      </div>
    </div>
  `;
  const switchOut = () => {
    ['octopus.jwt','octopus.actor_id','octopus.provider','octopus.display','octopus.model']
      .forEach(k => LS.del(k));
    document.body.classList.remove('chatting');
    render();
  };
  document.getElementById('switch-btn').onclick = switchOut;
  document.getElementById('logout-btn').onclick = switchOut;
}

render();
</script>
</body>
</html>
"""


def get_chat_html() -> str:
    return _CHAT_HTML
