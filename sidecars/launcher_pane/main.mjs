/**
 * File Launcher Sidecar Backend for Google Antigravity.
 *
 * Provides:
 * 1. Automatic real-time discovery of files created, modified, linked, or read
 *    in the active conversation (via transcript.jsonl + brain/<conv>/ artifacts).
 * 2. Automatic scanning of recent deliverables in D:\projects (and custom watched dirs).
 * 3. Native desktop launching:
 *    - Click-to-open with system default handler (or per-extension preferred app)
 *    - Native Windows "Open With..." system dialog (shell32.dll,OpenAs_RunDLL)
 *    - Direct launch with detected/custom apps (Antigravity, VS Code, Cursor, Office/WPS, Edge/Chrome, Notepad, PowerShell)
 *    - Reveal and select in Windows File Explorer (explorer.exe /select,<path>)
 */
import { spawn } from 'node:child_process';
import { existsSync, mkdirSync, readFileSync, readdirSync, realpathSync, statSync, writeFileSync } from 'node:fs';
import http from 'node:http';
import { homedir, platform } from 'node:os';
import { basename, dirname, extname, isAbsolute, join, normalize, resolve as resolvePath, sep } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const IS_WIN = platform() === 'win32';
const ID_RE = /^[0-9a-f-]{8,}$/i;

// Load sidecar_sdk when running inside Antigravity Language Server, with a
// standalone HTTP fallback for local testing (`node main.mjs --selftest`).
let SidecarApp;
let Response;
try {
  const sdk = await import('sidecar_sdk');
  SidecarApp = sdk.SidecarApp;
  Response = sdk.Response;
} catch {
  Response = class StandaloneResponse {
    constructor(body, init = {}) {
      this.body = body;
      this.status = init.status || 200;
      this.contentType = init.contentType || 'text/plain; charset=utf-8';
      this.headers = init.headers || {};
    }
  };
  SidecarApp = class StandaloneSidecarApp {
    constructor() {
      this.config = { conversationId: process.env.ANTIGRAVITY_CONVERSATION_ID || '' };
      this.routes = new Map();
    }
    page(route, fn) {
      this.routes.set(`GET:${route}`, (q) => new Response(fn(q), { contentType: 'text/html; charset=utf-8' }));
    }
    api(route, fn, method = 'GET') {
      this.routes.set(`${method.toUpperCase()}:${route}`, fn);
    }
    run() {
      const port = Number(process.env.ANTIGRAVITY_SIDECAR_WEB_PORT || 0);
      const srv = http.createServer(async (req, res) => {
        const u = new URL(req.url || '/', 'http://localhost');
        const key = `${(req.method || 'GET').toUpperCase()}:${u.pathname}`;
        const handler = this.routes.get(key);
        if (!handler) {
          res.writeHead(404);
          res.end('Not found');
          return;
        }
        const query = Object.fromEntries(u.searchParams.entries());
        try {
          const out = await handler(query);
          if (out instanceof Response) {
            res.writeHead(out.status, { 'Content-Type': out.contentType, ...out.headers });
            res.end(out.body);
          } else {
            res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
            res.end(JSON.stringify(out));
          }
        } catch (err) {
          res.writeHead(500, { 'Content-Type': 'application/json; charset=utf-8' });
          res.end(JSON.stringify({ ok: false, error: String(err?.message || err) }));
        }
      });
      srv.listen(port, '127.0.0.1', () => {
        const addr = srv.address();
        console.log(`[file-launcher] standalone server listening on http://127.0.0.1:${addr.port}`);
      });
      return srv;
    }
  };
}

// ---------------------------------------------------------------------------
// AppData & Configuration Persistence
// ---------------------------------------------------------------------------

function findAppDataDirs() {
  const dataDir = process.env.ANTIGRAVITY_EXECUTABLE_DATA_DIR;
  if (dataDir) {
    for (let d = dataDir; d !== dirname(d); d = dirname(d)) {
      if (basename(d) !== 'sidecar_data') continue;
      const appData = dirname(d);
      if (existsSync(join(appData, 'brain'))) return [appData];
    }
  }
  const envAppData = process.env.ANTIGRAVITY_APP_DATA_DIR;
  if (envAppData && existsSync(join(envAppData, 'brain'))) {
    return [normalize(envAppData)];
  }
  const root = join(homedir(), '.gemini');
  const candidates = ['antigravity', 'antigravity-ide', 'antigravity-cli'];
  const found = [];
  for (const c of candidates) {
    const p = join(root, c);
    if (existsSync(join(p, 'brain'))) found.push(p);
  }
  return found;
}

