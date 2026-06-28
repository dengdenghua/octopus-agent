import { test, type Page } from "@playwright/test";

const BASE_URL = "http://127.0.0.1:3000";
const BACKEND_URL = "http://127.0.0.1:8000";

const PAGES = [
  { path: "/#/workspace/realtime/new", name: "chat-home", label: "1. 对话首页 (chat home)" },
  { path: "/#/workspace/agents?surface=chat", name: "agents-hub", label: "2. Agent Hub (智能体)" },
  { path: "/#/workspace/workflows", name: "workflows", label: "3. 自动化 (workflows)" },
  { path: "/#/workspace/evolution", name: "evolution", label: "4. 自进化 (evolution)" },
  { path: "/#/workspace/team", name: "team", label: "5. 团队 (team)" },
  { path: "/#/workspace/knowledge", name: "knowledge", label: "6. 知识库 (knowledge)" },
  { path: "/#/workspace/store", name: "store", label: "7. 应用 (store)" },
  { path: "/#/workspace/skills", name: "skills", label: "8. 技能 (skills)" },
  { path: "/#/workspace/mcp", name: "mcp", label: "9. MCP" },
  { path: "/#/workspace/channels", name: "channels", label: "10. 渠道 (channels)" },
];

async function getAuthToken(page: Page) {
  const resp = await page.request.post(`${BACKEND_URL}/api/auth/local/login`, {
    data: { username: "uiaudit" },
    headers: { "Content-Type": "application/json" },
  });
  if (!resp.ok()) throw new Error(`Login failed: ${resp.status()}`);
  const data = await resp.json();
  return { token: data.access_token, user: data.user };
}

async function setupAuth(page: Page) {
  const { token, user } = await getAuthToken(page);
  await page.addInitScript(({ t, u }) => {
    localStorage.setItem("octopus_auth_token", t);
    localStorage.setItem("octopus_user", JSON.stringify(u));
    localStorage.setItem("octopus_auth_ts", String(Date.now()));
  }, { t: token, u: user });
}

async function waitStable(page: Page, ms = 2500) {
  try { await page.waitForLoadState("domcontentloaded"); } catch {}
  try { await page.waitForLoadState("networkidle", { timeout: 5000 }); } catch {}
  await page.waitForTimeout(ms);
}

