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
    // tab: "session" (本次产出) | "sent" (我发送的文件) | "pinned" (★收藏防压缩) | "archived" (已归档) | "recent" (最近项目)
    tab: "session",
    category: "all",
    groupByType: true,
    sortBy: "time_desc",
    selectMode: false,
    selectedPaths: new Set(),
    search: "",
    sessionFiles: [],
    sentFiles: [],
    pinnedFiles: [],
    archivedFiles: [],
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
    showToast._t = setTimeout(() => t.classList.add("hidden"), 2400);
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
        showToast(`📦 已归档 ${paths.length} 个文件至 D:\\projects\\Archived_Docs`);
      } else if (op === "unarchive") {
        showToast("已移出归档列表");
      } else if (op === "copy_chat_refs") {
        try {
          if (navigator.clipboard && data.chatText) {
            await navigator.clipboard.writeText(data.chatText);
          }
        } catch (e) {}
        showToast(`💬 已复制 ${paths.length} 个文件的 @引用 到剪贴板，直接在输入框 Ctrl+V 即可发送`);
      }
      await fetchState(true);
    } catch (err) {
      showToast("请求失败: " + err.message);
    }
  }

  async function openInsideAntigravity(f, fromPoll) {
    if (!f || !f.path) return;
    const ext = (f.ext || "").toLowerCase();

    const targetUri = f.openUri || (NATIVE_FILEVIEW_EXTS.has(ext) ? f.fileUri : "");
    if (
      targetUri &&
      window.sidecar &&
      window.sidecar.ui &&
      typeof window.sidecar.ui.toggleAuxPane === "function"
    ) {
      try {
        window.sidecar.ui.toggleAuxPane({ tabType: "fileView", uri: targetUri });
        showToast("已在右侧分栏打开 " + f.name);
        if (NATIVE_FILEVIEW_EXTS.has(ext) || fromPoll) {
          return;
        }
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
  });

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
    executeBatchAction("copy_chat_refs", Array.from(state.selectedPaths));
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

  function getBaseFiles() {
    if (state.tab === "sent") return state.sentFiles || [];
    if (state.tab === "pinned") return state.pinnedFiles || [];
    if (state.tab === "archived") return state.archivedFiles || [];
    if (state.tab === "recent") return state.recentFiles || [];
    return state.sessionFiles || [];
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

    const badgesHtml =
      (f.isPinned ? `<span class="pin-badge" title="防上下文压缩保护中">★防压缩</span>` : "") +
      (f.isArchived ? `<span class="arch-badge">已归档</span>` : "");

    item.innerHTML = `
      <div class="item-main" data-act="main-click" title="${state.selectMode ? "点击勾选/取消勾选" : "点击直接用默认程序打开"}">
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
          <button class="menu-item" data-mode="antigravity_internal">
            <span>Antigravity 内部打开</span>
            <span class="menu-tag">侧边栏</span>
          </button>
          <div class="menu-divider"></div>
          <div class="menu-section-label">文件管理与上下文</div>
          <button class="menu-item" data-mode="pin_toggle">
            <span>${f.isPinned ? "★ 取消收藏保留" : "★ 收藏保留 (防压缩)"}</span>
          </button>
          <button class="menu-item" data-mode="copy_chat">
            <span>💬 加入对话框 (@引用)</span>
          </button>
          <button class="menu-item" data-mode="archive_toggle">
            <span>${f.isArchived ? "📦 移出归档" : "📦 归档保存"}</span>
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
        triggerExternalOpen(f.path, "default", "");
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
        if (mode === "antigravity_internal") {
          openInsideAntigravity(f, false);
        } else if (mode === "pin_toggle") {
          executeBatchAction(f.isPinned ? "unpin" : "pin", [f.path]);
        } else if (mode === "copy_chat") {
          executeBatchAction("copy_chat_refs", [f.path]);
        } else if (mode === "archive_toggle") {
          executeBatchAction(f.isArchived ? "unarchive" : "archive", [f.path]);
        } else {
          triggerExternalOpen(f.path, mode, appId);
        }
      });
    });

    return item;
  }

  function renderList() {
    const container = el("fileListContainer");
    const filtered = getFilteredFiles();

    const readableSessionCount = (state.sessionFiles || []).filter((f) => f.isReadable).length;
    const sentCount = (state.sentFiles || []).length;
    const pinnedCount = (state.pinnedFiles || []).length;
    const readableRecentCount = (state.recentFiles || []).filter((f) => f.isReadable).length;
    el("countSession").textContent = String(readableSessionCount || (state.sessionFiles || []).length);
    el("countSent").textContent = String(sentCount);
    el("countPinned").textContent = String(pinnedCount);
    el("countRecent").textContent = String(readableRecentCount || (state.recentFiles || []).length);

    if (!filtered.length) {
      if (state.tab === "sent") {
        container.innerHTML = `<div class="empty-box">暂无您发送的文件（您在聊天中发送或上传的图片、文档会单独隔离保存在此分类）</div>`;
      } else if (state.tab === "pinned") {
        container.innerHTML = `<div class="empty-box">暂无收藏保留的文件（点击文件左侧 ☆ 或通过「选择 -> 收藏」可将重要文件永久保留，防止上下文压缩丢失）</div>`;
      } else if (state.tab === "archived") {
        container.innerHTML = `<div class="empty-box">暂无已归档的文件（可通过「选择 -> 归档」将成品文档归档保存）</div>`;
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
    updateCompositeBarUI();
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
      state.pinnedFiles = data.pinnedFiles || [];
      state.archivedFiles = data.archivedFiles || [];
      state.recentFiles = data.recentFiles || [];

      if (!manual && state.sessionFiles.length === 0 && state.recentFiles.length > 0 && state.tab === "session") {
        state.sessionFiles = state.recentFiles.slice(0, 20);
      }

      if (data.pendingInternalOpen && data.pendingInternalOpen.file) {
        openInsideAntigravity(data.pendingInternalOpen.file, true);
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
        openInsideAntigravity(data.pendingInternalOpen.file, true);
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
    if (!state.openMenuPath && !state.selectMode) fetchState(false);
  }, 2500);
})();