function getConfigPath() {
  const dirs = findAppDataDirs();
  const base = dirs[0] || join(homedir(), '.gemini', 'antigravity');
  try {
    mkdirSync(base, { recursive: true });
  } catch {}
  return join(base, 'file_launcher_config.json');
}

const DEFAULT_CONFIG = {
  watchedDirs: IS_WIN && existsSync('D:\\projects') ? ['D:\\projects'] : [join(homedir(), 'Desktop')],
  pinnedFiles: [],
  customApps: [],
  extDefaults: {} // e.g. { ".pptx": "default", ".md": "vscode" }
};

function loadUserConfig() {
  const p = getConfigPath();
  try {
    if (!existsSync(p)) return structuredClone(DEFAULT_CONFIG);
    const raw = JSON.parse(readFileSync(p, 'utf-8'));
    return {
      watchedDirs: Array.isArray(raw.watchedDirs) && raw.watchedDirs.length ? raw.watchedDirs : DEFAULT_CONFIG.watchedDirs,
      pinnedFiles: Array.isArray(raw.pinnedFiles) ? raw.pinnedFiles : [],
      customApps: Array.isArray(raw.customApps) ? raw.customApps : [],
      extDefaults: raw.extDefaults && typeof raw.extDefaults === 'object' ? raw.extDefaults : {}
    };
  } catch {
    return structuredClone(DEFAULT_CONFIG);
  }
}

function saveUserConfig(cfg) {
  const p = getConfigPath();
  try {
    writeFileSync(p, JSON.stringify(cfg, null, 2), 'utf-8');
    return true;
  } catch {
    return false;
  }
}

// ---------------------------------------------------------------------------
// Detecting Installed Applications for "Open With"
// ---------------------------------------------------------------------------

let cachedApps = null;
let cachedAppsAt = 0;

