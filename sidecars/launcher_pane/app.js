(function () {
  let state = {
    tab: "session",
    search: "",
    sessionFiles: [],
    recentFiles: [],
    apps: [],
    config: {},
    currentPreviewFile: null,
    autoPreviewedOnce: false,
  };

  const el = (id) => document.getElementById(id);

  // 初始化主题（默认深色高对比度）
  const savedTheme = localStorage.getItem("fl_theme") || "dark";
  applyTheme(savedTheme);

  function applyTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("fl_theme", theme);
    const btn = el("themeToggleBtn");
    if (btn) {
      btn.textContent = theme === "dark" ? "☀️ 换浅色" : "🌙 换深色";
    }
  }

  el("themeToggleBtn").addEventListener("click", () => {
    const cur = document.documentElement.getAttribute("data-theme") || "dark";
    applyTheme(cur === "dark" ? "light" : "dark");
  });

  // 常驻提示栏关闭记忆
  if (localStorage.getItem("fl_hide_resident_banner") === "1") {
    el("residentBanner").classList.add("hidden");
  }
  el("hideBannerBtn").addEventListener("click", () => {
    el("residentBanner").classList.add("hidden");
    localStorage.setItem("fl_hide_resident_banner", "1");
  });

  function showToast(msg) {
    const t = el("toastMsg");
    t.textContent = msg;
    t.classList.remove("hidden");
    clearTimeout(showToast._timer);
    showToast._timer = setTimeout(() => t.classList.add("hidden"), 2600);
  }

  function getConversationId() {
    if (window.antigravity && window.antigravity.conversationId) {
      return window.antigravity.conversationId;
    }
    const params = new URLSearchParams(window.location.search);
    return params.get("conversationId") || "";
  }

  function switchTab(tabName) {
    state.tab = tabName;
    ["session", "recent", "reader"].forEach((t) => {
      const btn = el("tab" + t.charAt(0).toUpperCase() + t.slice(1));
      if (btn) btn.classList.toggle("active", t === tabName);
    });

    if (tabName === "reader") {
      el("searchBarWrap").classList.add("hidden");
      el("fileListContainer").classList.add("hidden");
      el("readerView").classList.remove("hidden");
    } else {
      el("searchBarWrap").classList.remove("hidden");
      el("fileListContainer").classList.remove("hidden");
      el("readerView").classList.add("hidden");
      renderFileList();
    }
  }

  el("tabSession").addEventListener("click", () => switchTab("session"));
  el("tabRecent").addEventListener("click", () => switchTab("recent"));
  el("tabReader").addEventListener("click", () => switchTab("reader"));
  el("readerBackBtn").addEventListener("click", () => switchTab("session"));

  el("searchInput").addEventListener("input", (e) => {
    state.search = (e.target.value || "").trim().toLowerCase();
    renderFileList();
  });

  el("refreshBtn").addEventListener("click", () => {
    fetchState(true);
    showToast("🔄 已刷新文件列表");
  });

  function badgeClass(ext) {
    if (ext === ".docx" || ext === ".doc") return "ext-badge word";
    if (ext === ".pptx" || ext === ".ppt") return "ext-badge ppt";
    if (ext === ".xlsx" || ext === ".xls" || ext === ".csv") return "ext-badge excel";
    if (ext === ".md") return "ext-badge md";
    if (ext === ".pdf") return "ext-badge pdf";
    return "ext-badge";
  }

  function escapeHtml(s) {
    return String(s || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  async function openInSideReader(fileObj) {
    if (!fileObj || !fileObj.path) return;
    state.currentPreviewFile = fileObj;
    el("readerDot").style.display = "inline";
    switchTab("reader");
    el("readerTitle").textContent = fileObj.name || fileObj.path;
    el("readerBadge").textContent = "正在加载预览...";
    el("readerBody").innerHTML = '<div class="loading-box">正在为您解析文档内容...</div>';

    try {
      const res = await fetch("/api/preview?path=" + encodeURIComponent(fileObj.path));
      const data = await res.json();
      if (!data.ok) {
        el("readerBadge").textContent = "读取提示";
        el("readerBody").innerHTML = `<div class="empty-box"><div class="empty-title">无法直接预览</div><div class="empty-desc">${escapeHtml(data.error)}</div></div>`;
        return;
      }
      el("readerBadge").textContent = data.badge || "内置阅读";
      el("readerTitle").textContent = data.title || fileObj.name;
      if (data.kind === "image") {
        el("readerBody").innerHTML = `<div style="text-align:center;"><img src="${data.rawUrl}" style="max-width:100%;border-radius:8px;border:2px solid #475569;" /></div>`;
      } else {
        el("readerBody").innerHTML = data.html || "<p>暂无内容</p>";
      }
    } catch (err) {
      el("readerBody").innerHTML = `<div class="empty-box"><div class="empty-title">预览加载失败</div><div class="empty-desc">${escapeHtml(err.message)}</div></div>`;
    }
  }

  // 阅读器顶部的快捷打开按钮
  el("readerOpenDefaultBtn").addEventListener("click", () => {
    if (state.currentPreviewFile) {
      openFile(state.currentPreviewFile.path, "default");
    }
  });
  el("readerOpenWithBtn").addEventListener("click", () => {
    if (state.currentPreviewFile) {
      showOpenWithModal(state.currentPreviewFile);
    }
  });
  el("readerRevealBtn").addEventListener("click", () => {
    if (state.currentPreviewFile) {
      openFile(state.currentPreviewFile.path, "reveal");
    }
  });

  async function openFile(filePath, mode, appId, rememberExt) {
    try {
      const q = new URLSearchParams({
        path: filePath,
        mode: mode || "default",
        appId: appId || "",
        rememberExt: rememberExt ? "1" : "0",
      });
      const res = await fetch("/api/open?" + q.toString());
      const data = await res.json();
      if (data.ok) {
        if (mode === "reveal") {
          showToast("📂 已在文件夹中为您高亮选中该文件！");
        } else if (mode === "open_with_dialog") {
          showToast("🪟 已呼出 Windows 系统「打开方式」窗口！");
        } else {
          showToast("⚡ 已为您启动电脑软件打开文件！");
        }
      } else {
        showToast("⚠️ 打开失败：" + (data.error || "未知错误"));
      }
    } catch (err) {
      showToast("⚠️ 请求异常：" + err.message);
    }
  }

  function showOpenWithModal(fileObj) {
    const modal = el("openWithModal");
    el("modalFileName").textContent = fileObj.name;
    el("modalExtText").textContent = fileObj.ext || "此类";
    el("rememberExtCheck").checked = false;

    const grid = el("appGrid");
    grid.innerHTML = "";

    // 第一项：内置侧边栏直接看
    const previewBtn = document.createElement("button");
    previewBtn.className = "app-option-btn";
    previewBtn.innerHTML = `<span>👁️</span><span>在右侧面板直接看（内置阅读器）</span>`;
    previewBtn.addEventListener("click", () => {
      modal.classList.add("hidden");
      openInSideReader(fileObj);
    });
    grid.appendChild(previewBtn);

    // 第二项：系统默认软件
    const defBtn = document.createElement("button");
    defBtn.className = "app-option-btn";
    defBtn.innerHTML = `<span>⚡</span><span>系统默认软件直接打开</span>`;
    defBtn.addEventListener("click", () => {
      modal.classList.add("hidden");
      openFile(fileObj.path, "default", "default", el("rememberExtCheck").checked);
    });
    grid.appendChild(defBtn);

    // 检测到的本机软件列表
    (state.apps || []).forEach((app) => {
      const btn = document.createElement("button");
      btn.className = "app-option-btn";
      btn.innerHTML = `<span>${escapeHtml(app.icon || "🖥️")}</span><span>用 <strong>${escapeHtml(app.name)}</strong> 打开</span>`;
      btn.addEventListener("click", () => {
        modal.classList.add("hidden");
        openFile(fileObj.path, "app", app.id, el("rememberExtCheck").checked);
      });
      grid.appendChild(btn);
    });

    // 最后一项：Windows 原生「打开方式...」弹窗
    const sysDialogBtn = document.createElement("button");
    sysDialogBtn.className = "app-option-btn";
    sysDialogBtn.innerHTML = `<span>🪟</span><span>呼出 Windows 系统「打开方式...」弹窗</span>`;
    sysDialogBtn.addEventListener("click", () => {
      modal.classList.add("hidden");
      openFile(fileObj.path, "open_with_dialog");
    });
    grid.appendChild(sysDialogBtn);

    modal.classList.remove("hidden");
  }

  el("closeModalBtn").addEventListener("click", () => {
    el("openWithModal").classList.add("hidden");
  });
  el("openWithModal").addEventListener("click", (e) => {
    if (e.target === el("openWithModal")) {
      el("openWithModal").classList.add("hidden");
    }
  });

  function renderFileList() {
    const container = el("fileListContainer");
    const rawList = state.tab === "recent" ? state.recentFiles : state.sessionFiles;
    const filtered = rawList.filter((f) => {
      if (!state.search) return true;
      const hay = ((f.name || "") + " " + (f.path || "") + " " + (f.badge || "")).toLowerCase();
      return hay.includes(state.search);
    });

    el("countSession").textContent = String((state.sessionFiles || []).length);
    el("countRecent").textContent = String((state.recentFiles || []).length);

    if (!filtered.length) {
      container.innerHTML = `
        <div class="empty-box">
          <div class="empty-icon">📭</div>
          <div class="empty-title">暂未发现匹配的文件</div>
          <div class="empty-desc">您可以切换到「🕒 最近项目文件」查看 D:\projects 下的所有文档，或者让 AI 生成一个新文件试试！</div>
        </div>
      `;
      return;
    }

    container.innerHTML = "";
    filtered.forEach((fileObj) => {
      const card = document.createElement("div");
      card.className = "file-card";
      card.innerHTML = `
        <div class="card-top">
          <div class="file-icon">${escapeHtml(fileObj.icon || "📄")}</div>
          <div class="file-meta">
            <div class="file-title-row">
              <span class="${badgeClass(fileObj.ext)}">${escapeHtml(fileObj.badge || "文件")}</span>
              <span class="file-name" title="点击在右侧直接预览内容">${escapeHtml(fileObj.name)}</span>
            </div>
            <div class="file-path">${escapeHtml(fileObj.sizeText || "")} · ${escapeHtml(fileObj.path)}</div>
          </div>
        </div>
        <div class="card-actions">
          <button class="act-btn act-preview" data-act="preview">👁️ 在侧边直接看</button>
          <button class="act-btn act-primary" data-act="open">⚡ 用电脑软件打开</button>
          <button class="act-btn act-indigo" data-act="openwith">🔄 换个软件打开 ▾</button>
          <button class="act-btn act-folder" data-act="reveal">📂 打开所在文件夹</button>
        </div>
      `;

      // 点击文件名或「在侧边直接看」都在内置阅读器里打开（解决内置侧边打不开 Word 的问题）
      card.querySelector(".file-name").addEventListener("click", () => openInSideReader(fileObj));
      card.querySelector('[data-act="preview"]').addEventListener("click", () => openInSideReader(fileObj));
      card.querySelector('[data-act="open"]').addEventListener("click", () => openFile(fileObj.path, "default"));
      card.querySelector('[data-act="openwith"]').addEventListener("click", () => showOpenWithModal(fileObj));
      card.querySelector('[data-act="reveal"]').addEventListener("click", () => openFile(fileObj.path, "reveal"));

      container.appendChild(card);
    });
  }

  async function fetchState(manual) {
    try {
      const convId = getConversationId();
      const res = await fetch("/api/state?conversationId=" + encodeURIComponent(convId));
      const data = await res.json();
      if (!data.ok) return;
      state.sessionFiles = data.sessionFiles || [];
      state.recentFiles = data.recentFiles || [];
      state.apps = data.apps || [];
      state.config = data.config || {};

      if (state.tab !== "reader") {
        renderFileList();
      } else {
        el("countSession").textContent = String(state.sessionFiles.length);
        el("countRecent").textContent = String(state.recentFiles.length);
      }

      // 如果本次对话没有关联文件但最近项目文件有，自动展示最近项目文件避免空白
      if (!manual && state.sessionFiles.length === 0 && state.recentFiles.length > 0 && state.tab === "session") {
        state.sessionFiles = state.recentFiles.slice(0, 12);
        renderFileList();
      }
    } catch (err) {
      console.error("Failed to fetch state:", err);
    }
  }

  fetchState(false);
  setInterval(() => fetchState(false), 3500);
})();
