(function () {
  let state = {
    tab: "session",
    search: "",
    sessionFiles: [],
    recentFiles: [],
    apps: [],
    config: {},
    currentPreviewFile: null,
  };

  const el = (id) => document.getElementById(id);

  const savedTheme = localStorage.getItem("fl_theme") || "dark";
  document.documentElement.setAttribute("data-theme", savedTheme);

  el("themeToggleBtn").addEventListener("click", () => {
    const cur = document.documentElement.getAttribute("data-theme") || "dark";
    const next = cur === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    localStorage.setItem("fl_theme", next);
  });

  function showToast(msg) {
    const t = el("toastMsg");
    t.textContent = msg;
    t.classList.remove("hidden");
    clearTimeout(showToast._timer);
    showToast._timer = setTimeout(() => t.classList.add("hidden"), 2200);
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
      el("fileListContainer").classList.add("hidden");
      el("readerView").classList.remove("hidden");
    } else {
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
    if (state.tab !== "reader") renderFileList();
  });

  el("refreshBtn").addEventListener("click", () => {
    fetchState(true);
    showToast("已刷新");
  });

  function tagClass(ext) {
    if (ext === ".docx" || ext === ".doc") return "ext-tag word";
    if (ext === ".pptx" || ext === ".ppt") return "ext-tag ppt";
    if (ext === ".xlsx" || ext === ".xls" || ext === ".csv") return "ext-tag excel";
    if (ext === ".md") return "ext-tag md";
    if (ext === ".pdf") return "ext-tag pdf";
    return "ext-tag";
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
    switchTab("reader");
    el("readerTitle").textContent = fileObj.name || fileObj.path;
    el("readerBadge").textContent = (fileObj.ext || "FILE").replace(".", "").toUpperCase();
    el("readerBadge").className = tagClass(fileObj.ext);
    el("readerBody").innerHTML = '<div class="empty-state">正在解析文档内容...</div>';

    try {
      const res = await fetch("/api/preview?path=" + encodeURIComponent(fileObj.path));
      const data = await res.json();
      if (!data.ok) {
        el("readerBody").innerHTML = `<div class="empty-state">${escapeHtml(data.error)}</div>`;
        return;
      }
      if (data.kind === "image") {
        el("readerBody").innerHTML = `<div style="text-align:center;"><img src="${data.rawUrl}" style="max-width:100%;border-radius:6px;border:1px solid var(--border-default);" /></div>`;
      } else {
        el("readerBody").innerHTML = data.html || '<div class="empty-state">暂无内容</div>';
      }
    } catch (err) {
      el("readerBody").innerHTML = `<div class="empty-state">预览加载失败: ${escapeHtml(err.message)}</div>`;
    }
  }

  el("readerOpenDefaultBtn").addEventListener("click", () => {
    if (state.currentPreviewFile) openFile(state.currentPreviewFile.path, "default");
  });
  el("readerOpenWithBtn").addEventListener("click", () => {
    if (state.currentPreviewFile) showOpenWithModal(state.currentPreviewFile);
  });
  el("readerRevealBtn").addEventListener("click", () => {
    if (state.currentPreviewFile) openFile(state.currentPreviewFile.path, "reveal");
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
        showToast(mode === "reveal" ? "已在文件夹中定位" : "已打开文件");
      } else {
        showToast("打开失败: " + (data.error || "未知错误"));
      }
    } catch (err) {
      showToast("请求失败: " + err.message);
    }
  }

  function showOpenWithModal(fileObj) {
    const modal = el("openWithModal");
    el("modalFileName").textContent = fileObj.name;
    el("modalExtText").textContent = fileObj.ext || "此类";
    el("rememberExtCheck").checked = false;

    const grid = el("appGrid");
    grid.innerHTML = "";

    const addOption = (label, subLabel, onClick) => {
      const btn = document.createElement("button");
      btn.className = "app-item-btn";
      btn.innerHTML = `<span>${escapeHtml(label)}</span><span style="font-size:11px;color:var(--fg-secondary);">${escapeHtml(subLabel || "")}</span>`;
      btn.addEventListener("click", () => {
        modal.classList.add("hidden");
        onClick();
      });
      grid.appendChild(btn);
    };

    addOption("系统默认应用", "Default", () => {
      openFile(fileObj.path, "default", "default", el("rememberExtCheck").checked);
    });

    (state.apps || []).forEach((app) => {
      if (app.id === "default" || app.id === "open_with_dialog" || app.id === "explorer") return;
      addOption(app.name, "桌面应用", () => {
        openFile(fileObj.path, "app", app.id, el("rememberExtCheck").checked);
      });
    });

    addOption("系统「打开方式...」对话框", "Windows", () => {
      openFile(fileObj.path, "open_with_dialog");
    });

    modal.classList.remove("hidden");
  }

  el("closeModalBtn").addEventListener("click", () => el("openWithModal").classList.add("hidden"));
  el("openWithModal").addEventListener("click", (e) => {
    if (e.target === el("openWithModal")) el("openWithModal").classList.add("hidden");
  });

  function renderFileList() {
    const container = el("fileListContainer");
    const rawList = state.tab === "recent" ? state.recentFiles : state.sessionFiles;
    const filtered = rawList.filter((f) => {
      if (!state.search) return true;
      const hay = ((f.name || "") + " " + (f.path || "")).toLowerCase();
      return hay.includes(state.search);
    });

    el("countSession").textContent = String((state.sessionFiles || []).length);
    el("countRecent").textContent = String((state.recentFiles || []).length);

    if (!filtered.length) {
      container.innerHTML = `<div class="empty-state">暂无匹配的可读文档</div>`;
      return;
    }

    container.innerHTML = "";
    filtered.forEach((fileObj) => {
      const row = document.createElement("div");
      row.className = "file-row";
      const extLabel = (fileObj.ext || "FILE").replace(".", "").toUpperCase();

      row.innerHTML = `
        <div class="file-info" data-act="preview" title="点击预览文档内容">
          <span class="${tagClass(fileObj.ext)}">${escapeHtml(extLabel)}</span>
          <div class="file-text">
            <div class="file-title">${escapeHtml(fileObj.name)}</div>
            <div class="file-meta-sub">${escapeHtml(fileObj.sizeText || "")} · ${escapeHtml(fileObj.dir || "")}</div>
          </div>
        </div>
        <div class="row-actions">
          <button class="btn btn-secondary" data-act="preview">预览</button>
          <div class="split-btn-group">
            <button class="btn btn-primary split-main" data-act="open" title="使用默认应用打开">
              <span>打开</span>
              <svg viewBox="0 0 24 24" class="svg-icon-sm"><path d="M7 17 17 7"/><path d="M7 7h10v10"/></svg>
            </button>
            <button class="btn btn-primary split-trigger" data-act="openwith" title="选择打开应用">
              <svg viewBox="0 0 24 24" class="svg-icon-sm"><path d="m6 9 6 6 6-6"/></svg>
            </button>
          </div>
          <button class="icon-btn" data-act="reveal" title="在文件夹中显示">
            <svg viewBox="0 0 24 24" class="svg-icon"><path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"/></svg>
          </button>
        </div>
      `;

      row.querySelectorAll('[data-act="preview"]').forEach((n) =>
        n.addEventListener("click", () => openInSideReader(fileObj))
      );
      row.querySelector('[data-act="open"]').addEventListener("click", () => openFile(fileObj.path, "default"));
      row.querySelector('[data-act="openwith"]').addEventListener("click", () => showOpenWithModal(fileObj));
      row.querySelector('[data-act="reveal"]').addEventListener("click", () => openFile(fileObj.path, "reveal"));

      container.appendChild(row);
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

      if (!manual && state.sessionFiles.length === 0 && state.recentFiles.length > 0 && state.tab === "session") {
        state.sessionFiles = state.recentFiles.slice(0, 15);
        renderFileList();
      }
    } catch (err) {
      console.error("Failed to fetch state:", err);
    }
  }

  fetchState(false);
  setInterval(() => fetchState(false), 3500);
})();