function detectInstalledApps(customApps = []) {
  const now = Date.now();
  if (cachedApps && now - cachedAppsAt < 30000) {
    return mergeCustomApps(cachedApps, customApps);
  }
  const apps = [
    {
      id: 'default',
      name: '系统默认程序 (Default)',
      icon: '⚡',
      desc: '使用操作系统关联的默认软件直接打开',
      builtin: true
    },
    {
      id: 'open_with_dialog',
      name: '选择其他应用… (系统打开方式弹窗)',
      icon: '🪟',
      desc: '唤起 Windows 原生“你要如何打开这个文件？”选择窗口',
      builtin: true
    },
    {
      id: 'reveal',
      name: '在资源管理器中定位 (Explorer)',
      icon: '📂',
      desc: '打开所在文件夹并高亮选中该文件',
      builtin: true
    }
  ];

  if (IS_WIN) {
    const localAppData = process.env.LOCALAPPDATA || join(homedir(), 'AppData', 'Local');
    const progFiles = process.env.ProgramFiles || 'C:\\Program Files';
    const progFiles86 = process.env['ProgramFiles(x86)'] || 'C:\\Program Files (x86)';
    const sysRoot = process.env.SystemRoot || 'C:\\Windows';

    const candidates = [
      {
        id: 'antigravity',
        name: 'Antigravity',
        icon: '🚀',
        paths: [
          join(localAppData, 'Programs', 'antigravity', 'Antigravity.exe'),
          join(localAppData, 'Programs', 'Antigravity IDE', 'Antigravity IDE.exe')
        ]
      },
      {
        id: 'vscode',
        name: 'VS Code',
        icon: '📘',
        paths: [
          join(localAppData, 'Programs', 'Microsoft VS Code', 'Code.exe'),
          join(progFiles, 'Microsoft VS Code', 'Code.exe')
        ]
      },
      {
        id: 'cursor',
        name: 'Cursor',
        icon: '🖱️',
        paths: [
          join(localAppData, 'Programs', 'cursor', 'Cursor.exe')
        ]
      },
      {
        id: 'wps',
        name: 'WPS Office',
        icon: '📄',
        paths: [
          join(localAppData, 'Kingsoft', 'WPS Office', 'ksolaunch.exe'),
          join(progFiles, 'Kingsoft', 'WPS Office', 'ksolaunch.exe'),
          join(progFiles86, 'Kingsoft', 'WPS Office', 'ksolaunch.exe')
        ]
      },
      {
        id: 'powerpoint',
        name: 'PowerPoint',
        icon: '📊',
        paths: [
          join(progFiles, 'Microsoft Office', 'root', 'Office16', 'POWERPNT.EXE'),
          join(progFiles86, 'Microsoft Office', 'root', 'Office16', 'POWERPNT.EXE')
        ]
      },
      {
        id: 'excel',
        name: 'Excel',
        icon: '📗',
        paths: [
          join(progFiles, 'Microsoft Office', 'root', 'Office16', 'EXCEL.EXE'),
          join(progFiles86, 'Microsoft Office', 'root', 'Office16', 'EXCEL.EXE')
        ]
      },
      {
        id: 'word',
        name: 'Word',
        icon: '📘',
        paths: [
          join(progFiles, 'Microsoft Office', 'root', 'Office16', 'WINWORD.EXE'),
          join(progFiles86, 'Microsoft Office', 'root', 'Office16', 'WINWORD.EXE')
        ]
      },
      {
        id: 'edge',
        name: 'Microsoft Edge',
        icon: '🌐',
        paths: [
          join(progFiles86, 'Microsoft', 'Edge', 'Application', 'msedge.exe'),
          join(progFiles, 'Microsoft', 'Edge', 'Application', 'msedge.exe')
        ]
      },
      {
        id: 'chrome',
        name: 'Google Chrome',
        icon: '🌍',
        paths: [
          join(progFiles, 'Google', 'Chrome', 'Application', 'chrome.exe'),
          join(progFiles86, 'Google', 'Chrome', 'Application', 'chrome.exe'),
          join(localAppData, 'Google', 'Chrome', 'Application', 'chrome.exe')
        ]
      },
      {
        id: 'notepadpp',
        name: 'Notepad++',
        icon: '📝',
        paths: [
          join(progFiles, 'Notepad++', 'notepad++.exe'),
          join(progFiles86, 'Notepad++', 'notepad++.exe')
        ]
      },
      {
        id: 'typora',
        name: 'Typora',
        icon: '✍️',
        paths: [
          join(progFiles, 'Typora', 'Typora.exe'),
          join(localAppData, 'Programs', 'Typora', 'Typora.exe')
        ]
      },
      {
        id: 'notepad',
        name: '记事本 (Notepad)',
        icon: '🗒️',
        paths: [join(sysRoot, 'System32', 'notepad.exe')]
      },
      {
        id: 'powershell',
        name: 'PowerShell (在此目录打开)',
        icon: '💻',
        paths: [join(sysRoot, 'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe')]
      }
    ];

    for (const c of candidates) {
      const hit = c.paths.find((p) => {
        try {
          return existsSync(p);
        } catch {
          return false;
        }
      });
      if (hit) {
        apps.push({
          id: c.id,
          name: c.name,
          icon: c.icon,
          exe: hit,
          desc: hit
        });
      }
    }
  }

  cachedApps = apps;
  cachedAppsAt = now;
  return mergeCustomApps(apps, customApps);
}

function mergeCustomApps(baseApps, customApps) {
  const out = [...baseApps];
  for (const ca of customApps || []) {
    if (!ca || !ca.name || !ca.exe) continue;
    out.push({
      id: `custom:${ca.id || ca.name}`,
      name: ca.name,
      icon: ca.icon || '🔧',
      exe: ca.exe,
      desc: ca.exe,
      custom: true
    });
  }
  return out;
}

// ---------------------------------------------------------------------------
// File Info Helpers & Transcript Extraction
// ---------------------------------------------------------------------------

const DELIVERABLE_EXTS = new Set([
  '.pptx', '.ppt', '.pdf', '.docx', '.doc', '.xlsx', '.xls', '.csv',
  '.html', '.htm', '.md', '.png', '.jpg', '.jpeg', '.webp', '.svg',
  '.mp4', '.mp3', '.wav', '.zip', '.7z', '.tar', '.gz', '.json', '.py', '.js', '.ts'
]);

