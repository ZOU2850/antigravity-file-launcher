(() => {
  const $ = (id) => document.getElementById(id);
  const params = new URLSearchParams(location.search);

  const state = {
    tab: 'session', // 'session' | 'recent'
    filter: 'all',  // 'all' | 'office' | 'doc'
    apps: [],
    config: { watchedDirs: [], pinnedFiles: [], customApps: [], extDefaults: {} },
    sessionFiles: [],
    recentFiles: [],
    menuTargetPath: '',
    menuTargetExt: ''
  };

  const currentConv = () => window.sidecar?.conversationId || params.get('conversationId') || '';

  async function apiGet(path, query = {}) {
    const u = new URL(path, location.origin);
    for (const [k, v] of Object.entries(query)) {
      if (v !== undefined && v !== null && v !== '') u.searchParams.set(k, String(v));
    }
    const f = window.sidecar?.fetch ? window.sidecar.fetch.bind(window.sidecar) : fetch;
    const res = await f(u.pathname + u.search, { method: 'GET' });
    if (!res.ok) throw new Error(`${path}: ${res.status}`);
    return res.json();
  }

  let toastTimer = null;
  function toast(msg) {
    const el = $('toast');
    el.textContent = msg;
    el.classList.remove('hidden');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.classList.add('hidden'), 2600);
  }

  const esc = (s) =>
    String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  const FRIENDLY_TYPE = {
    '.docx': 'Word 文档',
    '.doc':  'Word 文档',
    '.pptx': 'PPT 演示文稿',
    '.ppt':  'PPT 演示文稿',
    '.xlsx': 'Excel 表格',
    '.xls':  'Excel 表格',
    '.csv':  'CSV 表格',
    '.pdf':  'PDF 文档',
    '.md':   'Markdown 笔记',
    '.html': '网页文件',
    '.htm':  '网页文件',
    '.txt':  '文本文件',
    '.png':  '图片文件',
    '.jpg':  '图片文件',
    '.jpeg': '图片文件',
    '.svg':  '矢量图标',
    '.exe':  '安装程序',
    '.zip':  '压缩包',
    '.py':   'Python 脚本',
    '.js':   'JS 脚本',
    '.json': '配置文件'
  };

  const OFFICE_EXTS = new Set(['.docx', '.doc', '.pptx', '.ppt', '.xlsx', '.xls', '.csv', '.pdf']);
  const DOC_EXTS = new Set(['.md', '.txt', '.html', '.htm', '.png', '.jpg', '.jpeg', '.svg']);

  function formatSize(bytes) {
    if (!bytes || bytes <= 0) return '';
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }

  function activeList() {
    const raw = state.tab === 'session' ? state.sessionFiles : state.recentFiles;
    return raw.filter((item) => {
      if (state.filter === 'office') return OFFICE_EXTS.has(item.ext);
      if (state.filter === 'doc') return DOC_EXTS.has(item.ext);
      return true;
    });
  }

  function preferredAppLabel(ext) {
    const appId = ext && state.config.extDefaults?.[ext];
    if (!appId || appId === 'default') return '直接打开';
    const app = state.apps.find((a) => a.id === appId);
    return app ? `用 ${app.name.split(' ')[0]} 打开` : '直接打开';
  }

  function renderList() {
    $('count-session').textContent = String(state.sessionFiles.length);
    $('count-recent').textContent = String(state.recentFiles.length);

    const items = activeList();
    const container = $('file-list');

    if (!items.length) {
      container.innerHTML = `
        <div class="empty-state">
          <div class="empty-state-icon">📭</div>
          <div>这里还没有匹配的文件。<br>可以点上方切换标签页或筛选分类看看！</div>
        </div>
      `;
      return;
    }

    container.innerHTML = items
      .map((f) => {
        const friendlyType = f.isDir ? '文件夹' : (FRIENDLY_TYPE[f.ext] || `${(f.ext || '').replace('.', '').toUpperCase() || '普通'}文件`);
        const openLabel = preferredAppLabel(f.ext);
        const isFeatured = OFFICE_EXTS.has(f.ext) || f.ext === '.md';
        const folderShort = f.dir.replace(/^D:\\projects\\?/i, 'D:\\projects\\');

        return `
          <div class="file-card ${isFeatured ? 'featured' : ''}" role="listitem" data-path="${esc(f.path)}" data-ext="${esc(f.ext)}">
            <div class="file-main" data-act="open-default" title="点击直接打开：${esc(f.name)}">
              <div class="file-icon-box" aria-hidden="true">${esc(f.icon)}</div>
              <div class="file-info">
                <div class="file-name">${esc(f.name)}</div>
                <div class="file-meta">
                  <span class="type-tag">${esc(friendlyType)}</span>
                  ${formatSize(f.size) ? `<span>${esc(formatSize(f.size))}</span>` : ''}
                  <span>📁 ${esc(folderShort)}</span>
                </div>
              </div>
            </div>
            <div class="file-actions">
              <button type="button" class="btn primary" data-act="open-default" title="用默认软件直接打开这个文件">
                ⚡ ${esc(openLabel)}
              </button>
              <button type="button" class="btn" data-act="open-with-menu" title="自由选择用 Word、WPS、记事本、VS Code 或其他软件打开">
                🔄 换个软件打开 ▾
              </button>
              <button type="button" class="btn" data-act="reveal" title="打开电脑文件夹并帮你高亮找到这个文件">
                📂 所在文件夹
              </button>
            </div>
          </div>
        `;
      })
      .join('');
  }

  function showOpenWithMenu(filePath, ext) {
    state.menuTargetPath = filePath;
    state.menuTargetExt = ext || '';
    const fileName = filePath.split(/[\\/]/).pop();
    $('popover-filename').textContent = `用什么打开「${fileName}」？`;
    $('popover-ext').textContent = ext || '此类文件';
    $('chk-remember-ext').checked = Boolean(ext && state.config.extDefaults?.[ext]);
    $('chk-remember-ext').disabled = !ext;

    // Filter out 'reveal' from Open With list since it has its own dedicated button
    const menuApps = state.apps.filter((a) => a.id !== 'reveal');

    $('popover-items').innerHTML = menuApps
      .map((a) => {
        const friendlyDesc =
          a.id === 'default'
            ? '最省心：按你电脑平时双击它的方式直接打开'
            : a.id === 'open_with_dialog'
            ? '弹出 Windows 系统自带的“打开方式”列表选其他软件'
            : `使用你电脑上的 ${a.name} 打开`;
        return `
          <button type="button" class="menu-item" role="menuitem" data-app-id="${esc(a.id)}">
            <span class="menu-item-icon">${esc(a.icon)}</span>
            <span class="menu-item-text">
              <b>${esc(a.name)}</b>
              <span class="menu-item-sub">${esc(friendlyDesc)}</span>
            </span>
          </button>
        `;
      })
      .join('');

    $('open-with-backdrop').classList.remove('hidden');
    $('open-with-menu').classList.remove('hidden');
  }

  function hideOpenWithMenu() {
    $('open-with-backdrop').classList.add('hidden');
    $('open-with-menu').classList.add('hidden');
  }

  async function triggerOpen(path, mode = 'default', appId = '', rememberExt = false) {
    if (!path) return;
    try {
      const res = await apiGet('/api/open', {
        path,
        mode,
        appId,
        rememberExt: rememberExt ? '1' : '0'
      });
      if (!res.ok) {
        toast(`⚠️ 没能打开：${res.error || '请换个打开方式试试'}`);
      } else {
        const name = path.split(/[\\/]/).pop();
        const label =
          mode === 'reveal' || appId === 'reveal'
            ? `已在电脑文件夹中为你选中：${name}`
            : mode === 'open_with_dialog' || appId === 'open_with_dialog'
            ? '已弹出系统“打开方式”窗口，请在弹窗中选择软件'
            : `正在为你打开：${name}`;
        toast(`✅ ${label}`);
        if (rememberExt) await refreshState();
      }
    } catch (err) {
      toast(`⚠️ 连接异常：${err.message}`);
    }
  }

  async function refreshState() {
    try {
      const data = await apiGet('/api/state', { conversationId: currentConv() });
      if (!data.ok) return;
      state.apps = data.apps || [];
      state.config = data.config || state.config;
      state.sessionFiles = data.sessionFiles || [];
      state.recentFiles = data.recentFiles || [];
      renderList();
    } catch (err) {
      console.error('[file-launcher] refresh error:', err);
    }
  }

  document.querySelectorAll('.tab[data-tab]').forEach((btn) => {
    btn.addEventListener('click', () => {
      state.tab = btn.dataset.tab;
      document.querySelectorAll('.tab[data-tab]').forEach((b) => b.classList.toggle('active', b === btn));
      renderList();
    });
  });

  document.querySelectorAll('.chip[data-filter]').forEach((btn) => {
    btn.addEventListener('click', () => {
      state.filter = btn.dataset.filter;
      document.querySelectorAll('.chip[data-filter]').forEach((b) => b.classList.toggle('active', b === btn));
      renderList();
    });
  });

  $('btn-refresh').addEventListener('click', () => {
    refreshState();
    toast('✅ 已刷新最新文件列表');
  });

  $('file-list').addEventListener('click', async (e) => {
    const target = e.target.closest('[data-act]');
    if (!target) return;
    const card = target.closest('.file-card');
    if (!card) return;
    const path = card.dataset.path;
    const ext = card.dataset.ext;
    const act = target.dataset.act;

    if (act === 'open-default') {
      await triggerOpen(path, 'default');
    } else if (act === 'open-with-menu') {
      e.stopPropagation();
      showOpenWithMenu(path, ext);
    } else if (act === 'reveal') {
      await triggerOpen(path, 'reveal');
    }
  });

  $('popover-items').addEventListener('click', async (e) => {
    const item = e.target.closest('.menu-item[data-app-id]');
    if (!item) return;
    const appId = item.dataset.appId;
    const remember = $('chk-remember-ext').checked && !['reveal', 'open_with_dialog'].includes(appId);
    hideOpenWithMenu();
    await triggerOpen(state.menuTargetPath, appId === 'default' ? 'default' : 'app', appId, remember);
  });

  $('btn-close-menu').addEventListener('click', hideOpenWithMenu);
  $('open-with-backdrop').addEventListener('click', hideOpenWithMenu);

  refreshState();
  setInterval(refreshState, 2500);
})();
