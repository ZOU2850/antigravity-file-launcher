(function () {
  // ==================== 主题同步（支持 host / light / dark / system） ====================
  let currentThemeMode = (() => {
    try {
      return localStorage.getItem("fl_appearance_theme") || "host";
    } catch (e) {
      return "host";
    }
  })();

  function resolveHostLuminanceTheme() {
    try {
      const probe = document.createElement("span");
      probe.style.cssText = "position:absolute;visibility:hidden;pointer-events:none;color:var(--background, #f7f7f8)";
      (document.body || document.documentElement).appendChild(probe);
      const c = getComputedStyle(probe).color;
      probe.remove();
      const nums = (c.match(/[\d.]+/g) || []).map(Number);
      if (nums.length >= 3) {
        const scale = c.startsWith("color(") ? 1 : 255;
        const lum = 0.2126 * (nums[0] / scale) + 0.7152 * (nums[1] / scale) + 0.0722 * (nums[2] / scale);
        return lum < 0.5 ? "dark" : "light";
      }
    } catch (e) {}
    return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }

  function applyThemeMode(mode) {
    const valid = ["host", "light", "dark", "system"];
    const nextMode = valid.includes(mode) ? mode : "host";
    currentThemeMode = nextMode;
    try {
      localStorage.setItem("fl_appearance_theme", nextMode);
    } catch (e) {}

    document.documentElement.dataset.themeMode = nextMode;
    let resolved = "light";
    if (nextMode === "light" || nextMode === "dark") {
      resolved = nextMode;
    } else if (nextMode === "system") {
      resolved = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
    } else {
      resolved = resolveHostLuminanceTheme();
    }
    if (document.documentElement.dataset.theme !== resolved) {
      document.documentElement.dataset.theme = resolved;
    }
  }

  applyThemeMode(currentThemeMode);
  new MutationObserver(() => {
    if (currentThemeMode === "host") applyThemeMode("host");
  }).observe(document.documentElement, { attributes: true, attributeFilter: ["style"] });

  try {
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    if (mq && typeof mq.addEventListener === "function") {
      mq.addEventListener("change", () => {
        if (currentThemeMode === "system" || currentThemeMode === "host") applyThemeMode(currentThemeMode);
      });
    }
  } catch (e) {}

  window.addEventListener("message", (event) => {
    if (event.data && event.data.type === "theme-change") {
      if (currentThemeMode === "host") {
        setTimeout(() => applyThemeMode("host"), 0);
      }
    }
  });

  // ==================== 常量与全量 20+ 类型映射 ====================
  const CATEGORY_ORDER = [
    "word", "ppt", "excel", "pdf", "markdown", "image", "text", "web",
    "code", "media", "archive", "design", "database", "font", "executable", "disk", "binary", "folder", "other",
  ];
  const QUICK_CATS = ["word", "ppt", "excel", "pdf", "markdown", "image", "text", "web", "code", "media", "archive", "folder", "other"];
  const CATEGORY_LABELS = {
    all: "全部类型",
    word: "Word",
    ppt: "PPT",
    excel: "Excel",
    pdf: "PDF",
    markdown: "Markdown",
    text: "文本/配置",
    image: "图片",
    web: "网页/样式",
    code: "代码",
    media: "音视频",
    archive: "压缩包",
    design: "设计稿",
    executable: "可执行",
    database: "数据库",
    font: "字体",
    disk: "磁盘镜像",
    binary: "二进制",
    folder: "文件夹",
    other: "其他",
  };

  const SOURCE_ORDER = ["all", "delivered", "created", "edited", "attachment", "reference", "uploaded", "read", "recent", "pinned"];
  const SOURCE_LABELS = {
    all: "全部来源",
    delivered: "对话交付",
    created: "AI 生成",
    edited: "AI 修改",
    attachment: "我发送的",
    reference: "对话引用",
    uploaded: "上传附件",
    read: "参考读取",
    recent: "工作区项目",
    pinned: "防压缩收藏",
    archived: "已归档",
  };

  const IMAGE_EXTS = new Set([".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp", ".ico", ".tif", ".tiff", ".avif"]);
  const OFFICE_PAGE_EXTS = new Set([".docx", ".doc", ".pptx", ".ppt", ".xlsx", ".xls", ".odt", ".odp", ".ods", ".rtf"]);

  const APP_VER = "2.4.1";
  let LAST_AUTO_SYNC_AT = 0;
  let pollAbortCtrl = null;
  let stateAbortCtrl = null;
  let autoRefreshTimer = null;
  const comfortTimers = new WeakMap();

  function stopComfortLoader(targetEl) {
    if (!targetEl) return;
    const prev = comfortTimers.get(targetEl);
    if (prev) {
      clearInterval(prev);
      comfortTimers.delete(targetEl);
    }
  }

  function renderComfortLoadingHtml(mode, elapsedMs, baselineMs) {
    const safeElapsed = Math.max(0, Number(elapsedMs) || 0);
    const base = Math.max(900, Number(baselineMs) || 2200);
    const secStr = (safeElapsed / 1000).toFixed(1);
    const estLow = Math.max(1, Math.round((base * 0.8) / 1000));
    const estHigh = Math.max(estLow + 1, Math.ceil((base * 1.4) / 1000));
    const remainSec = Math.max(1, Math.ceil((base * 1.15 - safeElapsed) / 1000));
    const overBudget = safeElapsed > base * 1.15;
    let title = "正在为您整理对话产出与项目文件，请稍候…";
    if (mode === "viewer") {
      if (safeElapsed >= 6000) title = "文件体量较大，正在努力排版收尾，请再多等几秒…";
      else if (safeElapsed >= 2500) title = "文档内容较丰富，正在加速转换版式中，不用着急…";
      else title = "正在贴心加载文档预览，马上就能查看…";
    } else {
      if (safeElapsed >= 6000) title = "项目与历史记录较多，正在全力收尾整理，请再给一点耐心…";
      else if (safeElapsed >= 2500) title = "文件较多，正在加快扫描并对齐关联项目，很快就好…";
    }
    const eta = overBudget
      ? `已等待 ${secStr} 秒 · 资料较多，正在收尾呈现…`
      : `已等待 ${secStr} 秒 · 预计共需 ${estLow}–${estHigh} 秒（约剩 ${remainSec} 秒）`;
    const pct = overBudget
      ? Math.min(94, 78 + Math.round((safeElapsed - base * 1.15) / 800))
      : Math.min(82, Math.max(12, Math.round((safeElapsed / base) * 78)));
    return `
      <div class="empty-box fl-loading-box" role="status">
        <div class="fl-loading-head">
          <span class="fl-spinner" aria-hidden="true"></span>
          <span class="fl-loading-title">${esc(title)}</span>
        </div>
        <div class="fl-loading-track" aria-hidden="true"><div class="fl-loading-fill" style="width:${pct}%"></div></div>
        <p class="fl-loading-eta">${esc(eta)}</p>
        <p class="fl-loading-hint">就绪后会自动展示，请放心稍等片刻。</p>
      </div>`;
  }

  function startComfortLoader(targetEl, mode, baselineMs) {
    if (!targetEl) return;
    stopComfortLoader(targetEl);
    const startedAt = Date.now();
    targetEl.innerHTML = renderComfortLoadingHtml(mode, 0, baselineMs);
    const timer = setInterval(() => {
      if (!targetEl.isConnected || !targetEl.querySelector(".fl-loading-box")) {
        stopComfortLoader(targetEl);
        return;
      }
      targetEl.innerHTML = renderComfortLoadingHtml(mode, Date.now() - startedAt, baselineMs);
    }, 250);
    comfortTimers.set(targetEl, timer);
  }

  const state = {
    tab: "session",
    category: "all",
    sourceFilter: "all",
    // groupMode: "type" | "project" | "none"
    groupMode: "type",
    // sortBy: "time_desc" | "time_asc" | "name" | "type"
    sortBy: "time_desc",
    selectMode: false,
    selectedPaths: new Set(),
    search: "",
    activeProjectId: "scope:conv",
    userChoseProject: false,
    appliedDefaultScope: false,
    scopeMenuOpen: false,
    filterPopoverOpen: false,
    lastConvId: "",
    conversationId: "",
    lastWorkspaceSig: "",
    realProjects: [],
    conversations: [],
    localDirs: [],
    projects: [],
    apps: [],
    config: {
      appearanceTheme: "host",
      autoRefresh: true,
      refreshSeconds: 60,
      defaultScope: "auto",
      collapseGroups: true,
      pdfMaxPages: 20,
      pdfDpi: 110,
      maxRows: 800,
      archiveDir: "",
      defaultClickAction: "sidecar",
      language: "zh",
      watchedDirs: [],
      customApps: [],
      extDefaults: {},
    },
    settingsPaths: {},
    archiveRoot: "",
    capabilities: { pdfPages: false, officePages: false },
    sessionFiles: [],
    sentFiles: [],
    pinnedFiles: [],
    archivedFiles: [],
    recentFiles: [],
    collapsedGroups: new Set(),
    collapsedSubGroups: new Set(),
    initCollapsedApplied: false,
    activeInternalDoc: null,
    // 增强预览状态
    previewRenderMode: "auto", // "pdf" | "html" | "image"
    pdfZoom: (() => {
      try {
        const z = parseFloat(localStorage.getItem("fl_pdf_zoom") || "1");
        return z >= 0.5 && z <= 2.5 ? z : 1;
      } catch (e) {
        return 1;
      }
    })(),
    pdfPagesState: null, // { pages: [], currentPage: 1, totalPages: 1 }
    // 上下文菜单状态
    contextMenuFile: null,
    contextMenuFocusIdx: -1,
    pendingDeletePaths: [],
    notifiedCodeStale: false,
  };

  // ==================== 宿主可见性与基础工具 ====================
  function isRealSidecarVisible() {
    if (document.visibilityState !== "visible") return false;
    const w = window.innerWidth || document.documentElement.clientWidth || 0;
    const h = window.innerHeight || document.documentElement.clientHeight || 0;
    return w > 24 && h > 24;
  }

  function updateVisibilityTimestamp() {
    return isRealSidecarVisible();
  }
  updateVisibilityTimestamp();

  const el = (id) => document.getElementById(id);

  function sidecarFetch(url, opts) {
    if (window.sidecar && typeof window.sidecar.fetch === "function") {
      return window.sidecar.fetch(url, opts);
    }
    return fetch(url, opts);
  }

  function postJson(url, payload) {
    return sidecarFetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload || {}),
    });
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
      return (
        Boolean(f.isCurrentConv) ||
        (Boolean(state.conversationId) &&
          (f.convId === state.conversationId || (Array.isArray(f.convIds) && f.convIds.includes(state.conversationId))))
      );
    }
    if (sid.startsWith("conv:")) {
      const targetCid = sid.slice(5);
      return (
        f.convId === targetCid ||
        (Array.isArray(f.convIds) && f.convIds.includes(targetCid)) ||
        (!f.convId && targetCid === state.conversationId && Boolean(f.isCurrentConv))
      );
    }
    if (sid.startsWith("agproj:")) {
      return (f.agProjectId || "") === sid || (f.projectId || "") === sid;
    }
    if (sid.startsWith("local:")) {
      if ((f.localDirId || "") === sid || (f.projectId || "") === sid) return true;
      const prefix = sid.slice(6).replace(/[\\/]+$/, "").toLowerCase();
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
      if (isCur && f.agProjectId) set.add(f.agProjectId);
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

  function formatMentionRef(f) {
    if (!f) return "";
    const p = String(f.path || "").trim();
    if (!p) return "";
    const name = String(f.name || "").trim();
    if (name) return `@${name}（${p}）`;
    return /\s/.test(p) ? `@"${p}"` : `@${p}`;
  }

  function formatChatRefsText(list) {
    return (list || []).map((f) => formatMentionRef(f)).filter(Boolean).join("\n");
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

  async function copyFileReferences(files) {
    const list = (files || []).filter((f) => f && f.path);
    if (!list.length) {
      showToast("请先选择或勾选至少一个文件");
      return false;
    }
    const text = formatChatRefsText(list);
    const ok = await copyTextToClipboard(text);
    if (ok) {
      showToast(
        list.length === 1
          ? `已复制「${list[0].name}」引用，请到聊天框 Ctrl+V 发送`
          : `已复制 ${list.length} 项引用，请到聊天框 Ctrl+V 发送`
      );
    } else {
      showToast("复制引用失败，请尝试右键复制完整路径");
    }
    return ok;
  }

  async function copyImageToClipboard(filePath) {
    try {
      if (!navigator.clipboard || typeof navigator.clipboard.write !== "function" || typeof ClipboardItem === "undefined") {
        showToast("当前环境不支持图片剪贴板，请复制完整路径或在浏览器中复制");
        return false;
      }
      const res = await sidecarFetch("/api/raw?path=" + encodeURIComponent(filePath));
      if (!res.ok) throw new Error("读取图片失败");
      const rawBlob = await res.blob();
      let pngBlob = rawBlob;
      if (rawBlob.type !== "image/png") {
        const imgUrl = URL.createObjectURL(rawBlob);
        try {
          const img = await new Promise((resolve, reject) => {
            const i = new Image();
            i.onload = () => resolve(i);
            i.onerror = reject;
            i.src = imgUrl;
          });
          const canvas = document.createElement("canvas");
          canvas.width = img.naturalWidth || img.width || 1;
          canvas.height = img.naturalHeight || img.height || 1;
          const ctx = canvas.getContext("2d");
          ctx.drawImage(img, 0, 0);
          pngBlob = await new Promise((resolve, reject) =>
            canvas.toBlob((b) => (b ? resolve(b) : reject(new Error("PNG 编码失败"))), "image/png")
          );
        } finally {
          URL.revokeObjectURL(imgUrl);
        }
      }
      await navigator.clipboard.write([new ClipboardItem({ "image/png": pngBlob })]);
      showToast("已复制图片到剪贴板");
      return true;
    } catch (err) {
      showToast("复制图片失败：" + (err.message || "宿主剪贴板权限受限"));
      return false;
    }
  }

  // ==================== 外部打开、批量操作、移除、永久删除 ====================
  async function triggerExternalOpen(filePath, mode, appId, rememberExt) {
    try {
      const res = await postJson("/api/open", {
        path: filePath,
        mode: mode || "default",
        appId: appId || "",
        rememberExt: Boolean(rememberExt),
      });
      const data = await res.json();
      if (data.ok) {
        if (mode === "reveal") showToast("已在文件资源管理器中定位");
        else if (mode === "open_with_dialog") showToast("已调出系统选择打开方式窗口");
        else showToast(rememberExt ? "已打开文件并设为该后缀默认程序" : "已打开文件");
        if (rememberExt) fetchState(false);
      } else {
        showToast("无法打开: " + (data.error || "文件不存在或程序未找到"));
      }
    } catch (err) {
      showToast("请求失败: " + err.message);
    }
  }

  async function openFolderAction(targetPath) {
    try {
      const res = await postJson("/api/open-folder", { path: targetPath });
      const data = await res.json();
      if (data.ok) showToast("已打开所在文件夹");
      else showToast("打开失败: " + (data.error || "路径不存在"));
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
      const res = await postJson("/api/batch", {
        op,
        paths,
        conversationId: getConversationId(),
      });
      const data = await res.json();
      if (!data.ok) {
        showToast("操作失败: " + (data.error || "未知错误"));
        return;
      }
      if (op === "pin") {
        showToast(`★ 已收藏 ${paths.length} 项（已开启防上下文压缩保护）`);
      } else if (op === "unpin") {
        showToast("已取消收藏");
      } else if (op === "archive") {
        const skippedCount = (data.skipped || []).length;
        const okCount = (data.copied || []).length;
        showToast(
          skippedCount > 0
            ? `已归档 ${okCount} 个文件，跳过 ${skippedCount} 项（目录/缺失）`
            : `📦 已按日期归档 ${okCount} 个文件至 ${data.archiveDir || "Archived_Docs"}`
        );
      } else if (op === "unarchive") {
        showToast("已移出归档视图（磁盘备份副本已保留）");
      } else if (op === "forget") {
        showToast(`已移除 ${paths.length} 条记录（未删除磁盘文件）`);
      }
      await fetchState(true);
    } catch (err) {
      showToast("请求失败: " + err.message);
    }
  }

  async function forgetPathsAction(paths) {
    if (!paths || !paths.length) return;
    try {
      const res = await postJson("/api/forget", {
        paths,
        conversationId: getConversationId(),
      });
      const data = await res.json();
      if (data.ok) {
        showToast(`已移除 ${(data.forgotten || paths).length} 条记录`);
        await fetchState(true);
      } else {
        showToast("移除失败: " + (data.error || "未知错误"));
      }
    } catch (err) {
      showToast("移除失败: " + err.message);
    }
  }

  function openDeleteConfirmModal(paths) {
    const clean = (paths || []).filter(Boolean);
    if (!clean.length) return;
    state.pendingDeletePaths = clean;
    const hasRef = clean.some((p) => {
      const hit = findFileByPath(p);
      return Boolean(hit && hit.isReference);
    });
    const box = el("delTargetPathBox");
    if (box) {
      const warn = hasRef
        ? `<div style="margin-top:6px;color:#d97706;font-size:11px;">⚠ 注意：勾选包含「引用」条目，确认将删除其指向的原磁盘文件；若仅需移出列表请取消并使用右键「移除记录」。</div>`
        : "";
      box.innerHTML = clean.map((p) => `<div>• ${esc(p)}</div>`).join("") + warn;
    }
    el("deleteConfirmModal").classList.remove("hidden");
  }

  function closeDeleteConfirmModal() {
    state.pendingDeletePaths = [];
    el("deleteConfirmModal").classList.add("hidden");
  }

  async function confirmPermanentDelete() {
    const targets = [...state.pendingDeletePaths];
    if (!targets.length) return;
    closeDeleteConfirmModal();
    try {
      const res = await postJson("/api/delete", {
        paths: targets,
        confirm: true,
        conversationId: getConversationId(),
      });
      const data = await res.json();
      if (data.deleted && data.deleted.length) {
        if (state.activeInternalDoc && targets.some((p) => p.toLowerCase() === String(state.activeInternalDoc.path).toLowerCase())) {
          closeInternalDocView();
        }
        showToast(`已永久删除 ${data.deleted.length} 个文件`);
        await fetchState(true);
      } else {
        const msg = (data.errors && data.errors[0] && data.errors[0].error) || data.error || "删除失败";
        showToast(msg);
      }
    } catch (err) {
      showToast("删除请求失败: " + err.message);
    }
  }

  // ==================== 默认打开方式 & 侧边栏分栏 & 增强预览器 ====================
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

  async function openFileByDefaultPreference(f) {
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
    if (f.missing) {
      showToast("文件不存在或已被移动（可右键移除不存在记录）");
      return;
    }
    if (f.isDir) {
      await openFolderAction(f.path);
      return;
    }
    const pref = (state.config && state.config.defaultClickAction) || "sidecar";
    if (pref === "preview") {
      await openInternalReader(f);
      return;
    }
    if (pref === "system") {
      await triggerExternalOpen(f.path, "default", "");
      return;
    }
    await openInSidePane(f);
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
    if (f.missing) {
      showToast("该文件已不存在");
      return;
    }
    if (f.isDir) {
      await openFolderAction(f.path);
      return;
    }
    const side = await resolveSide(f);
    if (side.kind === "external") {
      // 对 PDF / 图片 / 音视频 等：若本机支持内置增强预览，优先打开内置预览器；否则使用系统默认应用
      const ext = String(f.ext || "").toLowerCase();
      if (ext === ".pdf" || OFFICE_PAGE_EXTS.has(ext) || IMAGE_EXTS.has(ext)) {
        await openInternalReader(f);
        return;
      }
      await triggerExternalOpen(f.path, "default", "");
      showToast("该格式已用电脑默认软件打开");
      return;
    }
    const ui = window.sidecar && window.sidecar.ui;
    if (side.uri && ui && typeof ui.toggleAuxPane === "function") {
      try {
        const res = await ui.toggleAuxPane({ tabType: "fileView", uri: side.uri });
        if (!res || !res.isError) {
          showToast(side.kind === "mirror" ? `已在侧边栏打开 ${f.name}（只读预览）` : `已在侧边栏打开 ${f.name}`);
          return;
        }
      } catch (e) {}
    }
    await openInternalReader(f);
    showToast(`已在面板中打开 ${f.name}`);
  }

  function findFileByPath(p) {
    const pools = [
      state.sessionFiles,
      state.sentFiles,
      state.pinnedFiles,
      state.archivedFiles,
      state.recentFiles,
    ];
    for (const pool of pools) {
      const hit = (pool || []).find((x) => x.path === p);
      if (hit) return hit;
    }
    return null;
  }

  // ==================== 增强全屏内部预览器 (支持 PDF/Office 逐页、缩放、上下切换、复制图片) ====================
  function updatePdfPageIndicator() {
    const ps = state.pdfPagesState;
    if (!ps || !ps.pages.length) return;
    el("pdfPageIndicator").textContent = `${ps.currentPage} / ${ps.totalPages}`;
    el("pdfPrevPageBtn").disabled = ps.currentPage <= 1;
    el("pdfNextPageBtn").disabled = ps.currentPage >= ps.pages.length;
    el("pdfZoomLabel").textContent = `${Math.round(state.pdfZoom * 100)}%`;
  }

  function applyPdfZoomToStage() {
    const imgs = el("docContent").querySelectorAll(".pdf-page-card img");
    const baseWidth = Math.max(240, (el("docContent").clientWidth || 360) - 24);
    const targetW = Math.round(baseWidth * state.pdfZoom);
    imgs.forEach((img) => {
      img.style.width = `${targetW}px`;
      img.style.maxWidth = state.pdfZoom <= 1.02 ? "100%" : "none";
    });
    try {
      localStorage.setItem("fl_pdf_zoom", String(state.pdfZoom));
    } catch (e) {}
    updatePdfPageIndicator();
  }

  function scrollToPdfPage(pageNum) {
    const ps = state.pdfPagesState;
    if (!ps) return;
    const clamped = Math.max(1, Math.min(ps.pages.length, pageNum));
    ps.currentPage = clamped;
    updatePdfPageIndicator();
    const card = el("docContent").querySelector(`.pdf-page-card[data-page="${clamped}"]`);
    if (card) card.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  el("docContent").addEventListener("scroll", () => {
    const ps = state.pdfPagesState;
    if (!ps || !ps.pages.length) return;
    const wrap = el("docContent");
    const cards = wrap.querySelectorAll(".pdf-page-card");
    const topAnchor = wrap.getBoundingClientRect().top + 80;
    let bestPage = 1;
    cards.forEach((c) => {
      if (c.getBoundingClientRect().top <= topAnchor) {
        bestPage = parseInt(c.getAttribute("data-page") || "1", 10);
      }
    });
    if (bestPage !== ps.currentPage) {
      ps.currentPage = bestPage;
      updatePdfPageIndicator();
    }
  });

  el("pdfPrevPageBtn").addEventListener("click", () => {
    if (state.pdfPagesState) scrollToPdfPage(state.pdfPagesState.currentPage - 1);
  });
  el("pdfNextPageBtn").addEventListener("click", () => {
    if (state.pdfPagesState) scrollToPdfPage(state.pdfPagesState.currentPage + 1);
  });
  el("pdfZoomOutBtn").addEventListener("click", () => {
    state.pdfZoom = Math.max(0.5, +(state.pdfZoom - 0.15).toFixed(2));
    applyPdfZoomToStage();
  });
  el("pdfZoomInBtn").addEventListener("click", () => {
    state.pdfZoom = Math.min(2.5, +(state.pdfZoom + 0.15).toFixed(2));
    applyPdfZoomToStage();
  });
  el("pdfZoomFitBtn").addEventListener("click", () => {
    state.pdfZoom = 1.0;
    applyPdfZoomToStage();
  });

  function updateDocPrevNextButtons() {
    const list = getFilteredFiles();
    const cur = state.activeInternalDoc;
    const idx = cur ? list.findIndex((x) => x.path === cur.path) : -1;
    el("docPrevBtn").disabled = idx <= 0;
    el("docNextBtn").disabled = idx < 0 || idx >= list.length - 1;
  }

  function stepInternalPreview(delta) {
    const list = getFilteredFiles();
    const cur = state.activeInternalDoc;
    if (!cur || !list.length) return;
    const idx = list.findIndex((x) => x.path === cur.path);
    const nextIdx = idx + delta;
    if (nextIdx >= 0 && nextIdx < list.length) {
      openInternalReader(list[nextIdx]);
    }
  }

  el("docPrevBtn").addEventListener("click", () => stepInternalPreview(-1));
  el("docNextBtn").addEventListener("click", () => stepInternalPreview(1));
  el("docSidecarBtn").addEventListener("click", async () => {
    const f = state.activeInternalDoc;
    if (!f) return;
    const side = await resolveSide(f);
    const ui = window.sidecar && window.sidecar.ui;
    if (side.uri && ui && typeof ui.toggleAuxPane === "function") {
      try {
        const res = await ui.toggleAuxPane({ tabType: "fileView", uri: side.uri });
        if (!res || !res.isError) {
          if (el("docModal")) el("docModal").classList.add("hidden");
          state.activeInternalDoc = null;
          showToast(`已在侧边栏打开 ${f.name}`);
          return;
        }
      } catch (e) {}
    }
    triggerExternalOpen(f.path, "default", "");
  });

  async function openInternalReader(f) {
    if (!f || !f.path) return;
    if (f.missing) {
      showToast("文件不存在或已被移动");
      return;
    }
    state.activeInternalDoc = f;
    state.pdfPagesState = null;
    el("listViewWrap").classList.add("hidden");
    el("internalDocView").classList.remove("hidden");
    el("pdfToolbar").classList.add("hidden");
    el("docBanner").classList.add("hidden");
    el("docBanner").textContent = "";
    el("docTopTitle").textContent = f.name;
    startComfortLoader(el("docContent"), "viewer", 2400);
    updateDocPrevNextButtons();

    const docMenu = el("docMenuDrop");
    const ext = String(f.ext || "").toLowerCase();
    const isImg = IMAGE_EXTS.has(ext);
    const matched = Array.isArray(f.matchedApps) ? f.matchedApps : [];
    const appBtns = matched
      .map((a) => `<button class="menu-item" data-mode="app" data-app="${esc(a.id)}"><span>${esc(a.name)}</span></button>`)
      .join("");
    docMenu.innerHTML = `
      ${isImg ? `<button class="menu-item" data-mode="copy_image"><span>复制图片</span></button>` : ""}
      <button class="menu-item" data-mode="copy_mention"><span>@ 复制引用</span></button>
      <button class="menu-item" data-mode="copy_path"><span>复制完整路径</span></button>
      <div class="menu-divider"></div>
      ${appBtns ? `<div class="menu-section-label">匹配的应用</div>${appBtns}<div class="menu-divider"></div>` : ""}
      <button class="menu-item" data-mode="reveal"><span>文件资源管理器</span></button>
      <button class="menu-item" data-mode="open_with_dialog"><span>选择打开方式...</span></button>
    `;
    docMenu.querySelectorAll(".menu-item").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        docMenu.classList.add("hidden");
        const mode = btn.getAttribute("data-mode");
        if (mode === "copy_image") {
          copyImageToClipboard(f.path);
        } else if (mode === "copy_path") {
          copyTextToClipboard(f.path).then((ok) => showToast(ok ? "已复制完整路径" : "复制失败"));
        } else if (mode === "copy_mention") {
          copyFileReferences([f]);
        } else {
          triggerExternalOpen(f.path, mode, btn.getAttribute("data-app") || "");
        }
      });
    });

    // 1. PDF 或 Office 文件优先尝试逐页渲染
    if (ext === ".pdf" || OFFICE_PAGE_EXTS.has(ext)) {
      try {
        const res = await postJson("/api/pdf-pages", { path: f.path });
        const d = await res.json();
        if (state.activeInternalDoc !== f) return;
        if (d && d.ok && Array.isArray(d.pages) && d.pages.length) {
          state.pdfPagesState = {
            pages: d.pages,
            currentPage: 1,
            totalPages: d.totalPages || d.pages.length,
          };
          el("pdfToolbar").classList.remove("hidden");
          if (d.truncated) {
            el("docBanner").textContent = `当前仅渲染前 ${d.renderedPages} 页（共 ${d.totalPages} 页），可在右上角 ⚙ 设置中调整“PDF 最大渲染页数”。`;
            el("docBanner").classList.remove("hidden");
          }
          const cardsHtml = d.pages
            .map(
              (url, i) => `
              <div class="pdf-page-card" data-page="${i + 1}">
                <img src="${esc(url)}" loading="lazy" alt="第 ${i + 1} 页" />
                <div class="pdf-page-num">第 ${i + 1} / ${d.totalPages} 页</div>
              </div>`
            )
            .join("");
          el("docContent").innerHTML = `<div class="pdf-pages-stage">${cardsHtml}</div>`;
          applyPdfZoomToStage();
          return;
        }
        // Office 转 PDF 失败/无 LibreOffice 或无 pdfinfo 时平滑回退，并显示横幅提示
        if (d && d.error && OFFICE_PAGE_EXTS.has(ext)) {
          el("docBanner").textContent = d.error;
          el("docBanner").classList.remove("hidden");
        } else if (ext === ".pdf" && d && d.error) {
          el("docContent").innerHTML = `<div class="empty-box">${esc(d.error)}</div>`;
          return;
        }
      } catch (e) {}
    }

    // 2. HTML / 图片 / Markdown / 代码 / CSV 回退预览
    try {
      const res = await sidecarFetch("/api/preview?path=" + encodeURIComponent(f.path));
      const d = await res.json();
      if (state.activeInternalDoc !== f) return;
      if (!d.ok) {
        el("docContent").innerHTML = `<div class="empty-box">${esc(d.error || "无法加载")}</div>`;
        return;
      }
      if (d.truncated) {
        el("docBanner").textContent = `文件较大（共 ${d.totalLines || "?"} 行），当前仅预览前段内容，可点上方「分栏打开」或用编辑器查看全文。`;
        el("docBanner").classList.remove("hidden");
      }
      if (d.kind === "image") {
        el("docContent").innerHTML = `
          <div style="text-align:center;padding:8px 0;">
            <img src="${esc(d.rawUrl)}" style="max-width:100%;max-height:76vh;border-radius:6px;border:1px solid var(--border-strong);object-fit:contain;" />
            <div style="margin-top:8px;font-size:11px;color:var(--fg-muted);">可在右上角操作栏点击「复制图片」或「打开所在文件夹」</div>
          </div>`;
      } else {
        el("docContent").innerHTML = d.html || '<div class="empty-box">暂无内容</div>';
      }
    } catch (err) {
      el("docContent").innerHTML = `<div class="empty-box">读取失败: ${esc(err.message)}</div>`;
    }
  }

  function closeInternalDocView() {
    state.activeInternalDoc = null;
    state.pdfPagesState = null;
    el("internalDocView").classList.add("hidden");
    el("listViewWrap").classList.remove("hidden");
  }

  // ==================== 视图切换、排序、分组、主从 Source × Type 筛选 ====================
  function switchTab(nextTab) {
    const changed = state.tab !== nextTab;
    state.tab = nextTab;
    state.category = "all";
    state.sourceFilter = "all";
    el("tabSession").classList.toggle("active", nextTab === "session");
    el("tabSent").classList.toggle("active", nextTab === "sent");
    el("tabPinned").classList.toggle("active", nextTab === "pinned");
    el("tabRecent").classList.toggle("active", nextTab === "recent");
    el("archivedToggleBtn").classList.toggle("active", nextTab === "archived");
    renderAll();
    if (changed && Date.now() - LAST_AUTO_SYNC_AT > 1200 && isRealSidecarVisible()) {
      fetchState(false);
    }
  }

  function updateSortButtonUI() {
    const btn = el("sortTimeBtn");
    const label = el("sortTimeLabel");
    if (!btn || !label) return;
    btn.classList.add("active");
    if (state.sortBy === "time_desc") label.textContent = "时间↓";
    else if (state.sortBy === "time_asc") label.textContent = "时间↑";
    else if (state.sortBy === "name") label.textContent = "名称";
    else label.textContent = "类型";
  }

  function updateGroupButtonUI() {
    const btn = el("groupToggleBtn");
    const label = el("groupToggleLabel");
    if (!btn || !label) return;
    if (state.groupMode === "type") {
      btn.classList.add("active");
      label.textContent = "按类型";
    } else if (state.groupMode === "project") {
      btn.classList.add("active");
      label.textContent = "按项目";
    } else {
      btn.classList.remove("active");
      label.textContent = "平铺";
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

  function getBaseFilesForTab(tabName, scopeId) {
    const sid = scopeId || state.activeProjectId || "scope:conv";
    if (tabName === "sent") return (state.sentFiles || []).filter((f) => belongsToProject(f, sid));
    if (tabName === "pinned") return (state.pinnedFiles || []).filter((f) => belongsToProject(f, sid));
    if (tabName === "archived") return (state.archivedFiles || []).filter((f) => belongsToProject(f, sid));
    if (tabName === "recent") {
      if (sid === "all") return state.recentFiles || [];
      if (sid.startsWith("local:") || sid.startsWith("agproj:")) {
        return (state.recentFiles || []).filter((f) => belongsToProject(f, sid));
      }
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
    state.sourceFilter = "all";
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
    const timeKey = (x) => (state.tab === "sent" ? (x.sentAtMs || x.mtimeMs || 0) : (x.mtimeMs || 0));
    list.sort((a, b) => {
      if (state.tab === "session" && Boolean(a.isPinned) !== Boolean(b.isPinned)) {
        return a.isPinned ? -1 : 1;
      }
      if (state.sortBy === "time_asc") return timeKey(a) - timeKey(b);
      if (state.sortBy === "name") return String(a.name || "").localeCompare(String(b.name || ""), "zh-CN");
      if (state.sortBy === "type") {
        const cmp = String(a.category || "").localeCompare(String(b.category || ""));
        return cmp !== 0 ? cmp : timeKey(b) - timeKey(a);
      }
      return timeKey(b) - timeKey(a);
    });
    return list;
  }

  function matchesSourceFilter(f, srcFilter) {
    if (!srcFilter || srcFilter === "all") return true;
    if (srcFilter === "pinned") return Boolean(f.isPinned);
    if (srcFilter === "reference") return Boolean(f.isReference || f.sentKind === "reference");
    if (srcFilter === "uploaded") return Boolean(f.isUserSent) && !f.isReference && f.sentKind !== "reference";
    if (srcFilter === "delivered") return f.source === "delivered" || f.actionKind === "artifact" || f.actionKind === "linked";
    return (f.source || "") === srcFilter;
  }

  function getFilteredFiles() {
    const baseFiles = getBaseFiles();
    return applySort(
      baseFiles.filter((f) => {
        if (!matchesSourceFilter(f, state.sourceFilter)) return false;
        if (state.search) {
          const hay = (
            (f.name || "") +
            " " +
            (f.path || "") +
            " " +
            (f.refTarget || "") +
            " " +
            (f.ext || "") +
            " " +
            (f.categoryLabel || "") +
            " " +
            (f.sourceLabel || "") +
            " " +
            (f.sentScopeLabel || "") +
            (f.isReference ? " 引用 reference" : "")
          ).toLowerCase();
          if (!hay.includes(state.search)) return false;
        }
        if (state.category !== "all") {
          if ((f.category || "other") !== state.category) return false;
        } else if (!state.search && state.sourceFilter === "all") {
          // 保持原有“默认会话只突显可读交付物与代码/文件夹”或完整查看：
          // 当用户选中“参考读取”来源或主动搜索时展示全部读取的代码；默认在 session 未筛选时排除低噪 read（除非可读或文件夹）
          if (state.tab === "session" && f.source === "read" && !f.isReadable && !f.isDir) return false;
          if (state.tab === "recent" && !f.isReadable && !f.isDir) return false;
        }
        return true;
      })
    );
  }

  function renderCategoryBar(baseFiles) {
    const strip = el("catStrip");
    const counts = { all: 0 };
    baseFiles.forEach((f) => {
      if (!matchesSourceFilter(f, state.sourceFilter)) return;
      const cat = f.category || "other";
      const visibleInAll =
        state.tab === "sent" || state.tab === "pinned" || state.tab === "archived" ||
        state.sourceFilter !== "all" || Boolean(state.search) ||
        (state.tab === "session" ? !(f.source === "read" && !f.isReadable && !f.isDir) : (f.isReadable || f.isDir));
      if (visibleInAll) {
        counts.all += 1;
        counts[cat] = (counts[cat] || 0) + 1;
      } else {
        // 即使不在 默认全部 里，也统计细分数量供点击查看
        counts[cat] = (counts[cat] || 0) + 1;
      }
    });

    const allLabel =
      state.tab === "sent" ? "全部发送" :
      state.tab === "pinned" ? "全部收藏" :
      state.tab === "archived" ? "全部归档" : "全部推荐";
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
  }

  // ---------- 主从双栏 Source × Type 筛选 Popover ----------
  function renderFilterPopover() {
    const pop = el("filterPopover");
    const srcCol = el("filterSourceCol");
    const typeCol = el("filterTypeCol");
    if (!pop || !srcCol || !typeCol) return;

    const baseFiles = getBaseFiles();
    const srcCounts = {};
    SOURCE_ORDER.forEach((sk) => {
      srcCounts[sk] = sk === "all" ? baseFiles.length : baseFiles.filter((f) => matchesSourceFilter(f, sk)).length;
    });

    srcCol.innerHTML = `<div class="filter-col-title">来源 (Source)</div>`;
    SOURCE_ORDER.forEach((sk) => {
      if (sk !== "all" && srcCounts[sk] === 0 && state.sourceFilter !== sk) return;
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "filter-opt" + (state.sourceFilter === sk ? " active" : "");
      btn.innerHTML = `<span>${esc(SOURCE_LABELS[sk] || sk)}</span><span class="filter-opt-num">${srcCounts[sk] || 0}</span>`;
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        state.sourceFilter = sk;
        // 若当前选定类型在新来源下无文件，重置类型
        if (state.category !== "all") {
          const hasCat = baseFiles.some((f) => matchesSourceFilter(f, sk) && (f.category || "other") === state.category);
          if (!hasCat) state.category = "all";
        }
        renderFilterPopover();
        renderAll();
      });
      srcCol.appendChild(btn);
    });

    const sourceSubset = baseFiles.filter((f) => matchesSourceFilter(f, state.sourceFilter));
    const catCounts = { all: sourceSubset.length };
    sourceSubset.forEach((f) => {
      const c = f.category || "other";
      catCounts[c] = (catCounts[c] || 0) + 1;
    });

    typeCol.innerHTML = `<div class="filter-col-title">类型 (Type)</div>`;
    ["all", ...CATEGORY_ORDER].forEach((ck) => {
      if (ck !== "all" && !(catCounts[ck] > 0) && state.category !== ck) return;
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "filter-opt" + (state.category === ck ? " active" : "");
      btn.innerHTML = `<span>${esc(CATEGORY_LABELS[ck] || ck)}</span><span class="filter-opt-num">${catCounts[ck] || 0}</span>`;
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        state.category = ck;
        closeFilterPopover();
        renderAll();
      });
      typeCol.appendChild(btn);
    });
  }

  function openFilterPopover() {
    const pop = el("filterPopover");
    const btn = el("filterBtn");
    if (!pop || !btn) return;
    renderFilterPopover();
    pop.classList.remove("hidden");
    const r = btn.getBoundingClientRect();
    const popW = Math.min(360, window.innerWidth - 16);
    const left = Math.max(8, Math.min(r.right - popW, window.innerWidth - popW - 8));
    const top = Math.min(r.bottom + 4, window.innerHeight - 280);
    pop.style.left = `${left}px`;
    pop.style.top = `${Math.max(8, top)}px`;
    state.filterPopoverOpen = true;
  }

  function closeFilterPopover() {
    state.filterPopoverOpen = false;
    const pop = el("filterPopover");
    if (pop) pop.classList.add("hidden");
  }

  function renderActiveFiltersBar() {
    const bar = el("activeFiltersBar");
    const filterBtn = el("filterBtn");
    if (!bar) return;

    const tags = [];
    if (state.sourceFilter !== "all") {
      tags.push({ key: "source", label: `来源: ${SOURCE_LABELS[state.sourceFilter] || state.sourceFilter}` });
    }
    if (state.category !== "all") {
      tags.push({ key: "category", label: `类型: ${CATEGORY_LABELS[state.category] || state.category}` });
    }
    if (state.search) {
      tags.push({ key: "search", label: `关键词: "${state.search}"` });
    }

    if (filterBtn) {
      filterBtn.classList.toggle("active", state.sourceFilter !== "all" || state.category !== "all");
    }

    if (!tags.length) {
      bar.classList.add("hidden");
      bar.innerHTML = "";
      return;
    }
    bar.classList.remove("hidden");
    bar.innerHTML = "";
    tags.forEach((t) => {
      const chip = document.createElement("span");
      chip.className = "filter-chip";
      chip.innerHTML = `<span>${esc(t.label)}</span><button type="button" title="清除">×</button>`;
      chip.querySelector("button").addEventListener("click", () => {
        if (t.key === "source") state.sourceFilter = "all";
        else if (t.key === "category") state.category = "all";
        else if (t.key === "search") {
          state.search = "";
          if (el("searchInput")) el("searchInput").value = "";
        }
        renderAll();
      });
      bar.appendChild(chip);
    });

    const clearAll = document.createElement("button");
    clearAll.type = "button";
    clearAll.className = "filter-clear-btn";
    clearAll.textContent = "清除全部";
    clearAll.addEventListener("click", () => {
      state.sourceFilter = "all";
      state.category = "all";
      state.search = "";
      if (el("searchInput")) el("searchInput").value = "";
      renderAll();
    });
    bar.appendChild(clearAll);
  }

  // ==================== 全局浮动自适应可滚动上下文菜单 ====================
  function closeContextMenu() {
    state.contextMenuFile = null;
    state.contextMenuFocusIdx = -1;
    const menu = el("globalContextMenu");
    if (menu) {
      menu.classList.add("hidden");
      menu.innerHTML = "";
    }
  }

  function openContextMenu(f, anchorX, anchorY) {
    const menu = el("globalContextMenu");
    if (!menu || !f) return;
    closeFilterPopover();
    state.scopeMenuOpen = false;
    const dd = el("scopeDropdown");
    if (dd) dd.classList.add("hidden");

    state.contextMenuFile = f;
    state.contextMenuFocusIdx = -1;
    const ext = String(f.ext || "").toLowerCase();
    const isImg = IMAGE_EXTS.has(ext) && !f.missing;
    const matched = Array.isArray(f.matchedApps) ? f.matchedApps : [];
    const extDefaultId = (state.config && state.config.extDefaults && state.config.extDefaults[ext]) || "";
    const defAction = (state.config && state.config.defaultClickAction) || "sidecar";

    const itemsHtml = [];

    if (f.missing) {
      itemsHtml.push(`
        <button class="menu-item" data-act="forget">
          <span>🧹 移除不存在记录</span>
          <span class="menu-tag">清理</span>
        </button>
        <div class="menu-divider"></div>
        <button class="menu-item" data-act="copy_mention"><span>@ 复制引用</span></button>
        <button class="menu-item" data-act="copy_path"><span>复制原完整路径</span></button>
      `);
    } else {
      if (!f.isDir) {
        itemsHtml.push(`
          <button class="menu-item" data-act="preview_internal">
            <span>👁 在面板内预览</span>
            ${defAction === "preview" ? `<span class="menu-item-subtag">默认</span>` : ""}
          </button>
          <button class="menu-item" data-act="side_open">
            <span>📑 在侧边栏打开</span>
            ${defAction === "sidecar" ? `<span class="menu-item-subtag">默认</span>` : ""}
          </button>
        `);
      }
      itemsHtml.push(`
        <button class="menu-item" data-act="open_folder">
          <span>📂 ${f.isDir ? "在资源管理器打开目录" : "打开所在文件夹"}</span>
        </button>
      `);
      if (f.archiveInfo && f.archiveInfo.archivePath) {
        itemsHtml.push(`
          <button class="menu-item" data-act="reveal_archive">
            <span>📦 定位归档备份副本</span>
          </button>
        `);
      }
      itemsHtml.push(`<div class="menu-divider"></div>`);
      itemsHtml.push(`
        <button class="menu-item" data-act="copy_mention"><span>@ 复制引用</span></button>
        <button class="menu-item" data-act="copy_path"><span>📋 复制完整路径</span></button>
      `);
      if (isImg) {
        itemsHtml.push(`<button class="menu-item" data-act="copy_image"><span>🖼 复制图片</span></button>`);
      }

      itemsHtml.push(`<div class="menu-divider"></div><div class="menu-section-label">文件管理</div>`);
      itemsHtml.push(`
        <button class="menu-item" data-act="pin_toggle">
          <span>${f.isPinned ? "★ 取消收藏保留" : "★ 收藏保留 (防压缩)"}</span>
        </button>
        <button class="menu-item" data-act="archive_toggle">
          <span>${f.isArchived ? "📦 移出归档视图" : "📦 归档复制到日期目录"}</span>
        </button>
      `);

      if (!f.isDir) {
        itemsHtml.push(`<div class="menu-divider"></div>`);
        itemsHtml.push(`
          <button class="menu-item" data-act="open_default">
            <span>⚡ 用电脑默认软件打开</span>
            ${defAction === "system" && !extDefaultId ? `<span class="menu-item-subtag">默认</span>` : ""}
          </button>
        `);
        if (matched.length) {
          itemsHtml.push(`<div class="menu-section-label">匹配应用 (${esc(ext || "文件")})</div>`);
          matched.forEach((a) => {
            const isDef = extDefaultId === a.id;
            itemsHtml.push(`
              <button class="menu-item" data-act="open_app" data-app="${esc(a.id)}">
                <span>${esc(a.name)}</span>
                ${isDef ? `<span class="menu-item-subtag">✓ 后缀默认</span>` : `<span class="menu-tag" data-set-def="${esc(a.id)}" title="点击设为该后缀默认程序（也可按住 Alt 点击应用名）">设为默认</span>`}
              </button>
            `);
          });
        }
        itemsHtml.push(`
          <button class="menu-item" data-act="open_with_dialog"><span>🔧 选择打开方式...</span></button>
          <div class="menu-divider"></div>
          <button class="menu-item" data-act="forget"><span>🧹 仅从列表移除记录</span></button>
          <button class="menu-item danger" data-act="delete_perm"><span>🗑 永久删除文件…</span></button>
        `);
      } else {
        itemsHtml.push(`<div class="menu-divider"></div><button class="menu-item" data-act="forget"><span>🧹 从列表移除目录记录</span></button>`);
      }
    }

    menu.innerHTML = itemsHtml.join("");
    menu.classList.remove("hidden");

    // 视口边缘自适应定位（不溢出屏幕且支持上下翻转）
    menu.style.left = "0px";
    menu.style.top = "0px";
    const mw = menu.offsetWidth || 230;
    const mh = menu.offsetHeight || 280;
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    let left = Math.min(anchorX, vw - mw - 8);
    let top = anchorY + 4;
    if (top + mh > vh - 8 && anchorY - mh - 4 > 8) {
      top = anchorY - mh - 4;
    } else if (top + mh > vh - 8) {
      top = Math.max(8, vh - mh - 8);
    }
    menu.style.left = `${Math.max(8, left)}px`;
    menu.style.top = `${Math.max(8, top)}px`;

    menu.querySelectorAll(".menu-item").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        const act = btn.getAttribute("data-act");
        const appId = btn.getAttribute("data-app") || "";
        const target = state.contextMenuFile;
        closeContextMenu();
        if (!target) return;

        if (act === "preview_internal") openInternalReader(target);
        else if (act === "side_open") openInSidePane(target);
        else if (act === "open_folder") openFolderAction(target.path);
        else if (act === "reveal_archive" && target.archiveInfo?.archivePath) openFolderAction(target.archiveInfo.archivePath);
        else if (act === "copy_path") copyTextToClipboard(target.path).then((ok) => showToast(ok ? "已复制完整路径" : "复制失败"));
        else if (act === "copy_mention") copyFileReferences([target]);
        else if (act === "copy_image") copyImageToClipboard(target.path);
        else if (act === "pin_toggle") executeBatchAction(target.isPinned ? "unpin" : "pin", [target.path]);
        else if (act === "archive_toggle") executeBatchAction(target.isArchived ? "unarchive" : "archive", [target.path]);
        else if (act === "open_default") triggerExternalOpen(target.path, "default", "");
        else if (act === "open_app") {
          const setDef = Boolean(e.altKey) || Boolean(e.target && e.target.closest && e.target.closest("[data-set-def]"));
          triggerExternalOpen(target.path, "app", appId, setDef);
        } else if (act === "open_with_dialog") triggerExternalOpen(target.path, "open_with_dialog", "");
        else if (act === "forget") forgetPathsAction([target.path]);
        else if (act === "delete_perm") openDeleteConfirmModal([target.path]);
      });
    });
  }

  // ==================== 列表项与两级分组渲染 ====================
  function createItemElement(f) {
    const item = document.createElement("div");
    const isSelected = state.selectedPaths.has(f.path);
    const isRef = Boolean(f.isReference || f.sentKind === "reference");
    item.className =
      "codex-item" +
      (isSelected ? " selected" : "") +
      (isRef ? " is-reference" : "") +
      (f.missing ? " is-missing" : "");

    const extLabel = f.isDir ? "DIR" : (f.badge || (f.ext || "FILE").replace(".", "").toUpperCase());
    const sizeTxt = formatSize(f.size);
    const timeTxt = formatTime(f.mtimeMs || f.sentAtMs);
    const isSent = Boolean(f.isUserSent) || state.tab === "sent";

    const subParts = [];
    if (f.moved && f.movedFrom) subParts.push(`原路径: ${f.movedFrom}`);
    if (isSent && f.sentScopeLabel) subParts.push(f.sentScopeLabel);
    if (f.tabArchivedAt || (f.archiveInfo && f.archiveInfo.archivePath)) {
      if (state.tab === "archived" && f.archiveInfo && f.archiveInfo.archivePath) {
        subParts.push(`备份: ${f.archiveInfo.archivePath}`);
      }
    }
    if (timeTxt) subParts.push(timeTxt);
    if (sizeTxt) subParts.push(sizeTxt);
    if (isRef && (f.refOriginDir || f.dir) && !(f.moved && f.movedFrom)) {
      subParts.push(`指向: ${f.refOriginDir || f.dir}`);
    } else if (!isSent && f.dir && !(f.moved && f.movedFrom)) {
      subParts.push(f.dir);
    }

    const checkHtml = state.selectMode
      ? `<span class="sel-check ${isSelected ? "checked" : ""}" data-act="toggle-select">${isSelected ? "✓" : ""}</span>`
      : `<button class="star-btn ${f.isPinned ? "pinned" : ""}" data-act="toggle-pin" title="${f.isPinned ? "已收藏（防压缩保护中），点击取消" : "收藏此文件（防止上下文压缩丢失）"}">${f.isPinned ? "★" : "☆"}</button>`;

    const showProjBadge =
      f.projectName &&
      (state.activeProjectId === "all" || (state.activeProjectId === "scope:conv" && String(f.projectId || "").startsWith("proj:")));

    const srcCls = `src-${f.source || "recent"}`;
    const showSourceBadge = f.sourceLabel && (state.tab === "session" || state.tab === "pinned" || state.tab === "archived");

    const badgesHtml =
      (f.missing ? `<span class="missing-badge" title="文件已不存在或被移走，右键可移除记录">不存在</span>` : "") +
      (f.moved ? `<span class="moved-badge" title="原路径: ${esc(f.movedFrom || "")}">已移动</span>` : "") +
      (isRef ? `<span class="ref-badge" title="引用壳子指向：${esc(f.refTarget || f.path)}（点击直接无感打开原文件）">${esc(f.refLabel || "引用")}</span>` : "") +
      (showSourceBadge ? `<span class="source-badge ${esc(srcCls)}">${esc(f.sourceLabel)}</span>` : "") +
      (showProjBadge ? `<span class="proj-tag" title="所属项目">${esc(f.projectName)}</span>` : "") +
      (f.isPinned ? `<span class="pin-badge" title="防上下文压缩保护中">★防压缩</span>` : "") +
      (f.isArchived ? `<span class="arch-badge">已归档</span>` : "");

    const clickTitle = state.selectMode
      ? "点击勾选/取消勾选"
      : f.missing
        ? "文件不存在（右键可移除记录）"
        : f.isDir
          ? "点击在文件资源管理器打开目录"
          : "点击打开（可在设置中切换默认侧边栏分栏 / 面板内预览 / 系统软件）；右键打开操作菜单";

    item.innerHTML = `
      <div class="item-main" data-act="main-click" title="${esc(clickTitle)}">
        ${checkHtml}
        <span class="ext-pill ${esc(f.category || "other")}">${esc(extLabel)}</span>
        <div class="item-text">
          <div class="item-name">${esc(f.name)}${badgesHtml}</div>
          <div class="item-sub">${esc(subParts.join(" · "))}</div>
        </div>
      </div>
      <div class="row-actions">
        ${f.missing ? "" : `<button class="row-copy-ref-btn" data-act="copy-ref" title="复制 @ 引用（到聊天框 Ctrl+V 发送即可）">复制引用</button>`}
        <div class="open-with-wrap">
          <button class="open-with-btn" data-act="toggle-menu" title="打开方式与文件操作（或直接右键此行）">
            <span>${f.missing ? "操作" : "打开方式"}</span>
            <svg viewBox="0 0 24 24" class="svg-caret"><path d="m6 9 6 6 6-6"/></svg>
          </button>
        </div>
      </div>
    `;

    const copyRefBtn = item.querySelector('[data-act="copy-ref"]');
    if (copyRefBtn) {
      copyRefBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        copyFileReferences([f]);
      });
    }

    const pinBtn = item.querySelector('[data-act="toggle-pin"]');
    if (pinBtn) {
      pinBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        if (f.missing && !f.isPinned) {
          showToast("不存在的文件无法收藏");
          return;
        }
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
        openFileByDefaultPreference(f);
      }
    });

    item.querySelector('[data-act="toggle-menu"]').addEventListener("click", (e) => {
      e.stopPropagation();
      if (state.contextMenuFile && state.contextMenuFile.path === f.path) {
        closeContextMenu();
      } else {
        const r = e.currentTarget.getBoundingClientRect();
        openContextMenu(f, r.right - 210, r.bottom);
      }
    });

    // 对齐 DSH：整行支持右键上下文菜单
    item.addEventListener("contextmenu", (e) => {
      e.preventDefault();
      e.stopPropagation();
      openContextMenu(f, e.clientX, e.clientY);
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
        : "当前左侧边栏为独立对话";
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
      const hit = convs.find((x) => x.id === sid) || convs.find((x) => x.isCurrent) || convs[0];
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

    if (localDirs.length) {
      const d2 = document.createElement("div");
      d2.className = "scope-divider";
      dd.appendChild(d2);
      const localHead = document.createElement("div");
      localHead.className = "scope-group-title";
      localHead.textContent = `本地文件夹 · 监控目录 (${localDirs.length})`;
      dd.appendChild(localHead);
      localDirs.forEach((ld) => {
        dd.appendChild(
          makeOpt({
            id: ld.id,
            icon: "📂",
            title: ld.name,
            count: ld.count || 0,
            titleAttr: `本地目录：${ld.path}`,
          })
        );
      });
    }

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

  function renderList() {
    const container = el("fileListContainer");
    const filtered = getFilteredFiles();

    const sessBase = getBaseFilesForTab("session", state.activeProjectId);
    const sentBase = getBaseFilesForTab("sent", state.activeProjectId);
    const pinBase = getBaseFilesForTab("pinned", state.activeProjectId);
    const recBase = getBaseFilesForTab("recent", state.activeProjectId);
    const archBase = getBaseFilesForTab("archived", state.activeProjectId);

    const readableSessionCount = sessBase.filter((f) => !(f.source === "read" && !f.isReadable && !f.isDir)).length;
    el("countSession").textContent = String(readableSessionCount || sessBase.length);
    el("countSent").textContent = String(sentBase.length);
    el("countPinned").textContent = String(pinBase.length);
    el("countRecent").textContent = String(recBase.filter((f) => f.isReadable || f.isDir).length || recBase.length);
    if (el("countArchivedPill")) el("countArchivedPill").textContent = String(archBase.length);

    if (!filtered.length) {
      if (state.sourceFilter !== "all" || state.category !== "all" || state.search) {
        container.innerHTML = `<div class="empty-box">当前筛选条件下没有匹配文件（可清除右上/工具栏筛选标签）</div>`;
      } else if (state.tab === "sent") {
        container.innerHTML = `<div class="empty-box">当前范围下暂无您发送、上传或 @引用 的文件/文件夹</div>`;
      } else if (state.tab === "pinned") {
        container.innerHTML = `<div class="empty-box">暂无收藏保留文件（点 ☆ 或批量收藏可防上下文压缩）</div>`;
      } else if (state.tab === "archived") {
        container.innerHTML = `<div class="empty-box">暂无已归档文件</div>`;
      } else if (state.tab === "session") {
        container.innerHTML = `<div class="empty-box">当前会话暂未发现产出文件（可在“隔离范围”切换对话，或点“筛选 ▾ → 来源”查看所有文件）</div>`;
      } else {
        container.innerHTML = `<div class="empty-box">当前范围下暂无文件（可在“⚙ 设置”添加监控目录）</div>`;
      }
      return;
    }

    container.innerHTML = "";
    const forceExpand = Boolean(state.search || state.sourceFilter !== "all" || state.category !== "all");

    // 1. 按 项目 -> 会话 两级可折叠分组（对齐 DSH）
    if (state.groupMode === "project") {
      const projMap = new Map();
      filtered.forEach((f) => {
        const pKey = f.agProjectId || f.localDirId || "__standalone__";
        const pTitle = f.projectName || (f.localDirId ? "本地目录" : "独立对话与文件");
        if (!projMap.has(pKey)) {
          projMap.set(pKey, { key: pKey, title: pTitle, isCurProj: Boolean(f.isCurrentConv), sessMap: new Map(), count: 0 });
        }
        const pBucket = projMap.get(pKey);
        pBucket.count += 1;

        const sKey = f.convId ? `conv:${f.convId}` : "__workspace__";
        const sTitle = f.convId ? (f.convTitle || `对话 ${f.convId.slice(0, 8)}`) : "工作区最近文件";
        if (!pBucket.sessMap.has(sKey)) {
          pBucket.sessMap.set(sKey, { key: sKey, title: sTitle, isCur: Boolean(f.isCurrentConv), items: [] });
        }
        const sBucket = pBucket.sessMap.get(sKey);
        if (f.isCurrentConv) {
          pBucket.isCurProj = true;
          sBucket.isCur = true;
        }
        sBucket.items.push(f);
      });

      const defaultCollapsed = Boolean(state.config && state.config.collapseGroups);
      const projList = Array.from(projMap.values()).sort((a, b) => (b.isCurProj ? 1 : 0) - (a.isCurProj ? 1 : 0));

      projList.forEach((pb) => {
        const pId = `proj_${pb.key}`;
        if (!state.initCollapsedApplied && defaultCollapsed && !pb.isCurProj) {
          state.collapsedGroups.add(pId);
        }
        const isProjCollapsed = !forceExpand && state.collapsedGroups.has(pId);
        const block = document.createElement("div");
        block.className = "proj-group-block" + (isProjCollapsed ? " collapsed" : "");

        const head = document.createElement("div");
        head.className = "proj-group-head";
        head.innerHTML = `
          <div class="group-head-left">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="group-caret"><path d="m6 9 6 6 6-6"/></svg>
            <span>📁 ${esc(pb.title)}</span>
          </div>
          <span class="seg-count">${pb.count}</span>
        `;
        head.addEventListener("click", () => {
          if (state.collapsedGroups.has(pId)) state.collapsedGroups.delete(pId);
          else state.collapsedGroups.add(pId);
          block.classList.toggle("collapsed");
        });

        const bodyWrap = document.createElement("div");
        bodyWrap.className = "proj-group-body";

        const sessList = Array.from(pb.sessMap.values()).sort((a, b) => (b.isCur ? 1 : 0) - (a.isCur ? 1 : 0));
        sessList.forEach((sb) => {
          const sId = `${pId}::${sb.key}`;
          if (!state.initCollapsedApplied && defaultCollapsed && !sb.isCur) {
            state.collapsedSubGroups.add(sId);
          }
          const isSessCollapsed = !forceExpand && state.collapsedSubGroups.has(sId);
          const sBlock = document.createElement("div");
          sBlock.className = "sess-sub-block" + (isSessCollapsed ? " collapsed" : "");

          const sHead = document.createElement("div");
          sHead.className = "sess-sub-head";
          sHead.innerHTML = `
            <div class="group-head-left">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="group-caret"><path d="m6 9 6 6 6-6"/></svg>
              <span>${sb.key === "__workspace__" ? "📂" : "💬"} ${esc(sb.title)}${sb.isCur ? " (当前)" : ""}</span>
            </div>
            <span class="seg-count">${sb.items.length}</span>
          `;
          sHead.addEventListener("click", () => {
            if (state.collapsedSubGroups.has(sId)) state.collapsedSubGroups.delete(sId);
            else state.collapsedSubGroups.add(sId);
            sBlock.classList.toggle("collapsed");
          });

          const itemsWrap = document.createElement("div");
          itemsWrap.className = "sess-sub-items";
          sb.items.forEach((f) => itemsWrap.appendChild(createItemElement(f)));
          sBlock.appendChild(sHead);
          sBlock.appendChild(itemsWrap);
          bodyWrap.appendChild(sBlock);
        });

        block.appendChild(head);
        block.appendChild(bodyWrap);
        container.appendChild(block);
      });
      state.initCollapsedApplied = true;
      return;
    }

    // 2. 按文件类型分组
    if (state.category === "all" && state.groupMode === "type") {
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
        const isCollapsed = !forceExpand && state.collapsedGroups.has(catKey);
        block.className = "group-block" + (isCollapsed ? " collapsed" : "");
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
      return;
    }

    // 3. 平铺模式
    filtered.forEach((f) => container.appendChild(createItemElement(f)));
  }

  function renderAll() {
    renderProjectBar();
    updateSortButtonUI();
    updateGroupButtonUI();
    updateCompositeBarUI();
    renderCategoryBar(getBaseFiles());
    renderActiveFiltersBar();
    renderList();
  }

  // ==================== 完整设置弹窗 (对齐 DSH + 扩展 Antigravity 专属管理) ====================
  async function openSettingsModal() {
    const modal = el("settingsModal");
    const body = el("settingsBody");
    if (!modal || !body) return;
    modal.classList.remove("hidden");
    body.innerHTML = '<div class="empty-box">正在加载设置...</div>';

    try {
      const res = await sidecarFetch("/api/settings");
      const data = await res.json();
      if (data && data.ok && data.settings) {
        state.config = data.settings;
        state.archiveRoot = data.archiveRoot || state.archiveRoot;
        state.settingsPaths = data.paths || state.settingsPaths;
        state.apps = data.apps || state.apps;
        state.capabilities = data.capabilities || state.capabilities;
      }
    } catch (e) {}

    renderSettingsForm();
  }

  function closeSettingsModal() {
    el("settingsModal").classList.add("hidden");
  }

  function renderSettingsForm() {
    const body = el("settingsBody");
    const cfg = state.config || {};
    const caps = state.capabilities || {};
    const paths = state.settingsPaths || {};
    const watched = cfg.watchedDirs || [];
    const customApps = cfg.customApps || [];
    const extDefs = cfg.extDefaults || {};
    const appsById = {};
    (state.apps || []).forEach((a) => (appsById[a.id] = a.name));

    body.innerHTML = `
      <div class="settings-sec">
        <div class="settings-sec-title">界面外观</div>
        <div class="settings-row">
          <label for="setTheme">界面主题（实时生效）</label>
          <select id="setTheme" class="settings-select">
            <option value="host" ${cfg.appearanceTheme === "host" ? "selected" : ""}>跟随宿主 (Host)</option>
            <option value="light" ${cfg.appearanceTheme === "light" ? "selected" : ""}>浅色 (Light)</option>
            <option value="dark" ${cfg.appearanceTheme === "dark" ? "selected" : ""}>深色 (Dark)</option>
            <option value="system" ${cfg.appearanceTheme === "system" ? "selected" : ""}>跟随系统 (System)</option>
          </select>
        </div>
      </div>

      <div class="settings-sec">
        <div class="settings-sec-title">交互与列表视图</div>
        <div class="settings-row">
          <label for="setClickAction">默认单击打开方式</label>
          <select id="setClickAction" class="settings-select">
            <option value="sidecar" ${cfg.defaultClickAction !== "preview" && cfg.defaultClickAction !== "system" ? "selected" : ""}>Antigravity 右侧边栏打开 (推荐)</option>
            <option value="preview" ${cfg.defaultClickAction === "preview" ? "selected" : ""}>面板内增强预览</option>
            <option value="system" ${cfg.defaultClickAction === "system" ? "selected" : ""}>电脑默认软件直接打开</option>
          </select>
        </div>
        <div class="settings-row">
          <label for="setDefaultScope">默认隔离范围</label>
          <select id="setDefaultScope" class="settings-select">
            <option value="auto" ${cfg.defaultScope === "auto" ? "selected" : ""}>自动识别当前项目/对话</option>
            <option value="current" ${cfg.defaultScope === "current" ? "selected" : ""}>始终当前对话</option>
            <option value="all" ${cfg.defaultScope === "all" ? "selected" : ""}>全局全部文件</option>
          </select>
        </div>
        <div class="settings-row">
          <label for="setCollapseGroups">「按项目」分组时非当前项目默认折叠</label>
          <input id="setCollapseGroups" type="checkbox" ${cfg.collapseGroups !== false ? "checked" : ""} />
        </div>
        <div class="settings-row">
          <label for="setMaxRows">单列表最大行数 (100 - 2000)</label>
          <input id="setMaxRows" type="number" min="100" max="2000" step="50" class="settings-input" style="width:90px;" value="${esc(cfg.maxRows || 800)}" />
        </div>
      </div>

      <div class="settings-sec">
        <div class="settings-sec-title">后台自动刷新与防卡顿限流</div>
        <div class="settings-row">
          <label for="setAutoRefresh">启用后台定时刷新文件索引</label>
          <input id="setAutoRefresh" type="checkbox" ${cfg.autoRefresh !== false ? "checked" : ""} />
        </div>
        <div class="settings-row">
          <label for="setRefreshSec">自动刷新间隔秒数 (5 - 300s，建议 60s)</label>
          <input id="setRefreshSec" type="number" min="5" max="300" class="settings-input" style="width:90px;" value="${esc(cfg.refreshSeconds || 60)}" />
        </div>
      </div>

      <div class="settings-sec">
        <div class="settings-sec-title" style="display:flex;justify-content:space-between;align-items:center;">
          <span>PDF / Office 逐页渲染引擎</span>
          <span style="display:flex;gap:4px;">
            <span class="cap-pill ${caps.pdfPages ? "ready" : ""}">${caps.pdfPages ? "✓ PDF 分页可用" : "无 pdftoppm"}</span>
            <span class="cap-pill ${caps.officePages ? "ready" : ""}">${caps.officePages ? "✓ Office 转 PDF 可用" : "无 LibreOffice (自动结构化阅读)"}</span>
          </span>
        </div>
        <div class="settings-row">
          <label for="setPdfPages">PDF 最大渲染页数 (1 - 40)</label>
          <input id="setPdfPages" type="number" min="1" max="40" class="settings-input" style="width:90px;" value="${esc(cfg.pdfMaxPages || 20)}" />
        </div>
        <div class="settings-row">
          <label for="setPdfDpi">页面渲染清晰度 DPI (80 - 160)</label>
          <input id="setPdfDpi" type="number" min="80" max="160" step="5" class="settings-input" style="width:90px;" value="${esc(cfg.pdfDpi || 110)}" />
        </div>
      </div>

      <div class="settings-sec">
        <div class="settings-sec-title">归档目录配置（按日期 YYYY-MM-DD 子目录 + 防重名覆盖）</div>
        <div style="display:flex;gap:6px;">
          <input id="setArchiveDir" type="text" class="settings-input wide" placeholder="留空使用默认目录" value="${esc(cfg.archiveDir || "")}" />
          <button id="resetArchiveDirBtn" type="button" class="btn-secondary" style="white-space:nowrap;">恢复默认</button>
        </div>
        <div class="settings-path-note">当前生效归档目录：${esc(state.archiveRoot || paths.defaultArchiveDir || "")}</div>
      </div>

      <div class="settings-sec">
        <div class="settings-sec-title">额外监控目录 (${watched.length})</div>
        <div class="settings-chip-list">
          ${watched.map((d) => `
            <div class="settings-chip-row">
              <span class="settings-path-note">${esc(d)}</span>
              <button type="button" class="doc-mini-btn" data-remove-dir="${esc(d)}">移除</button>
            </div>`).join("") || `<div class="settings-path-note">暂无自定义监控目录</div>`}
        </div>
        <div style="display:flex;gap:6px;margin-top:4px;">
          <input id="addWatchDirInput" type="text" class="settings-input wide" placeholder="输入文件夹绝对路径，如 D:\\Documents" />
          <button id="addWatchDirBtn" type="button" class="btn-secondary" style="white-space:nowrap;">添加目录</button>
        </div>
      </div>

      <div class="settings-sec">
        <div class="settings-sec-title">自定义应用与后缀默认 (${customApps.length} 应用 / ${Object.keys(extDefs).length} 后缀)</div>
        <div class="settings-chip-list">
          ${customApps.map((a) => `
            <div class="settings-chip-row">
              <span>${esc(a.name)} <span class="settings-path-note">(${esc(a.exe)})</span></span>
              <button type="button" class="doc-mini-btn" data-remove-app="${esc(a.name)}">移除</button>
            </div>`).join("")}
        </div>
        <div style="display:flex;gap:5px;margin-top:4px;">
          <input id="addAppNameInput" type="text" class="settings-input" style="width:95px;" placeholder="应用名称" />
          <input id="addAppExeInput" type="text" class="settings-input wide" placeholder="程序 .exe 绝对路径" />
          <button id="addAppBtn" type="button" class="btn-secondary" style="white-space:nowrap;">添加</button>
        </div>
        ${Object.keys(extDefs).length ? `
          <div class="settings-chip-list" style="margin-top:6px;">
            ${Object.entries(extDefs).map(([ext, aid]) => `
              <div class="settings-chip-row">
                <span><strong>${esc(ext)}</strong> → ${esc(appsById[aid] || aid)}</span>
                <button type="button" class="doc-mini-btn" data-clear-ext="${esc(ext)}">还原系统默认</button>
              </div>`).join("")}
          </div>` : ""}
      </div>

      <div class="settings-sec">
        <div class="settings-sec-title">本地索引与数据文件位置</div>
        <div class="settings-path-note">配置文件：${esc(paths.config || "")}</div>
        <div class="settings-path-note">归档索引：${esc(paths.archiveIndex || "")}</div>
        <div class="settings-path-note">删除墓碑：${esc(paths.deletedIndex || "")}</div>
        <div class="settings-path-note">发送索引：${esc(paths.sentIndex || "")}</div>
        <div class="settings-path-note">页面缓存：${esc(paths.rendersDir || "")}</div>
      </div>
    `;

    // 主题实时预览，无需点击保存即可即时看到效果
    el("setTheme").addEventListener("change", (e) => applyThemeMode(e.target.value));
    el("resetArchiveDirBtn").addEventListener("click", () => {
      el("setArchiveDir").value = "";
      showToast("已清空自定义归档目录，点“保存设置”应用默认路径");
    });

    body.querySelectorAll("[data-remove-dir]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const d = btn.getAttribute("data-remove-dir");
        await sidecarFetch("/api/config?op=remove_watched_dir&dir=" + encodeURIComponent(d));
        await openSettingsModal();
        fetchState(false);
      });
    });

    el("addWatchDirBtn").addEventListener("click", async () => {
      const val = (el("addWatchDirInput").value || "").trim();
      if (!val) return;
      const r = await sidecarFetch("/api/config?op=add_watched_dir&dir=" + encodeURIComponent(val));
      const d = await r.json();
      if (!d.ok) {
        showToast("添加失败: " + (d.error || "目录不存在"));
        return;
      }
      showToast("已添加监控目录");
      await openSettingsModal();
      fetchState(true);
    });

    body.querySelectorAll("[data-remove-app]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const name = btn.getAttribute("data-remove-app");
        await sidecarFetch("/api/config?op=remove_custom_app&name=" + encodeURIComponent(name));
        await openSettingsModal();
        fetchState(false);
      });
    });

    el("addAppBtn").addEventListener("click", async () => {
      const name = (el("addAppNameInput").value || "").trim();
      const exe = (el("addAppExeInput").value || "").trim();
      if (!name || !exe) return;
      const r = await sidecarFetch(
        "/api/config?op=add_custom_app&name=" + encodeURIComponent(name) + "&exe=" + encodeURIComponent(exe)
      );
      const d = await r.json();
      if (!d.ok) {
        showToast("添加失败: " + (d.error || "可执行文件不存在"));
        return;
      }
      showToast("已添加自定义应用");
      await openSettingsModal();
      fetchState(false);
    });

    body.querySelectorAll("[data-clear-ext]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const ext = btn.getAttribute("data-clear-ext");
        await sidecarFetch("/api/config?op=set_ext_default&ext=" + encodeURIComponent(ext) + "&appId=default");
        await openSettingsModal();
        fetchState(false);
      });
    });
  }

  async function saveSettingsFromModal() {
    const patch = {
      appearanceTheme: el("setTheme").value,
      defaultClickAction: el("setClickAction").value,
      defaultScope: el("setDefaultScope").value,
      collapseGroups: Boolean(el("setCollapseGroups").checked),
      maxRows: parseInt(el("setMaxRows").value || "800", 10),
      autoRefresh: Boolean(el("setAutoRefresh").checked),
      refreshSeconds: parseInt(el("setRefreshSec").value || "60", 10),
      pdfMaxPages: parseInt(el("setPdfPages").value || "20", 10),
      pdfDpi: parseInt(el("setPdfDpi").value || "110", 10),
      archiveDir: (el("setArchiveDir").value || "").trim(),
    };
    try {
      const res = await postJson("/api/settings", { settings: patch });
      const data = await res.json();
      if (data && data.ok && data.settings) {
        state.config = data.settings;
        state.archiveRoot = data.archiveRoot || state.archiveRoot;
        applyThemeMode(state.config.appearanceTheme || "host");
        scheduleAutoRefresh();
        closeSettingsModal();
        showToast("设置已保存");
        await fetchState(true);
      } else {
        showToast("保存失败");
      }
    } catch (err) {
      showToast("保存失败: " + err.message);
    }
  }

  // ==================== 全局事件绑定 ====================
  el("docBackBtn").addEventListener("click", closeInternalDocView);
  el("docMenuBtn").addEventListener("click", (e) => {
    e.stopPropagation();
    el("docMenuDrop").classList.toggle("hidden");
  });

  if (el("filterBtn")) {
    el("filterBtn").addEventListener("click", (e) => {
      e.stopPropagation();
      if (state.filterPopoverOpen) closeFilterPopover();
      else openFilterPopover();
    });
  }

  if (el("archivedToggleBtn")) {
    el("archivedToggleBtn").addEventListener("click", () => {
      switchTab(state.tab === "archived" ? "session" : "archived");
    });
  }

  if (el("settingsBtn")) el("settingsBtn").addEventListener("click", openSettingsModal);
  if (el("settingsCloseBtn")) el("settingsCloseBtn").addEventListener("click", closeSettingsModal);
  if (el("settingsCancelBtn")) el("settingsCancelBtn").addEventListener("click", () => {
    applyThemeMode((state.config && state.config.appearanceTheme) || "host");
    closeSettingsModal();
  });
  if (el("settingsSaveBtn")) el("settingsSaveBtn").addEventListener("click", saveSettingsFromModal);

  if (el("delModalCloseBtn")) el("delModalCloseBtn").addEventListener("click", closeDeleteConfirmModal);
  if (el("delCancelBtn")) el("delCancelBtn").addEventListener("click", closeDeleteConfirmModal);
  if (el("delConfirmBtn")) el("delConfirmBtn").addEventListener("click", confirmPermanentDelete);

  document.addEventListener("click", (e) => {
    if (!e.target.closest(".open-with-wrap") && !e.target.closest("#globalContextMenu")) {
      el("docMenuDrop").classList.add("hidden");
      closeContextMenu();
    }
    if (!e.target.closest("#scopeWrap")) {
      if (state.scopeMenuOpen) {
        state.scopeMenuOpen = false;
        const dd = el("scopeDropdown");
        if (dd) dd.classList.add("hidden");
      }
    }
    if (!e.target.closest("#filterBtn") && !e.target.closest("#filterPopover")) {
      if (state.filterPopoverOpen) closeFilterPopover();
    }
  });

  document.addEventListener("keydown", (e) => {
    const delModalOpen = !el("deleteConfirmModal").classList.contains("hidden");
    const setModalOpen = !el("settingsModal").classList.contains("hidden");
    const menuEl = el("globalContextMenu");
    const menuOpen = menuEl && !menuEl.classList.contains("hidden");

    if (e.key === "Escape") {
      if (delModalOpen) { closeDeleteConfirmModal(); return; }
      if (setModalOpen) { applyThemeMode((state.config && state.config.appearanceTheme) || "host"); closeSettingsModal(); return; }
      if (menuOpen) { closeContextMenu(); return; }
      if (state.filterPopoverOpen) { closeFilterPopover(); return; }
      if (state.scopeMenuOpen) {
        state.scopeMenuOpen = false;
        const dd = el("scopeDropdown");
        if (dd) dd.classList.add("hidden");
        return;
      }
      if (state.activeInternalDoc) { closeInternalDocView(); return; }
    }

    if (menuOpen) {
      const items = Array.from(menuEl.querySelectorAll(".menu-item"));
      if (!items.length) return;
      if (e.key === "ArrowDown") {
        e.preventDefault();
        state.contextMenuFocusIdx = (state.contextMenuFocusIdx + 1) % items.length;
        items.forEach((it, idx) => it.classList.toggle("focused", idx === state.contextMenuFocusIdx));
        items[state.contextMenuFocusIdx].scrollIntoView({ block: "nearest" });
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        state.contextMenuFocusIdx = (state.contextMenuFocusIdx - 1 + items.length) % items.length;
        items.forEach((it, idx) => it.classList.toggle("focused", idx === state.contextMenuFocusIdx));
        items[state.contextMenuFocusIdx].scrollIntoView({ block: "nearest" });
      } else if (e.key === "Enter" && state.contextMenuFocusIdx >= 0 && items[state.contextMenuFocusIdx]) {
        e.preventDefault();
        items[state.contextMenuFocusIdx].click();
      }
      return;
    }

    if (state.activeInternalDoc && !delModalOpen && !setModalOpen) {
      if (e.key === "ArrowLeft") stepInternalPreview(-1);
      else if (e.key === "ArrowRight") stepInternalPreview(1);
    }
  });

  if (el("scopeTrigger")) {
    el("scopeTrigger").addEventListener("click", (e) => {
      e.stopPropagation();
      closeContextMenu();
      closeFilterPopover();
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
    if (!state.selectMode) state.selectedPaths.clear();
    updateCompositeBarUI();
    renderList();
  });

  el("selAllBtn").addEventListener("click", () => {
    const visible = getFilteredFiles();
    const allSelected = visible.length > 0 && visible.every((f) => state.selectedPaths.has(f.path));
    if (allSelected) state.selectedPaths.clear();
    else visible.forEach((f) => state.selectedPaths.add(f.path));
    updateCompositeBarUI();
    renderList();
  });

  el("batchPinBtn").addEventListener("click", () => executeBatchAction("pin", Array.from(state.selectedPaths)));
  el("batchArchiveBtn").addEventListener("click", () => executeBatchAction("archive", Array.from(state.selectedPaths)));
  if (el("batchForgetBtn")) {
    el("batchForgetBtn").addEventListener("click", () => {
      const sel = Array.from(state.selectedPaths);
      state.selectMode = false;
      state.selectedPaths.clear();
      updateCompositeBarUI();
      forgetPathsAction(sel);
    });
  }
  if (el("batchCopyRefBtn")) {
    el("batchCopyRefBtn").addEventListener("click", async () => {
      const files = Array.from(state.selectedPaths).map(findFileByPath).filter(Boolean);
      const ok = await copyFileReferences(files);
      if (ok) {
        state.selectMode = false;
        state.selectedPaths.clear();
        updateCompositeBarUI();
        renderList();
      }
    });
  }

  el("sortTimeBtn").addEventListener("click", () => {
    const order = ["time_desc", "time_asc", "name", "type"];
    const names = { time_desc: "时间从新到旧", time_asc: "时间从早到晚", name: "文件名 A-Z", type: "文件类型" };
    const next = order[(order.indexOf(state.sortBy) + 1) % order.length];
    state.sortBy = next;
    showToast("排序方式：" + names[next]);
    updateSortButtonUI();
    renderList();
  });

  el("groupToggleBtn").addEventListener("click", () => {
    const order = ["type", "project", "none"];
    const names = { type: "按文件类型分组", project: "按项目 → 会话分组", none: "平铺列表" };
    state.groupMode = order[(order.indexOf(state.groupMode) + 1) % order.length];
    state.initCollapsedApplied = false;
    showToast("分组视图：" + names[state.groupMode]);
    renderAll();
  });

  el("searchInput").addEventListener("input", (e) => {
    state.search = (e.target.value || "").trim().toLowerCase();
    renderAll();
  });

  el("refreshBtn").addEventListener("click", async () => {
    await fetchState(true);
    showToast("已强制刷新");
  });

  // ==================== 状态拉取、防竞态与实时卡片长轮询 ====================
  function scheduleAutoRefresh() {
    if (autoRefreshTimer) {
      clearInterval(autoRefreshTimer);
      autoRefreshTimer = null;
    }
    const cfg = state.config || {};
    if (cfg.autoRefresh === false) return;
    const rawSec = parseInt(cfg.refreshSeconds || "60", 10) || 60;
    const sec = Math.max(5, Math.min(300, rawSec === 60 ? 6 : rawSec));
    autoRefreshTimer = setInterval(() => {
      if (!state.contextMenuFile && !state.selectMode && !state.scopeMenuOpen && !state.filterPopoverOpen && isRealSidecarVisible()) {
        fetchState(false);
      }
    }, sec * 1000);
  }

  async function fetchState(manual) {
    if (stateAbortCtrl) {
      try { stateAbortCtrl.abort(); } catch (e) {}
    }
    stateAbortCtrl = new AbortController();
    const mySignal = stateAbortCtrl.signal;

    try {
      const convId = getConversationId();
      const wsList = await getWorkspaceUrisList();
      const wsSig = JSON.stringify(wsList || []);
      if (convId && convId !== state.lastConvId) {
        state.lastConvId = convId;
        state.userChoseProject = false;
        state.appliedDefaultScope = false;
      } else if (wsSig !== state.lastWorkspaceSig) {
        state.lastWorkspaceSig = wsSig;
        state.userChoseProject = false;
      }

      const url =
        "/api/state?client=sidecar&ver=" +
        APP_VER +
        "&visible=" +
        (isRealSidecarVisible() ? "1" : "0") +
        "&fresh=" +
        (manual ? "1" : "0") +
        "&conversationId=" +
        encodeURIComponent(convId) +
        "&workspaceUris=" +
        encodeURIComponent(wsSig);
      const res = await sidecarFetch(url, { signal: mySignal });
      const data = await res.json();
      if (!data.ok) return;
      LAST_AUTO_SYNC_AT = Date.now();
      if (data.codeStale && !state.notifiedCodeStale) {
        state.notifiedCodeStale = true;
        showToast("检测到插件后端已升级，请停用再启用 File Launcher 或重载窗口以加载新版");
      }

      state.conversationId = data.conversationId || state.conversationId || convId;
      state.realProjects = data.realProjects || [];
      state.conversations = data.conversations || [];
      state.localDirs = data.localDirs || [];
      state.projects = data.projects || [];
      state.apps = data.apps || [];
      if (data.config) {
        const prevSec = state.config && state.config.refreshSeconds;
        const prevAuto = state.config && state.config.autoRefresh;
        state.config = data.config;
        if (state.config.appearanceTheme) applyThemeMode(state.config.appearanceTheme);
        if (prevSec !== state.config.refreshSeconds || prevAuto !== state.config.autoRefresh) {
          scheduleAutoRefresh();
        }
      }
      state.archiveRoot = data.archiveRoot || state.archiveRoot;
      state.settingsPaths = data.settingsPaths || state.settingsPaths;
      state.capabilities = data.capabilities || state.capabilities;
      state.sessionFiles = data.sessionFiles || [];
      state.sentFiles = data.sentFiles || [];
      state.pinnedFiles = data.pinnedFiles || [];
      state.archivedFiles = data.archivedFiles || [];
      state.recentFiles = data.recentFiles || [];

      const validScope = (id) =>
        id === "all" ||
        id === "scope:conv" ||
        state.realProjects.some((p) => p.id === id) ||
        state.conversations.some((c) => c.id === id) ||
        state.localDirs.some((d) => d.id === id) ||
        state.projects.some((p) => p.id === id);

      const defaultScope = data.activeScopeId || data.activeProjectId || "scope:conv";
      if (!state.userChoseProject) {
        const prefScope = (state.config && state.config.defaultScope) || "auto";
        if (prefScope === "all") state.activeProjectId = "all";
        else if (prefScope === "current") state.activeProjectId = "scope:conv";
        else state.activeProjectId = defaultScope;
      } else if (state.activeProjectId && !validScope(state.activeProjectId)) {
        state.activeProjectId = defaultScope;
      }

      if (data.pendingInternalOpen && data.pendingInternalOpen.file) {
        openInSidePane(data.pendingInternalOpen.file);
      }

      renderAll();
    } catch (err) {
      if (err && err.name === "AbortError") return;
      console.error("Failed to fetch state:", err);
    }
  }

  async function startPollLoop() {
    while (true) {
      try {
        pollAbortCtrl = new AbortController();
        const visFlag = updateVisibilityTimestamp() ? "1" : "0";
        const myConvId = getConversationId();
        const res = await sidecarFetch(
          "/api/poll-open?wait=15&visible=" + visFlag + "&conversationId=" + encodeURIComponent(myConvId),
          { signal: pollAbortCtrl.signal }
        );
        const data = await res.json();
        if (data && data.ok && Array.isArray(data.queue) && data.queue.length > 0 && isRealSidecarVisible()) {
          const ackIds = [];
          for (const action of data.queue) {
            if (action.conversationId && myConvId && action.conversationId !== myConvId) continue;
            if (action.type === "open" && action.file) {
              await openInSidePane(action.file);
            }
            if (action.id) ackIds.push(action.id);
          }
          if (ackIds.length) {
            sidecarFetch("/api/ack?ids=" + encodeURIComponent(ackIds.join(","))).catch(() => {});
          }
        }
      } catch (e) {
        if (e && e.name === "AbortError") continue;
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
      try { pollAbortCtrl.abort(); } catch (e) {}
    }
    if (vis) fetchState(false);
  }

  document.addEventListener("visibilitychange", handleVisibilityOrResize);
  window.addEventListener("resize", handleVisibilityOrResize);
  document.addEventListener("pointerenter", () => {
    if (
      isRealSidecarVisible() &&
      Date.now() - LAST_AUTO_SYNC_AT > 2500 &&
      !state.contextMenuFile &&
      !state.selectMode &&
      !state.scopeMenuOpen &&
      !state.filterPopoverOpen
    ) {
      fetchState(false);
    }
  });
  window.addEventListener("focus", () => {
    if (
      isRealSidecarVisible() &&
      Date.now() - LAST_AUTO_SYNC_AT > 1500 &&
      !state.contextMenuFile &&
      !state.selectMode &&
      !state.scopeMenuOpen &&
      !state.filterPopoverOpen
    ) {
      fetchState(false);
    }
  });

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

  if (el("fileListContainer")) {
    startComfortLoader(el("fileListContainer"), "init", 2200);
  }
  fetchState(false).then(() => scheduleAutoRefresh());
  startPollLoop();
  scheduleAutoRefresh();
})();