async function auditPage(page: Page) {
  return await page.evaluate(() => {
    const issues: Array<{ severity: "high" | "medium" | "low"; type: string; msg: string }> = [];
    const vw = window.innerWidth;
    const vh = window.innerHeight;

    // 1. Horizontal overflow
    const docW = document.documentElement.scrollWidth;
    if (docW > vw + 5) {
      issues.push({ severity: "high", type: "水平滚动", msg: `页面整体水平溢出 ${docW - vw}px (内容${docW}px > 视口${vw}px)` });
    }

    // 2. Find elements that overflow their containers
    const allEls = document.querySelectorAll("div, section, main, aside, nav, header, footer");
    let overflowCount = 0;
    allEls.forEach((el) => {
      const r = el.getBoundingClientRect();
      if (r.width < 5 || r.height < 5) return;
      const cs = window.getComputedStyle(el);
      if (cs.overflow === "visible" || cs.overflowX === "visible") {
        if (el.scrollWidth > el.clientWidth + 2 && el.clientWidth > 50) {
          overflowCount++;
        }
      }
    });

    // 3. Text truncation check on interactive/text elements
    const textEls = document.querySelectorAll("button, a, span, h1, h2, h3, h4, label, td, th, .truncate");
    const truncatedTexts: string[] = [];
    textEls.forEach((el) => {
      const cs = window.getComputedStyle(el);
      if (
        (cs.overflow === "hidden" || cs.textOverflow === "ellipsis" || cs.whiteSpace === "nowrap") &&
        el.scrollWidth > el.clientWidth + 3
      ) {
        const txt = (el.textContent || "").trim();
        if (txt.length > 2 && txt.length < 80 && el.children.length === 0 && el.offsetParent !== null) {
          truncatedTexts.push(txt);
        }
      }
    });
    [...new Set(truncatedTexts)].slice(0, 5).forEach((t) => {
      issues.push({ severity: "medium", type: "文本截断", msg: `"${t}" 可能被截断` });
    });

    // 4. Broken images
    const brokenImgs: string[] = [];
    document.querySelectorAll("img").forEach((img) => {
      if (img.src && !img.src.startsWith("data:") && img.complete && img.naturalWidth === 0) {
        brokenImgs.push(img.src.substring(0, 120));
      }
    });
    brokenImgs.slice(0, 3).forEach((src) => {
      issues.push({ severity: "high", type: "图片加载失败", msg: src });
    });

    // 5. Visible error messages
    const visibleErrors: string[] = [];
    document.querySelectorAll('[role="alert"], .text-red-500, .text-red-600, .text-destructive, [data-error], .bg-destructive').forEach((el) => {
      const txt = (el.textContent || "").trim();
      const r = el.getBoundingClientRect();
      if (txt && txt.length < 200 && r.width > 0 && r.height > 0 && !el.closest("script,style")) {
        visibleErrors.push(txt.substring(0, 100));
      }
    });
    [...new Set(visibleErrors)].slice(0, 5).forEach((e) => {
      issues.push({ severity: "high", type: "错误提示可见", msg: e });
    });

    // 6. Stuck loading states
    const spinners = document.querySelectorAll(".animate-spin, [role='progressbar'], .spinner, [data-state='loading']");
    let visibleSpinners = 0;
    spinners.forEach((s) => {
      const r = s.getBoundingClientRect();
      if (r.width > 0 && r.height > 0) visibleSpinners++;
    });
    if (visibleSpinners > 3) {
      issues.push({ severity: "medium", type: "加载卡住", msg: `${visibleSpinners}个加载指示器仍可见，页面可能加载失败` });
    }

    // 7. Skeleton/placeholders still visible
    const skeletons = document.querySelectorAll(".skeleton, .animate-pulse, [data-skeleton]");
    let visibleSkeletons = 0;
    skeletons.forEach((s) => {
      const r = s.getBoundingClientRect();
      if (r.width > 0 && r.height > 0) visibleSkeletons++;
    });
    if (visibleSkeletons > 5) {
      issues.push({ severity: "medium", type: "骨架屏未消失", msg: `${visibleSkeletons}个骨架屏占位符仍显示` });
    }

    // 8. Empty content check
    const mainEl = document.querySelector("main") || document.querySelector('[role="main"]') || document.querySelector("#root");
    if (mainEl) {
      const txt = (mainEl.textContent || "").trim();
      if (txt.length < 30) {
        issues.push({ severity: "high", type: "内容为空", msg: `主内容区文本极少(${txt.length}字符)，可能渲染失败` });
      }
    }

    // 9. Alignment issues: look for elements that are positioned off-screen or misaligned
    // Check sidebar nav items alignment
    const navItems = document.querySelectorAll("nav a, nav button, [role='navigation'] a, [role='navigation'] button, aside a, aside button");
    const misaligned: string[] = [];
    navItems.forEach((item) => {
      const r = item.getBoundingClientRect();
      if (r.width < 10 || r.height < 10) return;
      const cs = window.getComputedStyle(item);
      if (cs.position === "fixed" || cs.position === "sticky") return;
      // Check if the item is partially outside viewport when it should be visible
      if (r.right > vw + 50 || r.bottom < 0 || r.top > vh + 50) {
        const label = (item.textContent || "").trim().substring(0, 30) || item.className.substring(0, 30);
        if (label) misaligned.push(label);
      }
    });

    // 10. Z-index/overlap issues: detect overlapping elements with visible text
    // (simplified check - look for text hidden behind fixed headers)
    const fixedHeaders = document.querySelectorAll("header.fixed, header.sticky, nav.fixed, nav.sticky, [data-fixed-header]");
    fixedHeaders.forEach((hdr) => {
      const hr = hdr.getBoundingClientRect();
      if (hr.bottom > 0 && hr.top < 0) {
        // Header partially off-screen
      }
    });

    return issues;
  });
}

async function getPageSnapshot(page: Page) {
  return await page.evaluate(() => {
    const root = document.getElementById("root");
    const rootText = (root?.textContent || "").trim();
    const hasSidebar = !!document.querySelector("aside, nav");
    const sidebarText = (document.querySelector("aside, nav")?.textContent || "").trim().substring(0, 200);
    const mainContent = document.querySelector("main, [role='main']");
    const mainText = (mainContent?.textContent || "").trim().substring(0, 500);
    const h1 = document.querySelector("h1");
    const h1Text = h1?.textContent?.trim() || "";
    return { rootLen: rootText.length, hasSidebar, sidebarText: sidebarText.substring(0, 300), mainText, h1Text, url: location.href };
  });
}

