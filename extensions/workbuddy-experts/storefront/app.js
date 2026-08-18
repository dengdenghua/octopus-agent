/* Octopus 专家商城 — WorkBuddy 全量镜像
 * 纯静态,无构建工具,直接双击 index.html 或任意静态服务器即可运行。
 */
(function () {
  "use strict";

  const DATA_URL = "data/expert-store.json";
  const state = { experts: [], categories: [], catId: "all", type: "all", q: "", sort: "updated" };

  const $ = (s) => document.querySelector(s);
  const el = (tag, cls, html) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (html != null) n.innerHTML = html;
    return n;
  };
  const zh = (o, fallback) => (o && o.zh) || (o && o.en) || fallback || "";
  const fmtDate = (iso) => {
    if (!iso) return "";
    const d = new Date(iso);
    if (isNaN(d)) return iso.slice(0, 10);
    return d.toISOString().slice(0, 10);
  };
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[c]));

  const catName = (id) => {
    const c = state.categories.find((x) => x.id === id);
    return c ? zh(c.name, id) : id;
  };

  async function load() {
    try {
      const res = await fetch(DATA_URL, { cache: "no-store" });
      if (!res.ok) throw new Error("HTTP " + res.status);
      const data = await res.json();
      state.experts = data.experts || [];
      state.categories = data.categories || [];
      const meta = data.meta || {};
      $("#footer-meta").textContent =
        "数据源: " + (meta.source || "") + " · 更新于 " + fmtDate(meta.lastUpdated) +
        " · 镜像: " + (meta.mirror || "");
      renderStats(meta);
      renderSidebar();
      render();
    } catch (e) {
      document.querySelector("#grid").innerHTML =
        '<div class="empty"><div class="empty-icon">⚠️</div><p>加载数据失败:' + esc(e.message) + "</p>" +
        '<p class="empty-sub">请通过本地静态服务器访问(index.html + app.js + data/expert-store.json)</p></div>';
    }
  }

  function renderStats(meta) {
    $("#stat-count").textContent = meta.count != null ? meta.count + " 专家" : state.experts.length + " 专家";
    $("#stat-agent").textContent = (meta.agentCount != null ? meta.agentCount : state.experts.filter((e) => e.expertType === "agent").length) + " 专家";
    $("#stat-team").textContent = (meta.teamCount != null ? meta.teamCount : state.experts.filter((e) => e.expertType === "team").length) + " 专家团";
    $("#h-count").textContent = meta.count || state.experts.length;
    $("#h-agent").textContent = meta.agentCount != null ? meta.agentCount : state.experts.filter((e) => e.expertType === "agent").length;
    $("#h-team").textContent = meta.teamCount != null ? meta.teamCount : state.experts.filter((e) => e.expertType === "team").length;
    $("#h-cat").textContent = state.categories.length;
  }

  function renderSidebar() {
    const ul = $("#cat-list");
    ul.innerHTML = "";
    const allBtn = el("li", "", '<button data-cat="all"><span>🏠 全部专家</span><span class="cat-count">' + state.experts.length + "</span></button>");
    ul.appendChild(allBtn);
    state.categories.forEach((c) => {
      const n = state.experts.filter((e) => e.categoryId === c.id).length;
      const li = el("li", "", '<button data-cat="' + esc(c.id) + '"><span>' + esc(zh(c.name, c.id)) + '</span><span class="cat-count">' + n + "</span></button>");
      ul.appendChild(li);
    });
    ul.addEventListener("click", (ev) => {
      const btn = ev.target.closest("button[data-cat]");
      if (!btn) return;
      state.catId = btn.dataset.cat;
      document.querySelectorAll("#cat-list button").forEach((b) => b.classList.toggle("active", b === btn));
      render();
    });
  }

  function filtered() {
    const q = state.q.trim().toLowerCase();
    return state.experts
      .filter((e) => (state.catId === "all" || e.categoryId === state.catId))
      .filter((e) => (state.type === "all" || e.expertType === state.type))
      .filter((e) => {
        if (!q) return true;
        const hay = [
          e.id, e.plugin, e.displayName && e.displayName.zh, e.displayName && e.displayName.en,
          e.profession && e.profession.zh, e.profession && e.profession.en,
          e.description && e.description.zh, e.description && e.description.en,
          (e.tags || []).map((t) => t.zh + " " + t.en).join(" "),
          catName(e.categoryId)
        ].join(" ").toLowerCase();
        return hay.includes(q);
      })
      .sort((a, b) => {
        if (state.sort === "name") return (a.displayName && a.displayName.en || a.id).localeCompare(b.displayName && b.displayName.en || b.id);
        if (state.sort === "name-zh") return (a.displayName && a.displayName.zh || a.id).localeCompare(b.displayName && b.displayName.zh || b.id, "zh");
        return (b.updatedAt || "").localeCompare(a.updatedAt || "");
      });
  }

  function cardHTML(e) {
    const name = zh(e.displayName, e.id);
    const prof = zh(e.profession, "");
    const isTeam = e.expertType === "team";
    const av = e.avatar
      ? '<img class="card-avatar" loading="lazy" src="' + esc(e.avatar) + '" alt="" onerror="this.outerHTML=\'<div class=&quot;card-avatar avatar-missing&quot;>🐙</div>\'">'
      : '<div class="card-avatar avatar-missing">🐙</div>';
    const tags = (e.tags || []).slice(0, 3).map((t) => '<span class="tag">' + esc(t.zh || t.en) + "</span>").join("");
    return (
      '<div class="card" data-id="' + esc(e.id) + '">' +
        '<div class="card-head">' + av +
          '<div><h3 class="card-name">' + esc(name) + "</h3>" +
          '<p class="card-prof">' + esc(prof) + "</p></div>" +
        "</div>" +
        '<div class="card-badges">' +
          '<span class="badge ' + (isTeam ? "team" : "agent") + '">' + (isTeam ? "专家团" : "专家") + "</span>" +
          '<span class="badge cat">' + esc(catName(e.categoryId)) + "</span>" +
        "</div>" +
        '<p class="card-desc">' + esc(e.description && e.description.zh || "") + "</p>" +
        (tags ? '<div class="card-tags">' + tags + "</div>" : "") +
        '<div class="card-foot">' +
          '<span class="card-updated">' + fmtDate(e.updatedAt) + "</span>" +
          '<button class="btn btn-primary btn-download" data-url="' + esc(e.bundleUrl) + '">下载</button>' +
        "</div>" +
      "</div>"
    );
  }

  function render() {
    const list = filtered();
    const grid = $("#grid");
    grid.innerHTML = list.map(cardHTML).join("");
    $("#empty").hidden = list.length !== 0;
    grid.querySelectorAll(".card").forEach((c) => {
      c.addEventListener("click", (ev) => {
        if (ev.target.closest(".btn-download")) return;
        const e = state.experts.find((x) => x.id === c.dataset.id);
        if (e) openModal(e);
      });
    });
    grid.querySelectorAll(".btn-download").forEach((b) => {
      b.addEventListener("click", (ev) => {
        ev.stopPropagation();
        const url = b.dataset.url;
        if (url) window.open(url, "_blank", "noopener");
      });
    });
  }

  /* ===== 详情弹窗 ===== */
  function openModal(e) {
    const isTeam = e.expertType === "team";
    const name = zh(e.displayName, e.id);
    const prof = zh(e.profession, "");
    const av = e.avatar
      ? '<img class="modal-avatar" src="' + esc(e.avatar) + '" alt="" onerror="this.outerHTML=\'<div class=&quot;modal-avatar&quot; style=&quot;display:flex;align-items:center;justify-content:center;font-size:32px&quot;&gt;🐙</div>\'">'
      : '<div class="modal-avatar" style="display:flex;align-items:center;justify-content:center;font-size:32px">🐙</div>';
    const tags = (e.tags || []).map((t) => '<span class="tag">' + esc(t.zh || t.en) + "</span>").join("");
    const prompts = (e.quickPrompts || []).map((p, i) =>
      "<li data-i='" + i + "' title='点击复制'>" + esc(p.zh || p.en) + "</li>").join("") || "<li>暂无快捷提示</li>";

    const installCmd =
      "# 方式一:八爪鱼命令导入(需在 octopus-agent 项目内)\n" +
      "python3 extensions/workbuddy-experts/scripts/pull-remote-catalog.py --install " + e.plugin + "\n\n" +
      "# 方式二:直接下载 bundle 解压后导入 agent pack\n" +
      "curl -L -o " + e.plugin + ".tar.gz " + e.bundleUrl;

    $("#modal-body").innerHTML =
      '<div class="modal-head">' + av +
        "<div><h2 class='modal-title'>" + esc(name) + "</h2>" +
        '<p class="modal-prof">' + esc(prof) + "</p>" +
        '<div class="card-badges">' +
          '<span class="badge ' + (isTeam ? "team" : "agent") + '">' + (isTeam ? "专家团" : "专家") + "</span>" +
          '<span class="badge cat">' + esc(catName(e.categoryId)) + "</span>" +
        "</div></div></div>" +
      '<p class="modal-desc">' + esc(e.description && e.description.zh || e.description && e.description.en || "") + "</p>" +
      '<div class="meta-grid">' +
        '<div class="meta-item"><b>标识 ID</b><span>' + esc(e.id) + "</span></div>" +
        '<div class="meta-item"><b>插件名</b><span>' + esc(e.plugin) + "</span></div>" +
        '<div class="meta-item"><b>类型</b><span>' + (isTeam ? "专家团(多角色协作)" : "领域专家(单角色)") + "</span></div>" +
        '<div class="meta-item"><b>最近更新</b><span>' + esc(fmtDate(e.updatedAt)) + "</span></div>" +
        (e.defaultInitPrompt && e.defaultInitPrompt.zh ? '<div class="meta-item" style="grid-column:1/-1"><b>默认开场提示</b><span>' + esc(e.defaultInitPrompt.zh) + "</span></div>" : "") +
      "</div>" +
      (tags ? '<div class="section-title">标签</div><div class="card-tags">' + tags + "</div>" : "") +
      '<div class="section-title">快捷提示(点击复制)</div><ul class="prompt-list">' + prompts + "</ul>" +
      '<div class="section-title">安装指引</div><pre class="cmd">' + esc(installCmd) + "</pre>" +
      '<div class="modal-actions">' +
        '<a class="btn btn-primary big" href="' + esc(e.bundleUrl) + '" target="_blank" rel="noopener">⬇ 下载 Bundle 包</a>' +
        '<button class="btn btn-ghost" id="modal-copy-cmd">复制安装命令</button>' +
      "</div>";

    $("#modal").hidden = false;
    document.body.style.overflow = "hidden";

    // 快捷提示复制
    $("#modal-body").querySelectorAll(".prompt-list li").forEach((li) => {
      li.addEventListener("click", async () => {
        const p = e.quickPrompts[+li.dataset.i];
        const txt = p.zh || p.en || "";
        try { await navigator.clipboard.writeText(txt); } catch (_) {
          const ta = document.createElement("textarea"); ta.value = txt; document.body.appendChild(ta); ta.select(); document.execCommand("copy"); ta.remove();
        }
        li.classList.add("copy-done"); li.textContent = "✅ 已复制:" + (p.zh || p.en);
        setTimeout(() => { li.classList.remove("copy-done"); li.innerHTML = esc(p.zh || p.en); }, 1200);
      });
    });
    $("#modal-copy-cmd").addEventListener("click", async () => {
      try { await navigator.clipboard.writeText(installCmd); } catch (_) {}
      const b = $("#modal-copy-cmd"); b.textContent = "✅ 已复制"; b.style.color = "#16a34a";
      setTimeout(() => { b.textContent = "复制安装命令"; b.style.color = ""; }, 1200);
    });
  }

  function closeModal() {
    $("#modal").hidden = true;
    document.body.style.overflow = "";
  }

  /* ===== 事件绑定 ===== */
  $("#modal-close").addEventListener("click", closeModal);
  $("#modal").addEventListener("click", (ev) => { if (ev.target === $("#modal")) closeModal(); });
  document.addEventListener("keydown", (ev) => { if (ev.key === "Escape") closeModal(); });
  $("#search").addEventListener("input", (ev) => { state.q = ev.target.value; render(); });
  $("#sort").addEventListener("change", (ev) => { state.sort = ev.target.value; render(); });
  document.querySelectorAll(".filter-group .chip").forEach((c) => {
    c.addEventListener("click", () => {
      state.type = c.dataset.type;
      document.querySelectorAll(".filter-group .chip").forEach((x) => x.classList.toggle("active", x === c));
      render();
    });
  });

  load();
})();
