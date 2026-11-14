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

  window.addEventListener("message", (event) => {
    if (event.data && event.data.type === "theme-change") {
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
    // tab: "session" (AI产出) | "sent" (单独隔离：我发送的文件) | "recent" (最近项目)
    tab: "session",
    category: "all",
    groupByType: true,
    // sortBy: "default" | "time_desc" (最新优先) | "time_asc" (最早优先)
    sortBy: "time_desc",
    search: "",
    sessionFiles: [],
    sentFiles: [],
    recentFiles: [],
    openMenuPath: null,
    collapsedGroups: new Set(),
    activeInternalDoc: null,
  };

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
    showToast._t = setTimeout(() => t.classList.add("hidden"), 2000);
  }

  function getConversationId() {
    if (window.sidecar && window.sidecar.conversationId) {
      return window.sidecar.conversationId;
    }
    const params = new URLSearchParams(window.location.search);
    return params.get("conversationId") || "";
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

  async function openInsideAntigravity(f) {
    if (!f || !f.path) return;
    const ext = (f.ext || "").toLowerCase();

    if (
      NATIVE_FILEVIEW_EXTS.has(ext) &&
      window.sidecar &&
      window.sidecar.ui &&
      typeof window.sidecar.ui.toggleAuxPane === "function" &&
      f.fileUri
    ) {
      try {
        window.sidecar.ui.toggleAuxPane({ tabType: "fileView", uri: f.fileUri });
        showToast("已在右侧分栏打开 " + f.name);
        return;
      } catch (e) {
        console.warn("toggleAuxPane fallback:", e);
      }
    }

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
    el("tabRecent").classList.toggle("active", nextTab === "recent");
    renderAll();
  }

  function updateSortButtonUI() {
    const btn = el("sortTimeBtn");
    const label = el("sortTimeLabel");
    if (!btn || !label) return;
    if (state.sortBy === "time_desc") {
      btn.classList.add("active");
      label.textContent = "按时间: 最新↓";
    } else if (state.sortBy === "time_asc") {
      btn.classList.add("active");
      label.textContent = "按时间: 最早↑";
    } else {
      btn.classList.remove("active");
      label.textContent = "按时间排序";
    }
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
  });

  el("tabSession").addEventListener("click", () => switchTab("session"));
  el("tabSent").addEventListener("click", () => switchTab("sent"));
  el("tabRecent").addEventListener("click", () => switchTab("recent"));

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

  function getBaseFiles() {
    if (state.tab === "sent") return state.sentFiles || [];
    if (state.tab === "recent") return state.recentFiles || [];
    return state.sessionFiles || [];
  }

  function applySort(files) {
    const list = [...files];
    if (state.sortBy === "time_desc") {
      list.sort((a, b) => (b.mtimeMs || 0) - (a.mtimeMs || 0));
    } else if (state.sortBy === "time_asc") {
      list.sort((a, b) => (a.mtimeMs || 0) - (b.mtimeMs || 0));
    }
    return list;
  }

  function renderCategoryBar(baseFiles) {
    const strip = el("catStrip");
    const counts = { all: 0 };
    baseFiles.forEach((f) => {
      const cat = f.category || "other";
      counts[cat] = (counts[cat] || 0) + 1;
      if (state.tab === "sent" || f.isReadable) counts.all += 1;
    });

    const allLabel = state.tab === "sent" ? "全部我发送的" : "全部文档";
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

    if (state.tab !== "sent") {
      const div = document.createElement("span");
      div.className = "cat-divider";
      strip.appendChild(div);

      const sentBtn = document.createElement("button");
      sentBtn.className = "cat-pill sent-isolated";
      sentBtn.title = "单独查看我发送给 Antigravity 的文件（与产出文档完全隔离）";
      sentBtn.innerHTML = `<span>我发送的文件</span><span class="cat-num">${(state.sentFiles || []).length}</span>`;
      sentBtn.addEventListener("click", () => switchTab("sent"));
      strip.appendChild(sentBtn);
    }
  }

  function createItemElement(f) {
    const item = document.createElement("div");
    item.className = "codex-item";
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

    item.innerHTML = `
      <div class="item-main" data-act="default-open" title="点击直接用默认程序打开">
        <span class="ext-pill ${esc(f.category || "other")}">${esc(extLabel)}</span>
        <div class="item-text">
          <div class="item-name">${esc(f.name)}</div>
          <div class="item-sub">${esc(subParts.join(" · "))}</div>
        </div>
      </div>
      <div class="open-with-wrap">
        <button class="open-with-btn" data-act="toggle-menu">
          <span>打开方式</span>
          <svg viewBox="0 0 24 24" class="svg-caret"><path d="m6 9 6 6 6-6"/></svg>
        </button>
        <div class="dropdown-menu ${isMenuOpen ? "" : "hidden"}">
          <button class="menu-item" data-mode="antigravity_internal">
            <span>Antigravity 内部打开</span>
            <span class="menu-tag">内置</span>
          </button>
          <div class="menu-divider"></div>
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

    item.querySelector('[data-act="default-open"]').addEventListener("click", () => {
      triggerExternalOpen(f.path, "default", "");
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
        if (mode === "antigravity_internal") {
          openInsideAntigravity(f);
        } else {
          triggerExternalOpen(f.path, mode, appId);
        }
      });
    });

    return item;
  }

  function renderList() {
    const container = el("fileListContainer");
    const baseFiles = getBaseFiles();

    const filtered = applySort(
      baseFiles.filter((f) => {
        if (state.search) {
          const hay = ((f.name || "") + " " + (f.path || "") + " " + (f.categoryLabel || "")).toLowerCase();
          if (!hay.includes(state.search)) return false;
        } else if (state.category === "all") {
          if (state.tab !== "sent" && !f.isReadable) return false;
        } else {
          if ((f.category || "other") !== state.category) return false;
        }
        return true;
      })
    );

    const readableSessionCount = (state.sessionFiles || []).filter((f) => f.isReadable).length;
    const sentCount = (state.sentFiles || []).length;
    const readableRecentCount = (state.recentFiles || []).filter((f) => f.isReadable).length;
    el("countSession").textContent = String(readableSessionCount || (state.sessionFiles || []).length);
    el("countSent").textContent = String(sentCount);
    el("countRecent").textContent = String(readableRecentCount || (state.recentFiles || []).length);

    if (!filtered.length) {
      if (state.tab === "sent") {
        container.innerHTML = `<div class="empty-box">暂无您发送的文件（您在聊天中发送或上传的图片、文档会单独隔离保存在此分类）</div>`;
      } else {
        container.innerHTML = `<div class="empty-box">该分类下暂无文件</div>`;
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
    updateSortButtonUI();
    renderCategoryBar(getBaseFiles());
    renderList();
  }

  async function fetchState(manual) {
    try {
      const convId = getConversationId();
      const res = await sidecarFetch("/api/state?client=sidecar&conversationId=" + encodeURIComponent(convId));
      const data = await res.json();
      if (!data.ok) return;

      state.sessionFiles = data.sessionFiles || [];
      state.sentFiles = data.sentFiles || [];
      state.recentFiles = data.recentFiles || [];

      if (!manual && state.sessionFiles.length === 0 && state.recentFiles.length > 0 && state.tab === "session") {
        state.sessionFiles = state.recentFiles.slice(0, 20);
      }

      if (data.pendingInternalOpen && data.pendingInternalOpen.file) {
        openInsideAntigravity(data.pendingInternalOpen.file);
      }

      renderAll();
    } catch (err) {
      console.error("Failed to fetch state:", err);
    }
  }

  async function pollPendingOpen() {
    try {
      const res = await sidecarFetch("/api/poll-open");
      const data = await res.json();
      if (data && data.ok && data.pendingInternalOpen && data.pendingInternalOpen.file) {
        openInsideAntigravity(data.pendingInternalOpen.file);
      }
    } catch (e) {}
  }

  if (window.sidecar && typeof window.sidecar.onWorkspaceChange === "function") {
    window.sidecar.onWorkspaceChange(() => {
      fetchState(false);
    });
  }

  fetchState(false);
  setInterval(pollPendingOpen, 500);
  setInterval(() => {
    if (!state.openMenuPath) fetchState(false);
  }, 2500);
})();
