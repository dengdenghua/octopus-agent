export const INSPECT_INJECTED_SCRIPT = `
(function() {
  if (window.__octopusInspectInstalled) return;
  window.__octopusInspectInstalled = true;

  let active = false;
  let lastHover = null;
  const OUTLINE_ID = '__octopus_inspect_outline__';

  function makeOutline() {
    const el = document.createElement('div');
    el.id = OUTLINE_ID;
    el.style.cssText = [
      'position:fixed',
      'pointer-events:none',
      'border:2px solid #8b5cf6',
      'background:rgba(139,92,246,0.12)',
      'z-index:2147483647',
      'display:none',
      'transition:all 50ms ease-out',
      'border-radius:2px',
      'box-sizing:border-box'
    ].join(';');
    return el;
  }

  let outline = null;
  function ensureOutline() {
    if (outline && outline.isConnected) return outline;
    if (!document.body) return null;
    outline = makeOutline();
    document.body.appendChild(outline);
    return outline;
  }

  function buildSelector(el) {
    if (!el || !el.tagName) return '';
    if (el === document.body) return 'body';
    if (el.id && /^[A-Za-z][\\w-]*$/.test(el.id)) return '#' + el.id;
    const path = [];
    let cur = el;
    let depth = 0;
    while (cur && cur.nodeType === 1 && cur !== document.body && depth < 5) {
      let part = cur.tagName.toLowerCase();
      const cls = cur.classList ? Array.from(cur.classList).filter(function(c){
        return /^[A-Za-z_-][\\w-]*$/.test(c);
      }).slice(0, 2) : [];
      if (cls.length) {
        part += '.' + cls.join('.');
      } else if (cur.parentElement) {
        const sibs = Array.from(cur.parentElement.children).filter(function(c){
          return c.tagName === cur.tagName;
        });
        if (sibs.length > 1) {
          part += ':nth-of-type(' + (sibs.indexOf(cur) + 1) + ')';
        }
      }
      path.unshift(part);
      cur = cur.parentElement;
      depth++;
    }
    return path.join(' > ');
  }

  function trim(s, n) {
    if (typeof s !== 'string') return '';
    return s.length > n ? s.slice(0, n) + '\\u2026' : s;
  }

  function showOutline(el) {
    const node = ensureOutline();
    if (!node || !el) return;
    const r = el.getBoundingClientRect();
    node.style.display = 'block';
    node.style.left = r.left + 'px';
    node.style.top = r.top + 'px';
    node.style.width = r.width + 'px';
    node.style.height = r.height + 'px';
  }

  function hideOutline() {
    if (outline) outline.style.display = 'none';
  }

  function onMove(e) {
    if (!active) return;
    const el = document.elementFromPoint(e.clientX, e.clientY);
    if (!el || el.id === OUTLINE_ID) return;
    if (el === lastHover) return;
    lastHover = el;
    showOutline(el);
  }

  function onClick(e) {
    if (!active) return;
    e.preventDefault();
    e.stopPropagation();
    const el = document.elementFromPoint(e.clientX, e.clientY);
    if (!el || el.id === OUTLINE_ID) return;
    const r = el.getBoundingClientRect();
    const payload = {
      selector: buildSelector(el),
      tagName: el.tagName ? el.tagName.toLowerCase() : '',
      outerHTML: trim(el.outerHTML || '', 600),
      textContent: trim((el.textContent || '').trim().replace(/\\s+/g, ' '), 200),
      rect: {
        x: Math.round(r.left),
        y: Math.round(r.top),
        w: Math.round(r.width),
        h: Math.round(r.height)
      }
    };
    try {
      window.parent.postMessage({ type: 'octopus:inspect:select', payload: payload }, '*');
    } catch (err) { swallow(err); }
    setActive(false);
  }

  function onKey(e) {
    if (active && e.key === 'Escape') {
      e.preventDefault();
      setActive(false);
    }
  }

  function setActive(v) {
    active = !!v;
    if (active) {
      ensureOutline();
      document.documentElement.style.cursor = 'crosshair';
      document.addEventListener('mousemove', onMove, true);
      document.addEventListener('click', onClick, true);
      document.addEventListener('keydown', onKey, true);
    } else {
      document.documentElement.style.cursor = '';
      document.removeEventListener('mousemove', onMove, true);
      document.removeEventListener('click', onClick, true);
      document.removeEventListener('keydown', onKey, true);
      hideOutline();
      lastHover = null;
    }
    try {
      window.parent.postMessage({ type: 'octopus:inspect:state', active: active }, '*');
    } catch (err) { swallow(err); }
  }

  window.addEventListener('message', function(e) {
    const data = e && e.data;
    if (!data || typeof data !== 'object') return;
    if (data.type === 'octopus:inspect:enable') setActive(true);
    else if (data.type === 'octopus:inspect:disable') setActive(false);
  });

  function announce() {
    try {
      window.parent.postMessage({ type: 'octopus:inspect:ready' }, '*');
    } catch (err) { swallow(err); }
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', announce);
  } else {
    announce();
  }
})();
`;
