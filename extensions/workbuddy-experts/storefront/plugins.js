/* Octopus 插件 / 连接器商城 — 纯静态
 * 数据: data/plugin-store.json(我们的 Codex 插件 + WorkBuddy 连接器)
 */
(function () {
  "use strict";

  const DATA_URL = "data/plugin-store.json";
  const state = { items: [], kind: "all", type: "all", q: "" };

  const $ = (s) => document.querySelector(s);
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[c]));

  async function load() {
    try {
      const res = await fetch(DATA_URL, { cache: "no-store" });
      if (!res.ok) throw new Error("HTTP " + res.status);
      const data = await res.json();
      state.items = data.items || [];
      const meta = data.meta || {};
      $("#stat-plugin").textContent = (meta.codex_plugins ?? 0) + " 插件";
      $("#stat-connector").textContent = (meta.workbuddy_connectors ?? 0) + " 连接器";
      $("#h-total").textContent = meta.count || state.items.length;
      $("#h-plugin").textContent = meta.codex_plugins ?? 0;
      $("#h-connector").textContent = meta.workbuddy_connectors ?? 0;
      $("#footer-meta").textContent = "数据源: " + (meta.sources || []).join(" · ");
      render();
    } catch (e) {
      document.querySelector("#grid").innerHTML =
        '<div class="empty"><div class="empty-icon">⚠️</div><p>加载数据失败:' + esc(e.message) + "</p></div>";
    }
  }

  function filtered() {
    const q = state.q.trim().toLowerCase();
    return state.items
      .filter((it) => state.kind === "all" || it.kind === state.kind)
      .filter((it) => {
        if (state.type === "all") return true;
        return (it.type || it.kind || "plugin") === state.type;
      })
      .filter((it) => {
        if (!q) return true;
        const hay = [
          it.id, it.name, it.name_zh, it.description, it.source,
          it.type, it.auth_mode, it.category, it.plugin,
          (it.mcp_servers || []).join(" "),
        ].join(" ").toLowerCase();
        return hay.includes(q);
      });
  }

  function cardHTML(it) {
    const isConnector = it.kind === "connector";
    const typeLabel = {
      mcp: "🔌 MCP", cli: "⌨️ CLI", "skill-only": "🧩 技能"
    }[it.type] || (isConnector ? "🔌" : "🧩 插件");
    const auth = it.auth_mode ? '<span class="tag">auth: ' + esc(it.auth_mode) + "</span>" : "";
    const skillInfo = isConnector
      ? '<span class="tag">技能 ' + (it.skills_count || 0) + "</span>"
      : '<span class="tag">技能 ' + (it.skills || []).length + "</span>";
    const mcp = (it.mcp_servers || []).slice(0, 2).map((m) =>
      '<span class="tag">' + esc(m) + "</span>").join("");
    return (
      '<div class="card" data-id="' + esc(it.id) + '">' +
        '<div class="card-head">' +
          '<div class="card-avatar avatar-missing">' + (isConnector ? "🔌" : "🧩") + "</div>" +
          '<div><h3 class="card-name">' + esc(it.name_zh || it.name) + "</h3>" +
          '<p class="card-prof">' + esc(it.name || "") + "</p></div>" +
        "</div>" +
        '<div class="card-badges">' +
          '<span class="badge ' + (isConnector ? "team" : "agent") + '">' + (isConnector ? "连接器" : "插件") + "</span>" +
          '<span class="badge cat">' + esc(typeLabel) + "</span>" +
          '<span class="badge cat">' + esc(it.source === "workbuddy" ? "WorkBuddy" : "Codex") + "</span>" +
        "</div>" +
        '<p class="card-desc">' + esc(it.description || "") + "</p>" +
        '<div class="card-tags">' + auth + skillInfo + mcp + "</div>" +
        '<div class="card-foot">' +
          '<span class="card-updated">' + esc(it.version || "") + "</span>" +
          '<button class="btn btn-primary btn-detail">详情</button>' +
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
      c.addEventListener("click", () => {
        const it = state.items.find((x) => x.id === c.dataset.id);
        if (it) openModal(it);
      });
    });
  }

  function openModal(it) {
    const isConnector = it.kind === "connector";
    const typeLabel = {
      mcp: "MCP 连接", cli: "CLI 包装", "skill-only": "纯技能"
    }[it.type] || "插件";
    const installCmd = isConnector
      ? "# 连接器(需 octopus 后端):\n" +
        "POST /api/connectors/" + it.plugin + "/install      # 安装(技能→skills)\n" +
        "POST /api/connectors/" + it.plugin + "/connect      # 认证编排(token/CLI登录)\n" +
        "GET  /api/connectors/" + it.plugin + "/headers      # 得到 auth 注入头\n" +
        "GET  /api/connectors/" + it.plugin + "/status       # 认证状态"
      : "# Codex 插件(OpenAI/Codex 生态):\n" +
        "来源: " + it.path + "\n" +
        "app.json 依赖 connector: " + (it.connectors || []).join(", ") + "\n" +
        "在 Codex 桌面端启用该插件即可;octopus 侧按 skills 导入。" +
        ((it.skills || []).length ? "\n捆绑技能: " + it.skills.join(", ") : "");

    const skillsHtml = isConnector
      ? ""
      : (it.skills && it.skills.length
          ? '<div class="section-title">捆绑技能</div><div class="card-tags">' +
            it.skills.map((s) => '<span class="tag">' + esc(s) + "</span>").join("") + "</div>"
          : "");
    const mcpHtml = (it.mcp_servers || []).length
      ? '<div class="section-title">MCP Server</div><ul class="prompt-list">' +
        it.mcp_servers.map((m) => "<li>" + esc(m) + "</li>").join("") + "</ul>"
      : "";
    const examples = (it.examples_zh || []).length
      ? '<div class="section-title">快捷示例</div><ul class="prompt-list">' +
        it.examples_zh.map((ex) => "<li>" + esc(ex) + "</li>").join("") + "</ul>"
      : "";

    $("#modal-body").innerHTML =
      '<div class="modal-head">' +
        '<div class="modal-avatar" style="display:flex;align-items:center;justify-content:center;font-size:34px">' +
        (isConnector ? "🔌" : "🧩") + "</div>" +
        "<div><h2 class='modal-title'>" + esc(it.name_zh || it.name) + "</h2>" +
        '<p class="modal-prof">' + esc(it.name || "") + "</p>" +
        '<div class="card-badges">' +
          '<span class="badge ' + (isConnector ? "team" : "agent") + '">' + (isConnector ? "连接器" : "插件") + "</span>" +
          '<span class="badge cat">' + esc(typeLabel) + "</span>" +
          '<span class="badge cat">' + esc(it.source === "workbuddy" ? "WorkBuddy" : "Codex") + "</span>" +
        "</div></div></div>" +
      '<p class="modal-desc">' + esc(it.description || "") + "</p>" +
      '<div class="meta-grid">' +
        '<div class="meta-item"><b>标识</b><span>' + esc(it.id) + "</span></div>" +
        (it.auth_mode ? '<div class="meta-item"><b>认证模式</b><span>' + esc(it.auth_mode) + "</span></div>" : "") +
        (isConnector ? '<div class="meta-item"><b>捆绑技能</b><span>' + (it.skills_count || 0) + "</span></div>" : "") +
        '<div class="meta-item"><b>版本</b><span>' + esc(it.version || "") + "</span></div>" +
      "</div>" +
      mcpHtml + skillsHtml + examples +
      '<div class="section-title">接入指引</div><pre class="cmd">' + esc(installCmd) + "</pre>";

    $("#modal").hidden = false;
    document.body.style.overflow = "hidden";
  }

  function closeModal() {
    $("#modal").hidden = true;
    document.body.style.overflow = "";
  }

  $("#modal-close").addEventListener("click", closeModal);
  $("#modal").addEventListener("click", (ev) => { if (ev.target === $("#modal")) closeModal(); });
  document.addEventListener("keydown", (ev) => { if (ev.key === "Escape") closeModal(); });
  $("#search").addEventListener("input", (ev) => { state.q = ev.target.value; render(); });
  document.querySelectorAll(".filter-group [data-kind]").forEach((c) => {
    c.addEventListener("click", () => {
      state.kind = c.dataset.kind;
      document.querySelectorAll(".filter-group [data-kind]").forEach((x) => x.classList.toggle("active", x === c));
      render();
    });
  });
  document.querySelectorAll(".chip-type").forEach((c) => {
    c.addEventListener("click", () => {
      state.type = c.dataset.type;
      document.querySelectorAll(".chip-type").forEach((x) => x.classList.toggle("active", x === c));
      render();
    });
  });

  load();
})();