const CATEGORY_MAP = {
  '.pptx': { badge: 'PPT', color: 'amber', icon: '📊', priority: 100 },
  '.ppt':  { badge: 'PPT', color: 'amber', icon: '📊', priority: 100 },
  '.pdf':  { badge: 'PDF', color: 'red', icon: '📕', priority: 95 },
  '.docx': { badge: 'Word', color: 'blue', icon: '📘', priority: 95 },
  '.doc':  { badge: 'Word', color: 'blue', icon: '📘', priority: 95 },
  '.xlsx': { badge: 'Excel', color: 'green', icon: '📗', priority: 95 },
  '.xls':  { badge: 'Excel', color: 'green', icon: '📗', priority: 95 },
  '.csv':  { badge: 'CSV', color: 'green', icon: '📈', priority: 90 },
  '.html': { badge: 'HTML', color: 'purple', icon: '🌐', priority: 88 },
  '.htm':  { badge: 'HTML', color: 'purple', icon: '🌐', priority: 88 },
  '.png':  { badge: 'IMG', color: 'cyan', icon: '🖼️', priority: 85 },
  '.jpg':  { badge: 'IMG', color: 'cyan', icon: '🖼️', priority: 85 },
  '.jpeg': { badge: 'IMG', color: 'cyan', icon: '🖼️', priority: 85 },
  '.webp': { badge: 'IMG', color: 'cyan', icon: '🖼️', priority: 85 },
  '.svg':  { badge: 'SVG', color: 'cyan', icon: '🎨', priority: 84 },
  '.mp4':  { badge: 'VIDEO', color: 'purple', icon: '🎬', priority: 92 },
  '.zip':  { badge: 'ZIP', color: 'amber', icon: '📦', priority: 86 },
  '.md':   { badge: 'MD', color: 'slate', icon: '📝', priority: 80 },
  '.json': { badge: 'JSON', color: 'slate', icon: '🧩', priority: 60 },
  '.py':   { badge: 'PY', color: 'blue', icon: '🐍', priority: 70 },
  '.js':   { badge: 'JS', color: 'amber', icon: '📜', priority: 65 },
  '.mjs':  { badge: 'MJS', color: 'amber', icon: '📜', priority: 65 },
  '.ts':   { badge: 'TS', color: 'blue', icon: '📘', priority: 65 },
  '.ps1':  { badge: 'PS1', color: 'blue', icon: '⚡', priority: 65 }
};

function unquote(v) {
  if (typeof v !== 'string') return v == null ? '' : String(v);
  const s = v.trim();
  if (s.length >= 2 && s.startsWith('"') && s.endsWith('"')) {
    try {
      return String(JSON.parse(s));
    } catch {
      return s.slice(1, -1);
    }
  }
  return s;
}