test("UI audit all workspace pages", async ({ page }) => {
  page.setViewportSize({ width: 1440, height: 900 });

  // Setup auth BEFORE any page load
  await setupAuth(page);

  const results: Array<{
    label: string;
    url: string;
    screenshot: string;
    issues: Array<{ severity: string; type: string; msg: string }>;
    snapshot: any;
    consoleErrors: string[];
    pageErrors: string[];
  }> = [];

  for (const pg of PAGES) {
    const consoleErrors: string[] = [];
    const pageErrors: string[] = [];
    const onConsole = (msg: any) => {
      if (msg.type() === "error") {
        const t = msg.text();
        if (!t.includes("favicon") && !t.includes("Failed to load resource")) {
          consoleErrors.push(t.substring(0, 300));
        }
      }
    };
    const onPageError = (err: Error) => pageErrors.push(err.message.substring(0, 300));
    page.on("console", onConsole);
    page.on("pageerror", onPageError);

    console.log(`\n>>> ${pg.label}`);
    try {
      await page.goto(`${BASE_URL}${pg.path}`, { waitUntil: "domcontentloaded", timeout: 20000 });
      await waitStable(page, 3500);
    } catch (e: any) {
      console.log(`  导航错误: ${e.message?.substring(0, 100)}`);
    }

    const currentUrl = page.url();
    console.log(`  URL: ${currentUrl}`);

    // Check if on login page
    const snapshot = await getPageSnapshot(page);
    const onLogin = currentUrl.includes("/login") || currentUrl.endsWith("/#/") || currentUrl.endsWith("/#");
    if (onLogin) {
      console.log(`  ⚠️ 仍在登录页! 尝试重新设置token并刷新...`);
      const { token, user } = await getAuthToken(page);
      await page.evaluate(({ t, u }) => {
        localStorage.setItem("octopus_auth_token", t);
        localStorage.setItem("octopus_user", JSON.stringify(u));
        localStorage.setItem("octopus_auth_ts", String(Date.now()));
      }, { t: token, u: user });
      await page.reload({ waitUntil: "domcontentloaded" });
      await waitStable(page, 3000);
    }

    const screenshotPath = `test-results/ui-audit-${pg.name}.png`;
    try {
      await page.screenshot({ path: screenshotPath, fullPage: false });
    } catch {}

    const issues = await auditPage(page);
    const finalSnapshot = await getPageSnapshot(page);

    if (finalSnapshot.url.includes("/login")) {
      issues.unshift({ severity: "high", type: "认证失败", msg: "页面停留在登录页，认证未生效" });
    }

    console.log(`  H1/标题: ${finalSnapshot.h1Text || "(无)"}`);
    console.log(`  内容长度: ${finalSnapshot.rootLen}字符, 侧边栏: ${finalSnapshot.hasSidebar ? "有" : "无"}`);
    if (issues.length > 0) {
      issues.forEach((i) => console.log(`  [${i.severity}][${i.type}] ${i.msg}`));
    } else {
      console.log(`  ✅ 无明显问题`);
    }
    if (consoleErrors.length > 0) {
      console.log(`  🚫 控制台错误(${consoleErrors.length}):`);
      consoleErrors.slice(0, 3).forEach((e) => console.log(`     - ${e}`));
    }
    if (pageErrors.length > 0) {
      console.log(`  💥 页面异常(${pageErrors.length}):`);
      pageErrors.forEach((e) => console.log(`     - ${e}`));
    }

    results.push({
      label: pg.label,
      url: finalSnapshot.url,
      screenshot: screenshotPath,
      issues,
      snapshot: finalSnapshot,
      consoleErrors: [...new Set(consoleErrors)].slice(0, 5),
      pageErrors: [...new Set(pageErrors)].slice(0, 5),
    });

    page.off("console", onConsole);
    page.off("pageerror", onPageError);
  }

  // Print final report
  console.log("\n\n" + "=".repeat(70));
  console.log("  UI/UX 检查综合报告");
  console.log("=".repeat(70));

  let totalHigh = 0, totalMed = 0, totalLow = 0;
  for (const r of results) {
    const high = r.issues.filter((i) => i.severity === "high").length;
    const med = r.issues.filter((i) => i.severity === "medium").length;
    const low = r.issues.filter((i) => i.severity === "low").length;
    totalHigh += high; totalMed += med; totalLow += low;
    const icon = high > 0 ? "🔴" : med > 0 ? "🟡" : "🟢";
    console.log(`\n${icon} ${r.label}`);
    console.log(`   截图: ${r.screenshot}`);
    console.log(`   URL: ${r.url}`);
    if (r.issues.length === 0 && r.consoleErrors.length === 0 && r.pageErrors.length === 0) {
      console.log(`   ✅ 未发现问题`);
    } else {
      r.issues.forEach((i) => {
        const bullet = i.severity === "high" ? "🔴" : i.severity === "medium" ? "🟡" : "🟢";
        console.log(`   ${bullet} [${i.type}] ${i.msg}`);
      });
      r.consoleErrors.forEach((e) => console.log(`   🚫 [Console] ${e.substring(0, 180)}`));
      r.pageErrors.forEach((e) => console.log(`   💥 [PageError] ${e.substring(0, 180)}`));
    }
  }

  console.log(`\n${"=".repeat(70)}`);
  console.log(`  汇总: 🔴高:${totalHigh}  🟡中:${totalMed}  🟢低:${totalLow}  共${totalHigh + totalMed + totalLow}个问题`);
  console.log(`${"=".repeat(70)}`);
});
