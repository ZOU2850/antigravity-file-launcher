(function () {
  // ---------- Automatic Light/Dark Theme Sync with Antigravity ----------
  function syncScheme() {
    try {
      const probe = document.createElement("span");
      probe.style.cssText = "position:absolute;visibility:hidden;pointer-events:none;color:var(--background, #f7f7f8)";
      (document.body || document.documentElement).appendChild(probe);
      const c = getComputedStyle(probe).color;
      probe.remove();
      const nums = (c.match(/[\d.]+/g) || []).map(Number);
      if (nums.length < 3) return;
      const scale = c.startsWith("color(") ? 1 : 255;
      const r = nums[0] / scale;
      const g = nums[1] / scale;
      const b = nums[2] / scale;
      const lum = 0.2126 * r + 0.7152 * g + 0.0722 * b;
      const theme = lum < 0.5 ? "dark" : "light";
      if (document.documentElement.dataset.theme !== theme) {
        document.documentElement.dataset.theme = theme;
      }
    } catch (e) {}
  }

  syncScheme();
  new MutationObserver(() => {
    syncScheme();
  }).observe(document.documentElement, { attributes: true, attributeFilter: ["style"] });

  let LAST_THEME_MSG_TS = 0;
  let HOST_UUC_READY_TS = 0;

  window.addEventListener("message", (event) => {
    if (event.data && event.data.type === "theme-change") {
      LAST_THEME_MSG_TS = Date.now();
      if (isRealSidecarVisible()) {
        HOST_UUC_READY_TS = LAST_THEME_MSG_TS;
      }
      setTimeout(syncScheme, 0);
    }
  });

  const NATIVE_FILEVIEW_EXTS = new Set([
    ".md", ".txt", ".json", ".py", ".js", ".mjs", ".ts", ".css", ".ps1",
    ".xml", ".yaml", ".yml", ".log", ".csv", ".html", ".htm",
    ".png", ".jpg", ".jpeg", ".webp", ".svg", ".gif"
  ]);

  const CATEGORY_ORDER = ["word", "markdown", "ppt", "excel", "pdf", "image", "text", "media", "code", "other"];
  const CATEGORY_LABELS = {
    all: "全部文档",
    word: "Word",
    markdown: "Markdown",
    ppt: "PPT",
    excel: "Excel",
    pdf: "PDF",
    image: "图片",
    text: "文本/网页",
    media: "音视频",
    code: "代码/其他",
    other: "其他"
  };

  let state = {
    // tab: "session" (本次产出) | "sent" (我发送的文件) | "pinned" (★收藏防压缩) | "archived" (已归档) | "recent" (最近项目/目录)
    tab: "session",
    category: "all",
    groupByType: true,
    sortBy: "time_desc",
    selectMode: false,
    selectedPaths: new Set(),
    search: "",
    activeProjectId: "scope:conv",
    userChoseProject: false,
    scopeMenuOpen: false,
    lastConvId: "",
    conversationId: "",
    lastWorkspaceSig: "",
    realProjects: [],
    conversations: [],
    localDirs: [],
    projects: [],
    sessionFiles: [],
    sentFiles: [],
    pinnedFiles: [],
    archivedFiles: [],
    recentFiles: [],
    chatAttachedFiles: [],
    openMenuPath: null,
    collapsedGroups: new Set(),
    activeInternalDoc: null,
    attachedPaths: new Set(),
  };

  const APP_VER = "2.3";
  const MOUNT_AT = Date.now();
  let LAST_VISIBLE_AT = 0;
  let wasRealVisible = false;
  let pollAbortCtrl = null;

  function isRealSidecarVisible() {
    if (document.visibilityState !== "visible") return false;
    const w = window.innerWidth || document.documentElement.clientWidth || 0;
    const h = window.innerHeight || document.documentElement.clientHeight || 0;
    return w > 24 && h > 24;
  }

  function updateVisibilityTimestamp() {
    const vis = isRealSidecarVisible();
    if (vis && !wasRealVisible) {
      LAST_VISIBLE_AT = Date.now();
      if (LAST_THEME_MSG_TS >= LAST_VISIBLE_AT - 200) {
        HOST_UUC_READY_TS = Math.max(HOST_UUC_READY_TS, LAST_THEME_MSG_TS);
      }
    }
    if (!vis) {
      HOST_UUC_READY_TS = 0;
    }
    wasRealVisible = vis;
    return vis;
  }

  async function waitForHostUucReady() {
    const baseTs = Math.max(MOUNT_AT, LAST_VISIBLE_AT || MOUNT_AT);
    const deadline = baseTs + 750;
    while (isRealSidecarVisible()) {
      const hostSignaled =
        HOST_UUC_READY_TS >= baseTs ||
        (LAST_THEME_MSG_TS >= baseTs - 150 && Date.now() - baseTs >= 120);
      if (hostSignaled || Date.now() >= deadline) {
        await new Promise((r) => {
          if (typeof requestAnimationFrame === "function") {
            requestAnimationFrame(() => requestAnimationFrame(r));
          } else {
            setTimeout(r, 32);
          }
        });
        return true;
      }
      await new Promise((r) => setTimeout(r, 60));
    }
    return false;
  }
  updateVisibilityTimestamp();

  const el = (id) => document.getElementById(id);

  function sidecarFetch(url, opts) {
    if (window.sidecar && typeof window.sidecar.fetch === "function") {
      return window.sidecar.fetch(url, opts);
    }
    return fetch(url, opts);
  }

  function showToast(msg) {
    const t = el("toastMsg");
    if (!t) return;
    t.textContent = msg;
    t.classList.remove("hidden");
    clearTimeout(showToast._t);
    showToast._t = setTimeout(() => t.classList.add("hidden"), 2800);
  }

  function getConversationId() {
    if (window.sidecar && window.sidecar.conversationId) {
      return window.sidecar.conversationId;
    }
    const params = new URLSearchParams(window.location.search);
    return params.get("conversationId") || state.conversationId || "";
  }

  state.cachedWorkspaceUris = (() => {
    try {
      const raw = sessionStorage.getItem("fl_ws_uris");
      const arr = raw ? JSON.parse(raw) : [];
      return Array.isArray(arr) ? arr : [];
    } catch (e) {
      return [];
    }
  })();

  async function getWorkspaceUrisList() {
    try {
      if (window.sidecar && typeof window.sidecar.getWorkspaceUris === "function") {
        const res = await Promise.race([
          Promise.resolve(window.sidecar.getWorkspaceUris()),
          new Promise((resolve) => setTimeout(() => resolve(null), 250)),
        ]);
        if (Array.isArray(res)) {
          state.cachedWorkspaceUris = res;
          try { sessionStorage.setItem("fl_ws_uris", JSON.stringify(res)); } catch (e) {}
          return res;
        }
      }
    } catch (e) {}
    return state.cachedWorkspaceUris || [];
  }

  function belongsToProject(f, scopeId) {
    if (!f) return false;
    const sid = scopeId || "scope:conv";
    if (sid === "all") return true;
    if (sid === "scope:conv") {
      return Boolean(f.isCurrentConv) || (Boolean(state.conversationId) && f.convId === state.conversationId);
    }
    if (sid.startsWith("conv:")) {
      const targetCid = sid.slice(5);
      return f.convId === targetCid || (!f.convId && targetCid === state.conversationId && Boolean(f.isCurrentConv));
    }
    if (sid.startsWith("agproj:")) {
      return (f.agProjectId || "") === sid || (f.projectId || "") === sid;
    }
    if (sid.startsWith("local:")) {
      if ((f.localDirId || "") === sid || (f.projectId || "") === sid) return true;
      const prefix = sid.slice(6).replace(/[\\/]+$/, "");
      const fp = String(f.path || "").toLowerCase();
      return Boolean(prefix) && (fp === prefix || fp.startsWith(prefix + "\\") || fp.startsWith(prefix + "/"));
    }
    return (f.projectId || "") === sid;
  }

  function getActiveConvProjectIds() {
    const set = new Set();
    const curCid = state.conversationId || state.lastConvId;
    [...(state.sessionFiles || []), ...(state.sentFiles || [])].forEach((f) => {
      if (!f) return;
      const isCur = Boolean(f.isCurrentConv) || (Boolean(curCid) && f.convId === curCid);
      if (isCur && f.agProjectId) {
        set.add(f.agProjectId);
      }
    });
    return set;
  }

  function esc(s) {
    return String(s || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function formatSize(bytes) {
    if (!bytes || bytes <= 0) return "";
    if (bytes < 1024) return bytes + " B";
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
    return (bytes / (1024 * 1024)).toFixed(1) + " MB";
  }

  function formatTime(ms) {
    if (!ms) return "";
    const d = new Date(ms);
    const pad = (n) => String(n).padStart(2, "0");
    return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
  }

  async function triggerExternalOpen(filePath, mode, appId) {
    try {
      const q = new URLSearchParams({
        path: filePath,
        mode: mode || "default",
        appId: appId || "",
      });
      const res = await sidecarFetch("/api/open?" + q.toString());
      const data = await res.json();
      if (data.ok) {
        if (mode === "reveal") showToast("已在文件资源管理器中定位");
        else if (mode === "open_with_dialog") showToast("已调出系统选择打开方式窗口");
        else showToast("已打开文件");
      } else {
        showToast("无法打开: " + (data.error || "未知错误"));
      }
    } catch (err) {
      showToast("请求失败: " + err.message);
    }
  }

  async function executeBatchAction(op, paths) {
    if (!paths || !paths.length) {
      showToast("请先勾选至少一个文件");
      return;
    }
    try {
      const q = new URLSearchParams({
        op,
        paths: JSON.stringify(paths),
        conversationId: getConversationId(),
      });
      const res = await sidecarFetch("/api/batch?" + q.toString());
      const data = await res.json();
      if (!data.ok) {
        showToast("操作失败: " + (data.error || "未知错误"));
        return;
      }
      if (op === "pin") {
        showToast(`★ 已收藏 ${paths.length} 个文件（已开启防上下文压缩保护）`);
      } else if (op === "unpin") {
        showToast("已取消收藏");
      } else if (op === "archive") {
        showToast(`📦 已归档 ${paths.length} 个文件至 ${data.archiveDir || "Archived_Docs"}`);
      } else if (op === "unarchive") {
        showToast("已移出归档列表");
      }
      await fetchState(true);
    } catch (err) {
      showToast("请求失败: " + err.message);
    }
  }

  // ---------- 默认打开方式：在 Antigravity 右侧分栏打开（与对话里点文件链接的原生体验一致） ----------
  async function resolveSide(f) {
    if (f.openUri) return { uri: f.openUri, kind: f.sideKind || "native" };
    try {
      const q = new URLSearchParams({ path: f.path, conversationId: getConversationId() });
      const res = await sidecarFetch("/api/side-uri?" + q.toString());
      const d = await res.json();
      if (d && d.ok) {
        f.openUri = d.uri || "";
        f.sideKind = d.kind;
        return { uri: d.uri || "", kind: d.kind };
      }
    } catch (e) {}
    return { uri: "", kind: "unknown" };
  }

  async function openInSidePane(f) {
    if (!f || !f.path) return;
    if (f.path === "__AUTO_RELOAD_SIDECAR__") {
      try {
        const u = new URL(window.location.href);
        u.searchParams.set("v", APP_VER + "_" + Date.now());
        window.location.replace(u.toString());
      } catch (e) {
        window.location.reload();
      }
      return;
    }
    const side = await resolveSide(f);
    if (side.kind === "external") {
      triggerExternalOpen(f.path, "default", "");
      showToast("该格式无法在侧边栏预览，已用电脑默认软件打开");
      return;
    }
    // Always open inside sidecar's internal reader as guaranteed visible fallback
    openInternalReader(f);
    const ui = window.sidecar && window.sidecar.ui;
    if (side.uri && ui && typeof ui.toggleAuxPane === "function") {
      // Omit targetConversationId so Antigravity spc() routes to the currently focused pane reliably
      ui.toggleAuxPane({ tabType: "fileView", uri: side.uri, keepOpen: true, background: false });
      showToast(side.kind === "mirror" ? `已在侧边栏打开 ${f.name}（只读预览）` : `已在侧边栏打开 ${f.name}`);
      return;
    }
    showToast(`已在右侧面板打开 ${f.name}`);
  }

  function formatChatRefsText(list) {
    return (list || [])
      .map((f) => `@${f.name}（${f.path}）`)
      .join("\n");
  }

  async function copyTextToClipboard(text) {
    if (!text) return false;
    try {
      if (navigator.clipboard && typeof navigator.clipboard.writeText === "function") {
        await navigator.clipboard.writeText(text);
        return true;
      }
    } catch (e) {}
    try {
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.style.cssText = "position:fixed;left:-9999px;top:-9999px;opacity:0;";
      document.body.appendChild(ta);
      ta.focus();
      ta.select();
      const ok = document.execCommand("copy");
      ta.remove();
      return Boolean(ok);
    } catch (e) {
      return false;
    }
  }

  async function sendAttachedToAI(files) {
    const list = (files && files.length ? files : state.chatAttachedFiles) || [];
    if (!list.length) {
      showToast("当前对话引用栏为空");
      return;
    }
    const msg = "请结合以下我加入对话的文件继续协助：\n" + formatChatRefsText(list);
    const agent = window.sidecar && window.sidecar.agent;
    if (agent && typeof agent.sendMessage === "function") {
      try {
        await agent.sendMessage(msg, getConversationId());
        showToast(`已将 ${list.length} 个引用文件直接发送给 AI`);
        return;
      } catch (e) {}
    }
    const copied = await copyTextToClipboard(msg);
    showToast(copied ? "已复制引用内容到剪贴板，请直接 Ctrl+V 发送给 AI" : "当前环境不支持直接发送，请手动粘贴路径");
  }

  function syncAttachedPathSet() {
    state.attachedPaths = new Set((state.chatAttachedFiles || []).map((x) => String(x.path || "").toLowerCase()).filter(Boolean));
  }

  // ---------- 加入对话框：持久化跨项目/跨对话引用，并注入宿主原生 Comment Pill（仅当 Cyc 真正可见挂载时） ----------
  let lastLocalAttachedMutAt = 0;
  const lastInjectedAtByPath = new Map();
  const HOST_INJECT_COOLDOWN_MS = 1200;

  async function attachToChat(files, skipServerRecord) {
    const list = (files || []).filter((f) => f && f.path);
    if (!list.length) {
      showToast("请先勾选至少一个文件");
      return;
    }
    lastLocalAttachedMutAt = Date.now();
    const convId = getConversationId();
    if (!skipServerRecord) {
      try {
        const qPaths = JSON.stringify(list.map((f) => f.path));
        const r = await sidecarFetch("/api/attach-record?conversationId=" + encodeURIComponent(convId) + "&paths=" + encodeURIComponent(qPaths));
        const d = await r.json();
        if (d && d.ok && Array.isArray(d.chatAttachedFiles)) {
          state.chatAttachedFiles = d.chatAttachedFiles;
          syncAttachedPathSet();
        }
      } catch (e) {}
    } else {
      const existing = [...(state.chatAttachedFiles || [])];
      const byLow = new Set(existing.map((x) => String(x.path || "").toLowerCase()));
      list.forEach((f) => {
        if (!byLow.has(f.path.toLowerCase())) {
          existing.unshift(f);
          byLow.add(f.path.toLowerCase());
        }
      });
      state.chatAttachedFiles = existing;
      syncAttachedPathSet();
    }

    const addedHost = await injectHostComments(list, true, !!skipServerRecord);
    showToast(
      addedHost > 0
        ? `已注入 ${addedHost} 个「Comment 引用气泡」到输入框上方（若在输入框点删除图标移除，点「🔄 补发气泡」可重新写入）`
        : `已把 ${list.length} 个文件加入本对话引用栏（可点「🚀 直接发给 AI」或「📋 复制引用」）`
    );
    renderChatAttachedBar();
    renderList();
  }

  async function injectHostComments(files, quiet, force) {
    const list = (files || []).filter((f) => f && f.path);
    if (!list.length) return 0;
    const ui = window.sidecar && window.sidecar.ui;
    if (!isRealSidecarVisible() || !ui || typeof ui.addArtifactComment !== "function") {
      if (!quiet) showToast("当前侧边栏未展开，请先点「File Launcher」或使用「🚀 直接发给 AI / 📋 复制引用」");
      return 0;
    }
    let addedHost = 0;
    let skipped = 0;
    const now = Date.now();
    for (const f of list) {
      const lp = String(f.path || "").toLowerCase();
      const prevAt = lastInjectedAtByPath.get(lp) || 0;
      if (!force && now - prevAt < HOST_INJECT_COOLDOWN_MS) {
        skipped++;
        continue;
      }
      try {
        let targetUri = f.openUri || "";
        if (!targetUri) {
          const side = await resolveSide(f);
          targetUri = (side && side.uri) || "";
        }
        if (!targetUri) targetUri = f.fileUri;
        const scopeLabel = f.convTitle || f.projectName || "";
        const scopeTag = scopeLabel ? ` [${scopeLabel}]` : "";
        const commentText = `已引用${scopeTag}：请结合文件「${f.name}」内容回答`;
        const titleText = scopeLabel && !f.isCurrentConv ? `${f.name} · ${scopeLabel}` : f.name;
        ui.addArtifactComment({
          uri: targetUri,
          comment: commentText,
          selection: { content: `${f.name}${scopeTag}` },
          pageTitle: titleText,
        });
        lastInjectedAtByPath.set(lp, Date.now());
        addedHost++;
        if (list.length > 1) {
          await new Promise((r) => setTimeout(r, 15));
        }
      } catch (e) {}
    }
    if (!quiet) {
      if (addedHost > 0) {
        showToast(`已写入/补发 ${addedHost} 个宿主「Comment 气泡」（在输入框气泡内点删除图标可移除）`);
      } else if (skipped > 0) {
        showToast("刚刚已发送过气泡注入请求，请稍等片刻");
      }
    }
    return addedHost;
  }

  async function detachFromChat(filePath, clearAll) {
    try {
      lastLocalAttachedMutAt = Date.now();
      const convId = getConversationId();
      if (clearAll) {
        lastInjectedAtByPath.clear();
      } else if (filePath) {
        lastInjectedAtByPath.delete(String(filePath).toLowerCase());
      }
      const url = clearAll
        ? "/api/detach?op=clear&conversationId=" + encodeURIComponent(convId)
        : "/api/detach?conversationId=" + encodeURIComponent(convId) + "&path=" + encodeURIComponent(filePath);
      const res = await sidecarFetch(url);
      const data = await res.json();
      if (data && data.ok) {
        state.chatAttachedFiles = data.chatAttachedFiles || [];
        syncAttachedPathSet();
        renderChatAttachedBar();
        renderList();
        showToast("已同步移出引用栏（Antigravity 宿主安全边界限制：输入框已生成的「Comment」气泡需在气泡内点删除图标移除）");
      }
    } catch (e) {}
  }

  function findFileByPath(p) {
    const pools = [
      state.sessionFiles,
      state.sentFiles,
      state.pinnedFiles,
      state.archivedFiles,
      state.recentFiles,
      state.chatAttachedFiles,
    ];
    for (const pool of pools) {
      const hit = (pool || []).find((x) => x.path === p);
      if (hit) return hit;
    }
    return null;
  }

  // 兜底：宿主 API 不可用时，在面板内置阅读器里展示
  async function openInternalReader(f) {
    if (!f || !f.path) return;
    state.activeInternalDoc = f;
    el("listViewWrap").classList.add("hidden");
    el("internalDocView").classList.remove("hidden");
    el("docTopTitle").textContent = f.name;
    el("docContent").innerHTML = '<div class="empty-box">正在加载文档内容...</div>';

    const docMenu = el("docMenuDrop");
    const matched = Array.isArray(f.matchedApps) ? f.matchedApps : [];
    const appBtns = matched
      .map((a) => `<button class="menu-item" data-mode="app" data-app="${esc(a.id)}"><span>${esc(a.name)}</span></button>`)
      .join("");
    docMenu.innerHTML = `
      ${appBtns ? `<div class="menu-section-label">匹配的应用</div>${appBtns}<div class="menu-divider"></div>` : ""}
      <button class="menu-item" data-mode="reveal"><span>文件资源管理器</span></button>
      <button class="menu-item" data-mode="open_with_dialog"><span>选择打开方式...</span></button>
    `;
    docMenu.querySelectorAll(".menu-item").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        docMenu.classList.add("hidden");
        triggerExternalOpen(f.path, btn.getAttribute("data-mode"), btn.getAttribute("data-app") || "");
      });
    });

    try {
      const res = await sidecarFetch("/api/preview?path=" + encodeURIComponent(f.path));
      const d = await res.json();
      if (!d.ok) {
        el("docContent").innerHTML = `<div class="empty-box">${esc(d.error || "无法加载")}</div>`;
        return;
      }
      if (d.kind === "image") {
        el("docContent").innerHTML = `<div style="text-align:center;"><img src="${d.rawUrl}" style="max-width:100%;border-radius:6px;border:1px solid var(--border-strong);" /></div>`;
      } else {
        el("docContent").innerHTML = d.html || '<div class="empty-box">暂无内容</div>';
      }
    } catch (err) {
      el("docContent").innerHTML = `<div class="empty-box">读取失败: ${esc(err.message)}</div>`;
    }
  }

  function closeInternalDocView() {
    state.activeInternalDoc = null;
    el("internalDocView").classList.add("hidden");
    el("listViewWrap").classList.remove("hidden");
  }

  function switchTab(nextTab) {
    state.tab = nextTab;
    state.category = "all";
    el("tabSession").classList.toggle("active", nextTab === "session");
    el("tabSent").classList.toggle("active", nextTab === "sent");
    el("tabPinned").classList.toggle("active", nextTab === "pinned");
    el("tabRecent").classList.toggle("active", nextTab === "recent");
    renderAll();
  }

  function updateSortButtonUI() {
    const btn = el("sortTimeBtn");
    const label = el("sortTimeLabel");
    if (!btn || !label) return;
    if (state.sortBy === "time_desc") {
      btn.classList.add("active");
      label.textContent = "时间↓";
    } else if (state.sortBy === "time_asc") {
      btn.classList.add("active");
      label.textContent = "时间↑";
    } else {
      btn.classList.remove("active");
      label.textContent = "时间";
    }
  }

  function updateCompositeBarUI() {
    const bar = el("compositeBar");
    const selectBtn = el("selectModeBtn");
    selectBtn.classList.toggle("active", state.selectMode);
    selectBtn.querySelector("span").textContent = state.selectMode ? "退出选择" : "选择";

    if (!state.selectMode) {
      bar.classList.add("hidden");
      return;
    }
    bar.classList.remove("hidden");
    el("selCountLabel").textContent = `已选 ${state.selectedPaths.size} 项`;
  }

  el("docBackBtn").addEventListener("click", closeInternalDocView);
  el("docMenuBtn").addEventListener("click", (e) => {
    e.stopPropagation();
    el("docMenuDrop").classList.toggle("hidden");
  });

  document.addEventListener("click", (e) => {
    if (!e.target.closest(".open-with-wrap")) {
      state.openMenuPath = null;
      document.querySelectorAll(".dropdown-menu").forEach((m) => m.classList.add("hidden"));
    }
    if (!e.target.closest("#scopeWrap")) {
      if (state.scopeMenuOpen) {
        state.scopeMenuOpen = false;
        const dd = el("scopeDropdown");
        if (dd) dd.classList.add("hidden");
      }
    }
  });

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && state.scopeMenuOpen) {
      state.scopeMenuOpen = false;
      const dd = el("scopeDropdown");
      if (dd) dd.classList.add("hidden");
    }
  });

  if (el("scopeTrigger")) {
    el("scopeTrigger").addEventListener("click", (e) => {
      e.stopPropagation();
      state.scopeMenuOpen = !state.scopeMenuOpen;
      const dd = el("scopeDropdown");
      if (dd) dd.classList.toggle("hidden", !state.scopeMenuOpen);
    });
  }

  el("tabSession").addEventListener("click", () => switchTab("session"));
  el("tabSent").addEventListener("click", () => switchTab("sent"));
  el("tabPinned").addEventListener("click", () => switchTab("pinned"));
  el("tabRecent").addEventListener("click", () => switchTab("recent"));

  el("selectModeBtn").addEventListener("click", () => {
    state.selectMode = !state.selectMode;
    if (!state.selectMode) {
      state.selectedPaths.clear();
    }
    updateCompositeBarUI();
    renderList();
  });

  el("selAllBtn").addEventListener("click", () => {
    const visible = getFilteredFiles();
    const allSelected = visible.length > 0 && visible.every((f) => state.selectedPaths.has(f.path));
    if (allSelected) {
      state.selectedPaths.clear();
    } else {
      visible.forEach((f) => state.selectedPaths.add(f.path));
    }
    updateCompositeBarUI();
    renderList();
  });

  el("batchPinBtn").addEventListener("click", () => {
    executeBatchAction("pin", Array.from(state.selectedPaths));
  });

  el("batchArchiveBtn").addEventListener("click", () => {
    executeBatchAction("archive", Array.from(state.selectedPaths));
  });

  el("batchChatBtn").addEventListener("click", () => {
    const files = Array.from(state.selectedPaths).map(findFileByPath).filter(Boolean);
    attachToChat(files);
    state.selectMode = false;
    state.selectedPaths.clear();
    updateCompositeBarUI();
    renderList();
  });

  el("sortTimeBtn").addEventListener("click", () => {
    if (state.sortBy === "time_desc") {
      state.sortBy = "time_asc";
      showToast("已切换为：按时间从早到晚排序");
    } else {
      state.sortBy = "time_desc";
      showToast("已切换为：按时间从新到旧排序");
    }
    updateSortButtonUI();
    renderList();
  });

  el("groupToggleBtn").addEventListener("click", () => {
    state.groupByType = !state.groupByType;
    el("groupToggleBtn").classList.toggle("active", state.groupByType);
    renderList();
  });

  el("searchInput").addEventListener("input", (e) => {
    state.search = (e.target.value || "").trim().toLowerCase();
    renderAll();
  });

  el("refreshBtn").addEventListener("click", () => {
    fetchState(true);
    showToast("已刷新");
  });

  function getBaseFilesForTab(tabName, scopeId) {
    const sid = scopeId || state.activeProjectId || "scope:conv";
    if (tabName === "sent") {
      return (state.sentFiles || []).filter((f) => belongsToProject(f, sid));
    }
    if (tabName === "pinned") {
      return (state.pinnedFiles || []).filter((f) => belongsToProject(f, sid));
    }
    if (tabName === "archived") {
      return (state.archivedFiles || []).filter((f) => belongsToProject(f, sid));
    }
    if (tabName === "recent") {
      if (sid === "all") return state.recentFiles || [];
      if (sid.startsWith("local:") || sid.startsWith("agproj:")) {
        return (state.recentFiles || []).filter((f) => belongsToProject(f, sid));
      }
      // Inside a specific conversation scope: match files belonging to that conv OR its Antigravity Project
      const activeProjs = sid === "scope:conv" ? getActiveConvProjectIds() : new Set();
      return (state.recentFiles || []).filter(
        (f) => belongsToProject(f, sid) || (f.agProjectId && activeProjs.has(f.agProjectId))
      );
    }
    return (state.sessionFiles || []).filter((f) => belongsToProject(f, sid));
  }

  function getBaseFiles() {
    return getBaseFilesForTab(state.tab, state.activeProjectId);
  }

  function switchProject(nextScopeId) {
    state.activeProjectId = nextScopeId || "scope:conv";
    state.userChoseProject = true;
    state.scopeMenuOpen = false;
    const dd = el("scopeDropdown");
    if (dd) dd.classList.add("hidden");
    state.category = "all";
    state.selectedPaths.clear();
    if (state.selectMode) updateCompositeBarUI();

    const curHas = getBaseFilesForTab(state.tab, state.activeProjectId).length > 0;
    if (!curHas) {
      if (state.activeProjectId.startsWith("local:") && getBaseFilesForTab("recent", state.activeProjectId).length > 0) {
        switchTab("recent");
        return;
      }
      if (getBaseFilesForTab("session", state.activeProjectId).length > 0) {
        switchTab("session");
        return;
      }
      if (getBaseFilesForTab("sent", state.activeProjectId).length > 0) {
        switchTab("sent");
        return;
      }
      if (getBaseFilesForTab("recent", state.activeProjectId).length > 0) {
        switchTab("recent");
        return;
      }
    }
    renderAll();
  }

  function applySort(files) {
    const list = [...files];
    list.sort((a, b) => {
      // Starred/Pinned files always stay protected at top in session view
      if (state.tab === "session" && Boolean(a.isPinned) !== Boolean(b.isPinned)) {
        return a.isPinned ? -1 : 1;
      }
      if (state.sortBy === "time_asc") {
        return (a.mtimeMs || 0) - (b.mtimeMs || 0);
      }
      return (b.mtimeMs || 0) - (a.mtimeMs || 0);
    });
    return list;
  }

  function getFilteredFiles() {
    const baseFiles = getBaseFiles();
    return applySort(
      baseFiles.filter((f) => {
        if (state.search) {
          const hay = ((f.name || "") + " " + (f.path || "") + " " + (f.categoryLabel || "")).toLowerCase();
          if (!hay.includes(state.search)) return false;
        } else if (state.category === "all") {
          if (state.tab !== "sent" && state.tab !== "pinned" && state.tab !== "archived" && !f.isReadable) return false;
        } else {
          if ((f.category || "other") !== state.category) return false;
        }
        return true;
      })
    );
  }

  function renderCategoryBar(baseFiles) {
    const strip = el("catStrip");
    const counts = { all: 0 };
    baseFiles.forEach((f) => {
      const cat = f.category || "other";
      counts[cat] = (counts[cat] || 0) + 1;
      if (state.tab === "sent" || state.tab === "pinned" || state.tab === "archived" || f.isReadable) counts.all += 1;
    });

    const allLabel =
      state.tab === "sent" ? "全部我发送的" :
      state.tab === "pinned" ? "全部收藏(防压缩)" :
      state.tab === "archived" ? "全部已归档" : "全部文档";
    const pills = ["all", ...CATEGORY_ORDER.filter((c) => (counts[c] || 0) > 0)];
    strip.innerHTML = "";

    pills.forEach((cat) => {
      const btn = document.createElement("button");
      btn.className = "cat-pill" + (state.category === cat ? " active" : "");
      const label = cat === "all" ? allLabel : (CATEGORY_LABELS[cat] || cat);
      btn.innerHTML = `<span>${esc(label)}</span><span class="cat-num">${counts[cat] || 0}</span>`;
      btn.addEventListener("click", () => {
        state.category = cat;
        renderAll();
      });
      strip.appendChild(btn);
    });

    // Quick entry pills for Archived & Sent when in other tabs
    const div = document.createElement("span");
    div.className = "cat-divider";
    strip.appendChild(div);

    const archBtn = document.createElement("button");
    archBtn.className = "cat-pill" + (state.tab === "archived" ? " active" : "");
    archBtn.innerHTML = `<span>📦 已归档</span><span class="cat-num">${(state.archivedFiles || []).length}</span>`;
    archBtn.addEventListener("click", () => switchTab("archived"));
    strip.appendChild(archBtn);
  }

  function createItemElement(f) {
    const item = document.createElement("div");
    const isSelected = state.selectedPaths.has(f.path);
    item.className = "codex-item" + (isSelected ? " selected" : "");
    const extLabel = f.isDir ? "DIR" : (f.ext || "FILE").replace(".", "").toUpperCase();
    const matched = Array.isArray(f.matchedApps) ? f.matchedApps : [];
    const sizeTxt = formatSize(f.size);
    const timeTxt = formatTime(f.mtimeMs);

    const appButtonsHtml = matched
      .map((a) => `<button class="menu-item" data-mode="app" data-app="${esc(a.id)}"><span>${esc(a.name)}</span></button>`)
      .join("");

    const isMenuOpen = state.openMenuPath === f.path;
    const isSent = Boolean(f.isUserSent) || state.tab === "sent";
    const subParts = [];
    if (isSent && f.sentScopeLabel) subParts.push(f.sentScopeLabel);
    if (timeTxt) subParts.push(timeTxt);
    if (sizeTxt) subParts.push(sizeTxt);
    if (!isSent && f.dir) subParts.push(f.dir);

    const checkHtml = state.selectMode
      ? `<span class="sel-check ${isSelected ? "checked" : ""}" data-act="toggle-select">${isSelected ? "✓" : ""}</span>`
      : `<button class="star-btn ${f.isPinned ? "pinned" : ""}" data-act="toggle-pin" title="${f.isPinned ? "已收藏（防上下文压缩保护中），点击取消" : "收藏此文件（防止上下文压缩丢失）"}">${f.isPinned ? "★" : "☆"}</button>`;

    const attachedFlag = state.attachedPaths.has(String(f.path || "").toLowerCase());
    const showProjBadge =
      f.projectName &&
      (state.activeProjectId === "all" || (state.activeProjectId === "scope:conv" && String(f.projectId || "").startsWith("proj:")));

    const badgesHtml =
      (showProjBadge ? `<span class="proj-tag" title="所属项目">${esc(f.projectName)}</span>` : "") +
      (f.isPinned ? `<span class="pin-badge" title="防上下文压缩保护中">★防压缩</span>` : "") +
      (f.isArchived ? `<span class="arch-badge">已归档</span>` : "") +
      (attachedFlag ? `<span class="chat-badge" title="已加入对话框，会随下一条消息发送">已加入对话</span>` : "");

    item.innerHTML = `
      <div class="item-main" data-act="main-click" title="${state.selectMode ? "点击勾选/取消勾选" : "点击在右侧侧边栏打开"}">
        ${checkHtml}
        <span class="ext-pill ${esc(f.category || "other")}">${esc(extLabel)}</span>
        <div class="item-text">
          <div class="item-name">${esc(f.name)}${badgesHtml}</div>
          <div class="item-sub">${esc(subParts.join(" · "))}</div>
        </div>
      </div>
      <div class="open-with-wrap">
        <button class="open-with-btn" data-act="toggle-menu">
          <span>打开方式</span>
          <svg viewBox="0 0 24 24" class="svg-caret"><path d="m6 9 6 6 6-6"/></svg>
        </button>
        <div class="dropdown-menu ${isMenuOpen ? "" : "hidden"}">
          <button class="menu-item" data-mode="side_open">
            <span>在侧边栏打开</span>
            <span class="menu-tag">默认</span>
          </button>
          <button class="menu-item" data-mode="copy_chat">
            <span>${attachedFlag ? "移出对话框" : "加入对话框"}</span>
          </button>
          <div class="menu-divider"></div>
          <div class="menu-section-label">文件管理</div>
          <button class="menu-item" data-mode="pin_toggle">
            <span>${f.isPinned ? "★ 取消收藏保留" : "★ 收藏保留 (防压缩)"}</span>
          </button>
          <button class="menu-item" data-mode="archive_toggle">
            <span>${f.isArchived ? "📦 移出归档" : "📦 归档保存"}</span>
          </button>
          <div class="menu-divider"></div>
          <button class="menu-item" data-mode="default">
            <span>用电脑默认软件打开</span>
          </button>
          ${matched.length ? `<div class="menu-section-label">匹配的应用</div>${appButtonsHtml}<div class="menu-divider"></div>` : ""}
          <button class="menu-item" data-mode="reveal">
            <span>文件资源管理器</span>
          </button>
          <button class="menu-item" data-mode="open_with_dialog">
            <span>选择打开方式...</span>
          </button>
        </div>
      </div>
    `;

    const pinBtn = item.querySelector('[data-act="toggle-pin"]');
    if (pinBtn) {
      pinBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        executeBatchAction(f.isPinned ? "unpin" : "pin", [f.path]);
      });
    }

    item.querySelector('[data-act="main-click"]').addEventListener("click", () => {
      if (state.selectMode) {
        if (state.selectedPaths.has(f.path)) state.selectedPaths.delete(f.path);
        else state.selectedPaths.add(f.path);
        updateCompositeBarUI();
        renderList();
      } else {
        openInSidePane(f);
      }
    });

    const menuEl = item.querySelector(".dropdown-menu");
    item.querySelector('[data-act="toggle-menu"]').addEventListener("click", (e) => {
      e.stopPropagation();
      const willOpen = menuEl.classList.contains("hidden");
      document.querySelectorAll(".dropdown-menu").forEach((m) => m.classList.add("hidden"));
      if (willOpen) {
        menuEl.classList.remove("hidden");
        state.openMenuPath = f.path;
      } else {
        state.openMenuPath = null;
      }
    });

    menuEl.querySelectorAll(".menu-item").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        menuEl.classList.add("hidden");
        state.openMenuPath = null;
        const mode = btn.getAttribute("data-mode");
        const appId = btn.getAttribute("data-app") || "";
        if (mode === "side_open") {
          openInSidePane(f);
        } else if (mode === "pin_toggle") {
          executeBatchAction(f.isPinned ? "unpin" : "pin", [f.path]);
        } else if (mode === "copy_chat") {
          if (state.attachedPaths.has(String(f.path || "").toLowerCase())) {
            detachFromChat(f.path, false);
          } else {
            attachToChat([f]);
          }
        } else if (mode === "archive_toggle") {
          executeBatchAction(f.isArchived ? "unarchive" : "archive", [f.path]);
        } else {
          triggerExternalOpen(f.path, mode, appId);
        }
      });
    });

    return item;
  }

  function renderProjectBar() {
    const trigName = el("scopeTriggerName");
    const kindBadge = el("scopeKindBadge");
    const trigCount = el("scopeTriggerCount");
    const projStat = el("scopeProjStat");
    const dd = el("scopeDropdown");
    if (!trigName || !kindBadge || !dd) return;

    const realProjects = state.realProjects || [];
    const convs = state.conversations || [];
    const localDirs = state.localDirs || [];
    const sid = state.activeProjectId || "scope:conv";

    if (projStat) {
      projStat.textContent = `项目: ${realProjects.length}`;
      projStat.title = realProjects.length
        ? `已识别 ${realProjects.length} 个 Antigravity 项目/工作区`
        : "您目前尚未建立 Antigravity 项目；左侧边栏列出的都是独立对话";
    }

    let curKindText = "对话";
    let isLocalKind = false;
    let curName = "当前对话";
    let curCount = 0;

    if (sid === "all") {
      curKindText = "全部";
      curName = "全部对话与本地文件";
      curCount = (state.sessionFiles || []).length + (state.sentFiles || []).length;
    } else if (sid.startsWith("agproj:")) {
      const hit = realProjects.find((x) => x.id === sid);
      curKindText = "项目";
      curName = hit ? hit.name : sid.slice(7);
      curCount = hit ? hit.count || 0 : 0;
    } else if (sid.startsWith("local:")) {
      const hit = localDirs.find((x) => x.id === sid);
      curKindText = "本地目录";
      isLocalKind = true;
      curName = hit ? hit.name : sid.slice(6);
      curCount = hit ? hit.count || 0 : 0;
    } else {
      const hit =
        convs.find((x) => x.id === sid) ||
        convs.find((x) => x.isCurrent) ||
        convs[0];
      curKindText = "对话";
      curName = hit ? (hit.isCurrent ? `${hit.name} (当前)` : hit.name) : "当前对话";
      curCount = hit ? hit.count || 0 : 0;
    }

    kindBadge.textContent = curKindText;
    kindBadge.classList.toggle("is-local", isLocalKind);
    trigName.textContent = curName;
    if (trigCount) trigCount.textContent = String(curCount);

    dd.innerHTML = "";

    function makeOpt({ id, icon, title, count, isCur, isWs, titleAttr }) {
      const btn = document.createElement("button");
      btn.type = "button";
      const isAct = sid === id || (sid === "scope:conv" && isCur && id.startsWith("conv:"));
      btn.className = "scope-opt" + (isAct ? " active" : "");
      if (titleAttr) btn.title = titleAttr;
      const wsDot = isWs ? `<span class="proj-ws-dot" title="当前打开的工作区"></span>` : "";
      const curTag = isCur ? `<span class="scope-opt-cur">当前</span>` : "";
      const mark = isAct ? `<span>✓</span>` : "";
      btn.innerHTML = `
        <span class="scope-opt-left">
          ${wsDot}
          <span>${icon}</span>
          <span class="scope-opt-title">${esc(title)}</span>
          ${curTag}
        </span>
        <span class="scope-opt-right">
          <span>${count}</span>
          ${mark}
        </span>
      `;
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        switchProject(id);
      });
      return btn;
    }

    // 1. Antigravity Projects section (honestly shows 0 when user has none)
    const projHead = document.createElement("div");
    projHead.className = "scope-group-title";
    projHead.textContent = `Antigravity 项目 (${realProjects.length})`;
    dd.appendChild(projHead);
    if (!realProjects.length) {
      const emptyProj = document.createElement("div");
      emptyProj.className = "scope-empty-hint";
      emptyProj.textContent = "暂无已建项目（当前左侧边栏均为独立对话）";
      dd.appendChild(emptyProj);
    } else {
      realProjects.forEach((p) => {
        dd.appendChild(
          makeOpt({
            id: p.id,
            icon: "📁",
            title: p.name,
            count: p.count || 0,
            isWs: Boolean(p.isWorkspace),
            titleAttr: p.path ? `Antigravity 项目目录：${p.path}` : p.name,
          })
        );
      });
    }

    // 2. Conversations section (exact left-sidebar titles)
    const d1 = document.createElement("div");
    d1.className = "scope-divider";
    dd.appendChild(d1);

    const convHead = document.createElement("div");
    convHead.className = "scope-group-title";
    convHead.textContent = `左侧边栏对话 (${convs.length}) · 与主界面名称一致`;
    dd.appendChild(convHead);
    if (!convs.length) {
      const emptyConv = document.createElement("div");
      emptyConv.className = "scope-empty-hint";
      emptyConv.textContent = "未读取到左侧边栏对话";
      dd.appendChild(emptyConv);
    } else {
      convs.forEach((c) => {
        dd.appendChild(
          makeOpt({
            id: c.id,
            icon: "💬",
            title: c.name,
            count: c.count || 0,
            isCur: Boolean(c.isCurrent),
            titleAttr: `对话：${c.name}\nID: ${c.convId}`,
          })
        );
      });
    }

    // 3. Local folders (unattached to Antigravity Projects)
    if (localDirs.length) {
      const d2 = document.createElement("div");
      d2.className = "scope-divider";
      dd.appendChild(d2);
      const localHead = document.createElement("div");
      localHead.className = "scope-group-title";
      localHead.textContent = `本地文件夹 · 非 Antigravity 项目 (${localDirs.length})`;
      dd.appendChild(localHead);
      localDirs.forEach((ld) => {
        dd.appendChild(
          makeOpt({
            id: ld.id,
            icon: "📂",
            title: ld.name,
            count: ld.count || 0,
            titleAttr: `本地目录（非 Antigravity 项目）：${ld.path}`,
          })
        );
      });
    }

    // 4. All option
    const d3 = document.createElement("div");
    d3.className = "scope-divider";
    dd.appendChild(d3);
    dd.appendChild(
      makeOpt({
        id: "all",
        icon: "🌐",
        title: "全部对话与本地文件",
        count: (state.sessionFiles || []).length + (state.sentFiles || []).length,
        titleAttr: "跨对话、跨目录浏览全部文件",
      })
    );
  }

  function renderChatAttachedBar() {
    const bar = el("chatAttachedBar");
    if (!bar) return;
    const items = state.chatAttachedFiles || [];
    if (!items.length) {
      bar.classList.add("hidden");
      bar.innerHTML = "";
      return;
    }
    bar.classList.remove("hidden");
    bar.innerHTML = "";

    const top = document.createElement("div");
    top.className = "chat-attached-top";

    const head = document.createElement("span");
    head.className = "chat-attached-head";
    head.textContent = `💬 已加入本对话 (${items.length}) · 支持跨对话/跨目录引用`;
    top.appendChild(head);

    const acts = document.createElement("div");
    acts.className = "chat-attached-actions";

    const sendBtn = document.createElement("button");
    sendBtn.type = "button";
    sendBtn.className = "chat-act-btn primary";
    sendBtn.textContent = "🚀 直接发给 AI";
    sendBtn.title = "通过 Antigravity 原生接口立即作为消息发送给 AI";
    sendBtn.addEventListener("click", () => sendAttachedToAI(items));
    acts.appendChild(sendBtn);

    const copyBtn = document.createElement("button");
    copyBtn.type = "button";
    copyBtn.className = "chat-act-btn";
    copyBtn.textContent = "📋 复制引用";
    copyBtn.title = "复制 @文件名 与完整路径到剪贴板，可在对话框中 Ctrl+V 粘贴";
    copyBtn.addEventListener("click", async () => {
      const ok = await copyTextToClipboard(formatChatRefsText(items));
      showToast(ok ? `已复制 ${items.length} 个文件引用，请 Ctrl+V 粘贴到对话框` : "复制失败");
    });
    acts.appendChild(copyBtn);

    const hostBtn = document.createElement("button");
    hostBtn.type = "button";
    hostBtn.className = "chat-act-btn";
    hostBtn.textContent = "🔄 补发气泡";
    hostBtn.title = "注入/补发 Antigravity 输入框上方的 Comment 引用气泡（若被手动删除，点此可重新写入）";
    hostBtn.addEventListener("click", () => injectHostComments(items, false, true));
    acts.appendChild(hostBtn);

    const clearBtn = document.createElement("button");
    clearBtn.type = "button";
    clearBtn.className = "chat-act-btn";
    clearBtn.textContent = "清空";
    clearBtn.addEventListener("click", () => detachFromChat("", true));
    acts.appendChild(clearBtn);

    top.appendChild(acts);
    bar.appendChild(top);

    const chipsWrap = document.createElement("div");
    chipsWrap.className = "chat-chips-wrap";
    items.forEach((item) => {
      const chip = document.createElement("div");
      chip.className = "chat-chip";
      const scopeName = item.convTitle || item.projectName || "";
      chip.title = `${item.name}${scopeName ? " · 来源: " + scopeName : ""}\n点击在侧边栏打开`;
      const projHtml = scopeName ? `<span class="chat-chip-proj">${esc(scopeName)}</span>` : "";
      chip.innerHTML = `
        <span class="chat-chip-name">${esc(item.name)}</span>
        ${projHtml}
        <button class="chat-chip-x" title="移出本对话引用">×</button>
      `;
      chip.addEventListener("click", (e) => {
        if (e.target.closest(".chat-chip-x")) {
          e.stopPropagation();
          detachFromChat(item.path, false);
          return;
        }
        openInSidePane(item);
      });
      chipsWrap.appendChild(chip);
    });
    bar.appendChild(chipsWrap);

    const note = document.createElement("div");
    note.className = "chat-attached-note";
    note.textContent =
      "此处可随时点 × 撤回或「清空」；若误写入过 Antigravity 输入栏「Comment 胶囊」，点击输入框上的 Comment 气泡即可单独删除。";
    bar.appendChild(note);
  }

  function renderList() {
    const container = el("fileListContainer");
    const filtered = getFilteredFiles();

    const sessBase = getBaseFilesForTab("session", state.activeProjectId);
    const sentBase = getBaseFilesForTab("sent", state.activeProjectId);
    const pinBase = getBaseFilesForTab("pinned", state.activeProjectId);
    const recBase = getBaseFilesForTab("recent", state.activeProjectId);

    const readableSessionCount = sessBase.filter((f) => f.isReadable).length;
    const sentCount = sentBase.length;
    const pinnedCount = pinBase.length;
    const readableRecentCount = recBase.filter((f) => f.isReadable).length;
    el("countSession").textContent = String(readableSessionCount || sessBase.length);
    el("countSent").textContent = String(sentCount);
    el("countPinned").textContent = String(pinnedCount);
    el("countRecent").textContent = String(readableRecentCount || recBase.length);

    if (!filtered.length) {
      if (state.tab === "sent") {
        container.innerHTML = `<div class="empty-box">当前范围下暂无您发送的文件（可在顶部下拉切换其他对话或目录并「加入对话框」）</div>`;
      } else if (state.tab === "pinned") {
        container.innerHTML = `<div class="empty-box">当前范围下暂无收藏保留的文件（点击 ☆ 或「选择 -> 收藏」可防止上下文压缩丢失）</div>`;
      } else if (state.tab === "archived") {
        container.innerHTML = `<div class="empty-box">当前范围下暂无已归档的文件（可通过「选择 -> 归档」将成品文档归档保存）</div>`;
      } else if (state.tab === "session") {
        container.innerHTML = `<div class="empty-box">当前范围下暂无会话产出（可在顶部下拉选择其他左侧边栏对话或本地文件夹查看）</div>`;
      } else if ((state.realProjects || []).length === 0 && !String(state.activeProjectId || "").startsWith("local:") && state.activeProjectId !== "all") {
        container.innerHTML = `<div class="empty-box">您目前尚未创建任何 Antigravity 项目；可在顶部下拉中选择「本地文件夹」或「全部」查看本地磁盘文件</div>`;
      } else {
        container.innerHTML = `<div class="empty-box">当前范围分类下暂无可读文件</div>`;
      }
      return;
    }

    container.innerHTML = "";

    if (state.category === "all" && state.groupByType) {
      const buckets = new Map();
      filtered.forEach((f) => {
        const key = f.category || "other";
        if (!buckets.has(key)) buckets.set(key, []);
        buckets.get(key).push(f);
      });

      CATEGORY_ORDER.forEach((catKey) => {
        const groupFiles = buckets.get(catKey);
        if (!groupFiles || !groupFiles.length) return;

        const block = document.createElement("div");
        block.className = "group-block" + (state.collapsedGroups.has(catKey) ? " collapsed" : "");

        const head = document.createElement("div");
        head.className = "group-head";
        head.innerHTML = `
          <div class="group-head-left">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="group-caret"><path d="m6 9 6 6 6-6"/></svg>
            <span>${esc(CATEGORY_LABELS[catKey] || catKey)}</span>
            <span class="seg-count">(${groupFiles.length})</span>
          </div>
        `;
        head.addEventListener("click", () => {
          if (state.collapsedGroups.has(catKey)) state.collapsedGroups.delete(catKey);
          else state.collapsedGroups.add(catKey);
          block.classList.toggle("collapsed");
        });

        const itemsWrap = document.createElement("div");
        itemsWrap.className = "group-items";
        groupFiles.forEach((f) => itemsWrap.appendChild(createItemElement(f)));

        block.appendChild(head);
        block.appendChild(itemsWrap);
        container.appendChild(block);
      });
    } else {
      filtered.forEach((f) => container.appendChild(createItemElement(f)));
    }
  }

  function renderAll() {
    renderProjectBar();
    renderChatAttachedBar();
    updateSortButtonUI();
    updateCompositeBarUI();
    renderCategoryBar(getBaseFiles());
    renderList();
  }

  async function fetchState(manual) {
    try {
      const convId = getConversationId();
      const wsList = await getWorkspaceUrisList();
      const wsSig = JSON.stringify(wsList || []);
      if (convId && convId !== state.lastConvId) {
        state.lastConvId = convId;
        state.userChoseProject = false;
      } else if (wsSig !== state.lastWorkspaceSig) {
        state.lastWorkspaceSig = wsSig;
        state.userChoseProject = false;
      }

      const url =
        "/api/state?client=sidecar&ver=" +
        APP_VER +
        "&visible=" +
        (isRealSidecarVisible() ? "1" : "0") +
        "&conversationId=" +
        encodeURIComponent(convId) +
        "&workspaceUris=" +
        encodeURIComponent(wsSig);
      const res = await sidecarFetch(url);
      const data = await res.json();
      if (!data.ok) return;

      state.conversationId = data.conversationId || state.conversationId || convId;
      state.realProjects = data.realProjects || [];
      state.conversations = data.conversations || [];
      state.localDirs = data.localDirs || [];
      state.projects = data.projects || [];
      state.sessionFiles = data.sessionFiles || [];
      state.sentFiles = data.sentFiles || [];
      state.pinnedFiles = data.pinnedFiles || [];
      state.archivedFiles = data.archivedFiles || [];
      state.recentFiles = data.recentFiles || [];
      state.chatAttachedFiles = data.chatAttachedFiles || [];
      syncAttachedPathSet();

      const validScope = (id) =>
        id === "all" ||
        id === "scope:conv" ||
        state.realProjects.some((p) => p.id === id) ||
        state.conversations.some((c) => c.id === id) ||
        state.localDirs.some((d) => d.id === id) ||
        state.projects.some((p) => p.id === id);

      const defaultScope = data.activeScopeId || data.activeProjectId || "scope:conv";
      if (!state.userChoseProject) {
        state.activeProjectId = defaultScope;
      } else if (state.activeProjectId && !validScope(state.activeProjectId)) {
        state.activeProjectId = defaultScope;
      }

      if (data.pendingInternalOpen && data.pendingInternalOpen.file) {
        openInSidePane(data.pendingInternalOpen.file);
      }

      renderAll();
    } catch (err) {
      console.error("Failed to fetch state:", err);
    }
  }

  // 对话里的文件卡片把动作写进队列，只有当右侧 File Launcher 面板真正具备宽高并可见（K6c visible=true 且 Cyc 已挂载）时才消费并执行
  async function startPollLoop() {
    while (true) {
      try {
        pollAbortCtrl = new AbortController();
        const visFlag = updateVisibilityTimestamp() ? "1" : "0";
        const res = await sidecarFetch("/api/poll-open?wait=15&visible=" + visFlag, {
          signal: pollAbortCtrl.signal,
        });
        const data = await res.json();
        if (data && data.ok && Array.isArray(data.queue) && data.queue.length > 0 && isRealSidecarVisible()) {
          const hasHostAction = data.queue.some((a) => a && (a.type === "open" || a.type === "attach"));
          if (hasHostAction) {
            await waitForHostUucReady();
          }
          const ackIds = [];
          for (const action of data.queue) {
            if (action.type === "open" && action.file) {
              await openInSidePane(action.file);
            } else if (action.type === "attach") {
              await attachToChat(action.files || [], true);
            } else if (action.type === "sync_attached") {
              if (!action.ts || action.ts * 1000 >= lastLocalAttachedMutAt - 150) {
                state.chatAttachedFiles = Array.isArray(action.chatAttachedFiles) ? action.chatAttachedFiles : [];
                syncAttachedPathSet();
                renderChatAttachedBar();
                renderList();
              }
            }
            if (action.id) ackIds.push(action.id);
          }
          if (ackIds.length) {
            sidecarFetch("/api/ack?ids=" + encodeURIComponent(ackIds.join(","))).catch(() => {});
          }
        }
      } catch (e) {
        if (e && e.name === "AbortError") {
          continue;
        }
        await new Promise((r) => setTimeout(r, 1200));
      }
    }
  }

  let lastReportedVis = null;
  function handleVisibilityOrResize() {
    const vis = updateVisibilityTimestamp();
    if (vis === lastReportedVis) return;
    lastReportedVis = vis;
    sidecarFetch("/api/visibility?visible=" + (vis ? "1" : "0")).catch(() => {});
    if (pollAbortCtrl) {
      try {
        pollAbortCtrl.abort();
      } catch (e) {}
    }
    if (vis) {
      fetchState(false);
    }
  }

  document.addEventListener("visibilitychange", handleVisibilityOrResize);
  window.addEventListener("resize", handleVisibilityOrResize);

  if (window.sidecar && typeof window.sidecar.onWorkspaceChange === "function") {
    window.sidecar.onWorkspaceChange((uris) => {
      if (Array.isArray(uris)) {
        state.cachedWorkspaceUris = uris;
        try { sessionStorage.setItem("fl_ws_uris", JSON.stringify(uris)); } catch (e) {}
      }
      state.userChoseProject = false;
      fetchState(false);
    });
  }

  fetchState(false);
  startPollLoop();
  setInterval(() => {
    if (!state.openMenuPath && !state.selectMode && !state.scopeMenuOpen && isRealSidecarVisible()) {
      fetchState(false);
    }
  }, 4000);
})();