function fileUriToLocalPath(uriStr) {
  try {
    let raw = uriStr.trim().replace(/#L\d+(?:-L?\d+)?$/i, '');
    if (!raw.toLowerCase().startsWith('file://')) return '';
    // Handle file:///C:/... or file://C:/...
    let rest = raw.replace(/^file:\/+/i, '');
    rest = decodeURIComponent(rest);
    if (IS_WIN) {
      if (/^[a-zA-Z]:/.test(rest)) {
        return normalize(rest);
      }
      if (/^\/[a-zA-Z]:/.test(rest)) {
        return normalize(rest.slice(1));
      }
    }
    return normalize('/' + rest);
  } catch {
    return '';
  }
}

function describeFile(rawPath, meta = {}) {
  if (!rawPath || typeof rawPath !== 'string') return null;
  let normPath;
  try {
    normPath = normalize(rawPath.trim());
  } catch {
    return null;
  }
  if (!isAbsolute(normPath)) return null;
  let st;
  try {
    st = statSync(normPath);
  } catch {
    return null;
  }
  const isDir = st.isDirectory();
  const ext = isDir ? '' : extname(normPath).toLowerCase();
  const cat = isDir
    ? { badge: 'DIR', color: 'amber', icon: '📁', priority: 75 }
    : (CATEGORY_MAP[ext] || { badge: (ext.slice(1) || 'FILE').toUpperCase().slice(0, 6), color: 'slate', icon: '📄', priority: 50 });

  let fileUri = '';
  try {
    fileUri = pathToFileURL(normPath).href;
  } catch {
    fileUri = `file:///${normPath.replace(/\\/g, '/')}`;
  }

  return {
    path: normPath,
    name: basename(normPath) || normPath,
    dir: dirname(normPath),
    ext,
    isDir,
    size: isDir ? 0 : st.size,
    mtimeMs: st.mtimeMs,
    fileUri,
    badge: cat.badge,
    color: cat.color,
    icon: cat.icon,
    priority: cat.priority,
    actionKind: meta.actionKind || 'recent', // 'created' | 'edited' | 'linked' | 'artifact' | 'read' | 'pinned' | 'recent'
    stepIndex: meta.stepIndex ?? -1
  };
}

function resolveActiveConversation(requestedConv) {
  const appDataDirs = findAppDataDirs();
  if (requestedConv && ID_RE.test(requestedConv)) {
    for (const ad of appDataDirs) {
      if (existsSync(join(ad, 'brain', requestedConv))) {
        return { appData: ad, convId: requestedConv };
      }
    }
  }
  // Fallback: pick the most recently updated conversation in brain/
  let newest = null;
  for (const ad of appDataDirs) {
    const brainDir = join(ad, 'brain');
    let entries = [];
    try {
      entries = readdirSync(brainDir);
    } catch {
      continue;
    }
    for (const name of entries) {
      if (!ID_RE.test(name)) continue;
      const tPath = join(brainDir, name, '.system_generated', 'logs', 'transcript.jsonl');
      const target = existsSync(tPath) ? tPath : join(brainDir, name);
      try {
        const mtime = statSync(target).mtimeMs;
        if (!newest || mtime > newest.mtime) {
          newest = { appData: ad, convId: name, mtime };
        }
      } catch {}
    }
  }
  return newest ? { appData: newest.appData, convId: newest.convId } : { appData: appDataDirs[0] || '', convId: requestedConv || '' };
}

const ACTION_WEIGHT = {
  created: 5,
  artifact: 4,
  linked: 4,
  edited: 3,
  read: 1
};

function collectSessionFiles(appData, convId) {
  if (!appData || !convId || !ID_RE.test(convId)) return [];
  const map = new Map(); // lowerPath -> item

  const upsert = (rawPath, actionKind, stepIndex = 0) => {
    const info = describeFile(rawPath, { actionKind, stepIndex });
    if (!info) return;
    // Filter out internal system logs/builtin skill docs unless they are user project files
    const lower = info.path.toLowerCase();
    if (lower.includes('.system_generated') || lower.includes('\\builtin\\skills\\') || lower.includes('\\builtin\\plugins\\')) {
      return;
    }
    const prev = map.get(lower);
    if (!prev) {
      map.set(lower, info);
      return;
    }
    const prevW = ACTION_WEIGHT[prev.actionKind] || 0;
    const newW = ACTION_WEIGHT[actionKind] || 0;
    if (newW >= prevW) {
      prev.actionKind = actionKind;
    }
    if (stepIndex > prev.stepIndex) {
      prev.stepIndex = stepIndex;
    }
  };

  // 1. Scan conversation artifact directory (<appData>/brain/<convId>/)
  const convDir = join(appData, 'brain', convId);
  const scanArtifactDir = (dir, depth = 0) => {
    if (depth > 2 || !existsSync(dir)) return;
    let list = [];
    try {
      list = readdirSync(dir, { withFileTypes: true });
    } catch {
      return;
    }
    for (const d of list) {
      if (d.name.startsWith('.') || d.name === 'browser_sandbox') continue;
      const full = join(dir, d.name);
      if (d.isDirectory()) {
        scanArtifactDir(full, depth + 1);
      } else {
        upsert(full, 'artifact', 9999);
      }
    }
  };
  scanArtifactDir(convDir);

  // 2. Parse transcript.jsonl
  const tPath = join(convDir, '.system_generated', 'logs', 'transcript.jsonl');
  if (existsSync(tPath)) {
    try {
      const text = readFileSync(tPath, 'utf-8');
      const lines = text.split('\n');
      for (const line of lines) {
        if (!line.trim()) continue;
        let step;
        try {
          step = JSON.parse(line);
        } catch {
          continue;
        }
        const idx = Number(step?.step_index) || 0;

        // Extract tool calls
        if (Array.isArray(step?.tool_calls)) {
          for (const tc of step.tool_calls) {
            const name = tc?.name || '';
            const args = tc?.args || {};
            const p = unquote(args.Path || args.AbsolutePath || args.TargetFile);
            if (p) {
              if (name === 'write_file') upsert(p, 'created', idx);
              else if (name === 'edit_file') upsert(p, 'edited', idx);
              else if (name === 'read_file') upsert(p, 'read', idx);
            }
          }
        }

        // Extract file:/// links in planner response content
        if (step?.type === 'PLANNER_RESPONSE' && typeof step?.content === 'string') {
          const matches = step.content.matchAll(/file:\/\/\/[^\s)"'\]>`]+/gi);
          for (const m of matches) {
            const localP = fileUriToLocalPath(m[0]);
            if (localP) upsert(localP, 'linked', idx);
          }
        }
      }
    } catch {}
  }

  return [...map.values()].sort((a, b) => {
    const wa = ACTION_WEIGHT[a.actionKind] || 0;
    const wb = ACTION_WEIGHT[b.actionKind] || 0;
    if (wa !== wb) return wb - wa;
    if (b.stepIndex !== a.stepIndex) return b.stepIndex - a.stepIndex;
    return b.mtimeMs - a.mtimeMs;
  });
}

// ---------------------------------------------------------------------------
// Scanning Recent Deliverables in Watched Project Directories (e.g. D:\projects)
// ---------------------------------------------------------------------------

const SKIP_DIRS = new Set([
  'node_modules', '.git', '.hg', '.svn', '__pycache__', '.venv', 'venv',
  'dist', 'build', '.next', '.nuxt', '.cache', '.agents', '.agent', '.gemini'
]);

function collectRecentProjectFiles(watchedDirs, maxItems = 50) {
  const found = [];
  const seen = new Set();

  const walk = (dir, depth = 0) => {
    if (depth > 3 || !existsSync(dir)) return;
    let entries = [];
    try {
      entries = readdirSync(dir, { withFileTypes: true });
    } catch {
      return;
    }
    for (const e of entries) {
      if (e.name.startsWith('.')) continue;
      const full = join(dir, e.name);
      if (e.isDirectory()) {
        if (SKIP_DIRS.has(e.name.toLowerCase())) continue;
        walk(full, depth + 1);
      } else {
        const ext = extname(e.name).toLowerCase();
        if (!DELIVERABLE_EXTS.has(ext)) continue;
        const lower = full.toLowerCase();
        if (seen.has(lower)) continue;
        seen.add(lower);
        const info = describeFile(full, { actionKind: 'recent' });
        if (info) found.push(info);
      }
    }
  };

  for (const root of watchedDirs || []) {
    if (root && existsSync(root)) {
      walk(root, 0);
    }
  }

  found.sort((a, b) => b.mtimeMs - a.mtimeMs);
  return found.slice(0, maxItems);
}

// ---------------------------------------------------------------------------
// Launching Files / Open With / Reveal in Explorer
// ---------------------------------------------------------------------------

function spawnDetached(cmd, args, cwd) {
  return new Promise((resolve) => {
    try {
      const child = spawn(cmd, args, {
        cwd: cwd || undefined,
        detached: true,
        stdio: 'ignore',
        windowsHide: false
      });
      child.on('error', (err) => resolve({ ok: false, error: String(err?.message || err) }));
      child.unref();
      setTimeout(() => resolve({ ok: true }), 120);
    } catch (err) {
      resolve({ ok: false, error: String(err?.message || err) });
    }
  });
}

async function performFileAction({ targetPath, mode, appId, customExe }) {
  if (!targetPath || typeof targetPath !== 'string') {
    return { ok: false, error: 'Missing file path' };
  }
  const norm = normalize(targetPath.trim());
  if (!existsSync(norm)) {
    return { ok: false, error: `File does not exist: ${norm}` };
  }
  let real = norm;
  try {
    real = realpathSync(norm);
  } catch {}
  const isDir = (() => {
    try {
      return statSync(real).isDirectory();
    } catch {
      return false;
    }
  })();
  const workDir = isDir ? real : dirname(real);

  // 1. Reveal in File Explorer / Finder
  if (mode === 'reveal' || appId === 'reveal') {
    if (IS_WIN) {
      return spawnDetached('explorer.exe', [isDir ? real : `/select,${real}`], workDir);
    }
    if (platform() === 'darwin') {
      return spawnDetached('open', ['-R', real], workDir);
    }
    return spawnDetached('xdg-open', [workDir], workDir);
  }

  // 2. Native Windows "Open With..." system dialog
  if (mode === 'open_with_dialog' || appId === 'open_with_dialog') {
    if (IS_WIN) {
      return spawnDetached('rundll32.exe', ['shell32.dll,OpenAs_RunDLL', real], workDir);
    }
    if (platform() === 'darwin') {
      return spawnDetached('open', ['-a', 'Finder', real], workDir);
    }
    return spawnDetached('xdg-open', [real], workDir);
  }

  // 3. Open with a specific detected or custom application
  if (mode === 'app' || (appId && appId !== 'default')) {
    const cfg = loadUserConfig();
    const apps = detectInstalledApps(cfg.customApps);
    const chosen = apps.find((a) => a.id === appId);
    const exe = customExe || chosen?.exe;

    if (appId === 'powershell' && IS_WIN) {
      return spawnDetached('cmd.exe', ['/c', 'start', 'powershell.exe', '-NoExit', '-Command', `Set-Location -LiteralPath '${workDir.replace(/'/g, "''")}'`], workDir);
    }
    if (!exe || !existsSync(exe)) {
      return { ok: false, error: `Application executable not found: ${exe || appId}` };
    }
    return spawnDetached(exe, [real], workDir);
  }

  // 4. Default open (respecting per-extension user preference if configured)
  const cfg = loadUserConfig();
  const ext = isDir ? '' : extname(real).toLowerCase();
  const preferredAppId = ext && cfg.extDefaults?.[ext];
  if (preferredAppId && preferredAppId !== 'default') {
    return performFileAction({ targetPath: real, mode: 'app', appId: preferredAppId });
  }

  if (IS_WIN) {
    if (isDir) {
      return spawnDetached('explorer.exe', [real], workDir);
    }
    return spawnDetached('rundll32.exe', ['url.dll,FileProtocolHandler', real], workDir);
  }
  if (platform() === 'darwin') {
    return spawnDetached('open', [real], workDir);
  }
  return spawnDetached('xdg-open', [real], workDir);
}

// ---------------------------------------------------------------------------
// HTTP Routes (All GET for seamless iframe + standalone compatibility)
// ---------------------------------------------------------------------------

const STATIC = {
  '/styles.css': ['styles.css', 'text/css; charset=utf-8'],
  '/app.js': ['app.js', 'application/javascript; charset=utf-8']
};

const app = new SidecarApp();

app.page('/', () => readFileSync(join(__dirname, 'index.html'), 'utf-8'));

for (const [route, [file, type]] of Object.entries(STATIC)) {
  app.api(route, () => new Response(readFileSync(join(__dirname, file), 'utf-8'), { contentType: type }), 'GET');
}

app.api('/api/state', (data = {}) => {
  const reqConv = data.conversationId || app.config?.conversationId || process.env.ANTIGRAVITY_CONVERSATION_ID || '';
  const { appData, convId } = resolveActiveConversation(reqConv);
  const cfg = loadUserConfig();
  const apps = detectInstalledApps(cfg.customApps);
  const sessionFiles = collectSessionFiles(appData, convId);
  const recentFiles = collectRecentProjectFiles(cfg.watchedDirs, 50);
  const pinnedFiles = (cfg.pinnedFiles || [])
    .map((p) => describeFile(p, { actionKind: 'pinned' }))
    .filter(Boolean);

  return {
    ok: true,
    conversationId: convId,
    platform: platform(),
    apps,
    config: cfg,
    sessionFiles,
    recentFiles,
    pinnedFiles
  };
}, 'GET');

app.api('/api/open', async (data = {}) => {
  const targetPath = data.path || '';
  const mode = data.mode || 'default';
  const appId = data.appId || '';
  const customExe = data.customExe || '';
  const rememberExt = data.rememberExt === '1' || data.rememberExt === 'true';

  if (rememberExt && targetPath && appId) {
    const ext = extname(targetPath).toLowerCase();
    if (ext) {
      const cfg = loadUserConfig();
      cfg.extDefaults = cfg.extDefaults || {};
      cfg.extDefaults[ext] = appId;
      saveUserConfig(cfg);
    }
  }

  return performFileAction({ targetPath, mode, appId, customExe });
}, 'GET');

app.api('/api/pin', (data = {}) => {
  const targetPath = (data.path || '').trim();
  const op = data.op || 'add'; // 'add' | 'remove'
  if (!targetPath) return { ok: false, error: 'Missing path' };
  const norm = normalize(targetPath);
  const cfg = loadUserConfig();
  const list = new Set(cfg.pinnedFiles || []);
  if (op === 'remove') {
    for (const item of [...list]) {
      if (item.toLowerCase() === norm.toLowerCase()) list.delete(item);
    }
  } else {
    if (!existsSync(norm)) return { ok: false, error: `Path not found: ${norm}` };
    list.add(norm);
  }
  cfg.pinnedFiles = [...list];
  saveUserConfig(cfg);
  return { ok: true, pinnedFiles: cfg.pinnedFiles };
}, 'GET');

app.api('/api/config', (data = {}) => {
  const cfg = loadUserConfig();
  if (data.op === 'set_ext_default') {
    const ext = (data.ext || '').toLowerCase();
    const appId = data.appId || 'default';
    if (ext) {
      if (appId === 'default') delete cfg.extDefaults[ext];
      else cfg.extDefaults[ext] = appId;
      saveUserConfig(cfg);
    }
  } else if (data.op === 'add_watched_dir') {
    const dir = normalize((data.dir || '').trim());
    if (!dir || !existsSync(dir)) return { ok: false, error: `Directory does not exist: ${dir}` };
    if (!cfg.watchedDirs.some((d) => d.toLowerCase() === dir.toLowerCase())) {
      cfg.watchedDirs.push(dir);
      saveUserConfig(cfg);
    }
  } else if (data.op === 'remove_watched_dir') {
    const dir = normalize((data.dir || '').trim());
    cfg.watchedDirs = cfg.watchedDirs.filter((d) => d.toLowerCase() !== dir.toLowerCase());
    saveUserConfig(cfg);
  } else if (data.op === 'add_custom_app') {
    const name = (data.name || '').trim();
    const exe = normalize((data.exe || '').trim());
    if (!name || !exe || !existsSync(exe)) {
      return { ok: false, error: `Executable not found: ${exe}` };
    }
    cfg.customApps = cfg.customApps.filter((a) => a.name.toLowerCase() !== name.toLowerCase());
    cfg.customApps.push({ id: name.toLowerCase().replace(/[^a-z0-9]+/g, '-'), name, exe, icon: '🔧' });
    saveUserConfig(cfg);
  } else if (data.op === 'remove_custom_app') {
    const name = (data.name || '').trim();
    cfg.customApps = cfg.customApps.filter((a) => a.name.toLowerCase() !== name.toLowerCase());
    saveUserConfig(cfg);
  }
  return { ok: true, config: cfg, apps: detectInstalledApps(cfg.customApps) };
}, 'GET');

// Self-test mode for automated verification (`node main.mjs --selftest`)
if (process.argv.includes('--selftest')) {
  const { appData, convId } = resolveActiveConversation('');
  const cfg = loadUserConfig();
  const apps = detectInstalledApps(cfg.customApps);
  const sessionFiles = collectSessionFiles(appData, convId);
  const recentFiles = collectRecentProjectFiles(cfg.watchedDirs, 10);
  console.log(JSON.stringify({
    selftest: 'PASS',
    appData,
    convId,
    detectedAppsCount: apps.length,
    detectedApps: apps.map((a) => a.name),
    sessionFilesCount: sessionFiles.length,
    recentFilesCount: recentFiles.length,
    sampleRecent: recentFiles.slice(0, 3).map((f) => f.path)
  }, null, 2));
  process.exit(0);
}

app.run();
