(function () {
  let state = {
    tab: "session",
    search: "",
    sessionFiles: [],
    recentFiles: [],
    openMenuPath: null,
  };

  const el = (id) => document.getElementById(id);

  function showToast(msg) {
    const t = el("toastMsg");
    if (!t) return;
    t.textContent = msg;
    t.classList.remove("hidden");
    clearTimeout(showToast._t);
    showToast._t = setTimeout(() => t.classList.add("hidden"), 1800);
  }

  function getConversationId() {
    if (window.antigravity && window.antigravity.conversationId) {
      return window.antigravity.conversationId;
    }
    const params = new URLSearchParams(window.location.search);
    return params.get("conversationId") || "";
  }

  function pillClass(ext) {
    if (ext === ".docx" || ext === ".doc") return "ext-pill word";
    if (ext === ".pptx" || ext === ".ppt") return "ext-pill ppt";
    if (ext === ".xlsx" || ext === ".xls" || ext === ".csv") return "ext-pill excel";
    if (ext === ".md") return "ext-pill md";
    if (ext === ".pdf") return "ext-pill pdf";
    return "ext-pill";
  }

  function esc(s) {
    return String(s || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  async function triggerOpen(filePath, mode, appId) {
    try {
      const q = new URLSearchParams({
        path: filePath,
        mode: mode || "default",
        appId: appId || "",
      });
      const res = await fetch("/api/open?" + q.toString());
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

  // Close open dropdown when clicking outside
  document.addEventListener("click", (e) => {
    if (!e.target.closest(".open-with-wrap")) {
      state.openMenuPath = null;
      document.querySelectorAll(".dropdown-menu").forEach((m) => m.classList.add("hidden"));
    }
  });

  el("tabSession").addEventListener("click", () => {
    state.tab = "session";
    el("tabSession").classList.add("active");
    el("tabRecent").classList.remove("active");
    renderList();
  });

  el("tabRecent").addEventListener("click", () => {
    state.tab = "recent";
    el("tabRecent").classList.add("active");
    el("tabSession").classList.remove("active");
    renderList();
  });

  el("searchInput").addEventListener("input", (e) => {
    state.search = (e.target.value || "").trim().toLowerCase();
    renderList();
  });

  el("refreshBtn").addEventListener("click", () => {
    fetchState(true);
    showToast("已刷新");
  });

  function renderList() {
    const container = el("fileListContainer");
    const raw = state.tab === "recent" ? state.recentFiles : state.sessionFiles;
    const list = raw.filter((f) => {
      if (!state.search) return true;
      return ((f.name || "") + " " + (f.path || "")).toLowerCase().includes(state.search);
    });

    el("countSession").textContent = String((state.sessionFiles || []).length);
    el("countRecent").textContent = String((state.recentFiles || []).length);

    if (!list.length) {
      container.innerHTML = `<div class="empty-box">暂无可读文档</div>`;
      return;
    }

    container.innerHTML = "";
    list.forEach((f) => {
      const item = document.createElement("div");
      item.className = "codex-item";
      const extLabel = (f.ext || "FILE").replace(".", "").toUpperCase();
      const matched = Array.isArray(f.matchedApps) ? f.matchedApps : [];

      const appButtonsHtml = matched
        .map(
          (a) =>
            `<button class="menu-item" data-mode="app" data-app="${esc(a.id)}"><span>${esc(a.name)}</span></button>`
        )
        .join("");

      const isMenuOpen = state.openMenuPath === f.path;

      item.innerHTML = `
        <div class="item-main" data-act="default-open" title="点击直接打开 ${esc(f.name)}">
          <span class="${pillClass(f.ext)}">${esc(extLabel)}</span>
          <div class="item-text">
            <div class="item-name">${esc(f.name)}</div>
            <div class="item-sub">${esc(f.sizeText || "")} · ${esc(f.dir || "")}</div>
          </div>
        </div>
        <div class="open-with-wrap">
          <button class="open-with-btn" data-act="toggle-menu">
            <span>打开方式</span>
            <svg viewBox="0 0 24 24" class="svg-caret"><path d="m6 9 6 6 6-6"/></svg>
          </button>
          <div class="dropdown-menu ${isMenuOpen ? "" : "hidden"}">
            ${
              matched.length
                ? `<div class="menu-section-label">匹配的应用</div>${appButtonsHtml}<div class="menu-divider"></div>`
                : ""
            }
            <button class="menu-item" data-mode="reveal">
              <span>文件资源管理器</span>
            </button>
            <button class="menu-item" data-mode="open_with_dialog">
              <span>选择打开方式...</span>
            </button>
          </div>
        </div>
      `;

      // Click left file area -> open directly with default app
      item.querySelector('[data-act="default-open"]').addEventListener("click", () => {
        triggerOpen(f.path, "default", "");
      });

      // Click "打开方式 ▾" -> toggle smart dropdown menu
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

      // Menu item clicks
      menuEl.querySelectorAll(".menu-item").forEach((btn) => {
        btn.addEventListener("click", (e) => {
          e.stopPropagation();
          menuEl.classList.add("hidden");
          state.openMenuPath = null;
          const mode = btn.getAttribute("data-mode");
          const appId = btn.getAttribute("data-app") || "";
          triggerOpen(f.path, mode, appId);
        });
      });

      container.appendChild(item);
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

      if (!manual && state.sessionFiles.length === 0 && state.recentFiles.length > 0 && state.tab === "session") {
        state.sessionFiles = state.recentFiles.slice(0, 15);
      }
      renderList();
    } catch (err) {
      console.error("Failed to fetch state:", err);
    }
  }

  fetchState(false);
  setInterval(() => {
    // Do not re-render while user has the dropdown menu open
    if (!state.openMenuPath) fetchState(false);
  }, 3500);
})();
