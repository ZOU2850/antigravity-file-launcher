#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
File Launcher Sidecar Backend (Python 3 Standard Library Edition) for Google Antigravity.

Zero external dependencies. Implements the exact Antigravity Sidecar HTTP contract:
- Binds to 127.0.0.1:$ANTIGRAVITY_SIDECAR_WEB_PORT
- Serves /, /preload.js, /styles.css, /app.js
- Serves /api/state, /api/open, /api/pin, /api/config, and /_sidecar/* agentapi bridges
- Automatically discovers files from active conversation transcript.jsonl + brain/<conv>/ artifacts
- Automatically scans recent deliverables in D:\\projects (and custom watched dirs)
- Launches files with default app, Windows native "Open With..." dialog (OpenAs_RunDLL),
  detected desktop apps (Antigravity, VS Code, Cursor, WPS, Office, Edge, Chrome, Notepad, PowerShell),
  or reveals in File Explorer (explorer.exe /select,<path>).
"""

import json
import os
import platform
import re
import sqlite3
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import dsh_sync

IS_WIN = platform.system().lower() == "windows"
ID_RE = re.compile(r"^[0-9a-f-]{8,}$", re.IGNORECASE)

# 默认只展示对普通用户可读的成品文档与媒体文件；代码/配置/设计稿/文件夹在侧边栏全量发现并可多维筛选
READABLE_EXTS = set(dsh_sync.DELIVERABLE_DOC_EXTS) | set(dsh_sync.IMAGE_EXTS) | {".mp4", ".mp3", ".wav", ".mkv", ".mov"}
DELIVERABLE_EXTS = READABLE_EXTS | {
    ".py", ".js", ".mjs", ".ts", ".tsx", ".jsx", ".css", ".scss", ".json", ".ps1",
    ".xml", ".yaml", ".yml", ".zip", ".7z", ".rar", ".sql", ".fig", ".psd",
}

CATEGORY_MAP = {
    ".pptx": {"badge": "PPT", "color": "amber", "icon": "📊", "priority": 100},
    ".ppt":  {"badge": "PPT", "color": "amber", "icon": "📊", "priority": 100},
    ".pdf":  {"badge": "PDF", "color": "red", "icon": "📕", "priority": 95},
    ".docx": {"badge": "Word", "color": "blue", "icon": "📘", "priority": 95},
    ".doc":  {"badge": "Word", "color": "blue", "icon": "📘", "priority": 95},
    ".xlsx": {"badge": "Excel", "color": "green", "icon": "📗", "priority": 95},
    ".xls":  {"badge": "Excel", "color": "green", "icon": "📗", "priority": 95},
    ".csv":  {"badge": "CSV", "color": "green", "icon": "📈", "priority": 90},
    ".html": {"badge": "HTML", "color": "purple", "icon": "🌐", "priority": 88},
    ".htm":  {"badge": "HTML", "color": "purple", "icon": "🌐", "priority": 88},
    ".png":  {"badge": "IMG", "color": "cyan", "icon": "🖼️", "priority": 85},
    ".jpg":  {"badge": "IMG", "color": "cyan", "icon": "🖼️", "priority": 85},
    ".jpeg": {"badge": "IMG", "color": "cyan", "icon": "🖼️", "priority": 85},
    ".webp": {"badge": "IMG", "color": "cyan", "icon": "🖼️", "priority": 85},
    ".svg":  {"badge": "SVG", "color": "cyan", "icon": "🎨", "priority": 84},
    ".mp4":  {"badge": "VIDEO", "color": "purple", "icon": "🎬", "priority": 92},
    ".zip":  {"badge": "ZIP", "color": "amber", "icon": "📦", "priority": 86},
    ".md":   {"badge": "MD", "color": "slate", "icon": "📝", "priority": 80},
    ".json": {"badge": "JSON", "color": "slate", "icon": "🧩", "priority": 60},
    ".py":   {"badge": "PY", "color": "blue", "icon": "🐍", "priority": 70},
    ".js":   {"badge": "JS", "color": "amber", "icon": "📜", "priority": 65},
    ".mjs":  {"badge": "MJS", "color": "amber", "icon": "📜", "priority": 65},
    ".ts":   {"badge": "TS", "color": "blue", "icon": "📘", "priority": 65},
    ".ps1":  {"badge": "PS1", "color": "blue", "icon": "⚡", "priority": 65},
}

SKIP_DIRS = {
    "node_modules", ".git", ".hg", ".svn", "__pycache__", ".venv", "venv",
    "dist", "build", ".next", ".nuxt", ".cache", ".agents", ".agent", ".gemini"
}
NON_PROJECT_SUBDIRS = SKIP_DIRS | {
    "archived_docs", "pinned_protected_files", "fl_preview", ".fl_preview",
    "file_launcher_preview", ".file_launcher_preview", "tmp", "temp",
}

ACTION_WEIGHT = {
    "created": 5,
    "artifact": 4,
    "linked": 4,
    "edited": 3,
    "read": 1,
}


def find_app_data_dirs():
    data_dir = os.environ.get("ANTIGRAVITY_EXECUTABLE_DATA_DIR", "")
    if data_dir:
        curr = Path(data_dir).resolve()
        for parent in [curr] + list(curr.parents):
            if parent.name == "sidecar_data":
                app_data = parent.parent
                if (app_data / "brain").exists():
                    return [app_data]
    env_app = os.environ.get("ANTIGRAVITY_APP_DATA_DIR", "")
    if env_app and (Path(env_app) / "brain").exists():
        return [Path(env_app).resolve()]
    root = Path.home() / ".gemini"
    found = []
    for name in ("antigravity", "antigravity-ide", "antigravity-cli"):
        cand = root / name
        if (cand / "brain").exists():
            found.append(cand)
    return found


def get_ipc_path():
    dirs = find_app_data_dirs()
    base = dirs[0] if dirs else (Path.home() / ".gemini" / "antigravity")
    base.mkdir(parents=True, exist_ok=True)
    return base / "file_launcher_ipc.json"


QUEUE_LOCK = threading.RLock()
QUEUE_COND = threading.Condition(QUEUE_LOCK)
ACTION_SEQ = 0


def read_ipc_state():
    p = get_ipc_path()
    default_ipc = {
        "lastSidecarSeen": 0.0,
        "lastSidecarVisible": 0.0,
        "pendingInternalOpen": None,
        "queue": [],
        "ackedIds": {},
        "chatAttachedByConv": {},
    }
    if not p.exists():
        return default_ipc
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return default_ipc
        for k, v in default_ipc.items():
            if k not in raw or raw[k] is None:
                raw[k] = v
        return raw
    except Exception:
        return default_ipc


def write_ipc_state(state_obj):
    p = get_ipc_path()
    try:
        p.write_text(json.dumps(state_obj, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def get_config_path():
    dirs = find_app_data_dirs()
    base = dirs[0] if dirs else (Path.home() / ".gemini" / "antigravity")
    base.mkdir(parents=True, exist_ok=True)
    return base / "file_launcher_config.json"


def get_data_base_dir():
    if IS_WIN and Path("D:\\projects").exists():
        return Path("D:\\projects")
    return Path.home() / "Documents" / "AntigravityFileLauncher"


def get_store_paths():
    cfg_dir = get_config_path().parent
    paths = dsh_sync.get_store_paths(cfg_dir)
    # 保持向后兼容：默认归档根目录放在 D:\projects\Archived_Docs (或 Documents/AntigravityFileLauncher/Archived_Docs)
    paths["defaultArchiveDir"] = get_data_base_dir() / "Archived_Docs"
    paths["pinnedManifestDir"] = get_data_base_dir() / "Pinned_Protected_Files"
    return paths


def default_config():
    default_dir = "D:\\projects" if (IS_WIN and Path("D:\\projects").exists()) else str(Path.home() / "Desktop")
    cfg = dsh_sync.default_settings()
    cfg["watchedDirs"] = [default_dir]
    return cfg


import shutil as _shutil


def sync_anti_compaction_manifest(pinned_paths, active_conv_id=""):
    """
    Persist a human- and AI-readable manifest of pinned (anti-compaction protected) files
    both in <data_base>/Pinned_Protected_Files and in the active conversation brain directory,
    so context compaction NEVER loses track of starred files.
    """
    prot_dir = get_data_base_dir() / "Pinned_Protected_Files"
    prot_dir.mkdir(parents=True, exist_ok=True)

    lines = [
        "# ★ 防压缩保护文件清单 (Pinned Anti-Compaction Files)",
        "",
        "> 以下文件已被用户标记为「收藏保留（防压缩）」。即使对话发生上下文压缩（Context Compaction），也必须始终保留并优先参考这些文件：",
        "",
    ]
    valid_count = 0
    for raw_p in pinned_paths or []:
        norm = os.path.normpath(raw_p)
        if not os.path.exists(norm):
            continue
        valid_count += 1
        name = os.path.basename(norm)
        # If the file lives in a temporary/hidden upload folder, also keep a safe backup copy in prot_dir
        backup_note = ""
        if ".user_uploaded" in norm.lower() or "\\scratch\\" in norm.lower():
            try:
                dst = prot_dir / name
                if os.path.abspath(norm).lower() != os.path.abspath(str(dst)).lower():
                    _shutil.copy2(norm, dst)
                backup_note = f" (已备份至 `{dst}`)"
            except Exception:
                pass
        lines.append(f"- **{name}**: `{norm}`{backup_note}")

    if valid_count == 0:
        lines.append("- （当前暂无收藏保护文件）")

    manifest_text = "\n".join(lines) + "\n"
    try:
        (prot_dir / "PINNED_FILES_MANIFEST.md").write_text(manifest_text, encoding="utf-8")
    except Exception:
        pass

    if active_conv_id and ID_RE.match(active_conv_id):
        for ad in find_app_data_dirs():
            conv_dir = Path(ad) / "brain" / active_conv_id
            if conv_dir.exists():
                try:
                    (conv_dir / "PINNED_FILES_MANIFEST.md").write_text(manifest_text, encoding="utf-8")
                except Exception:
                    pass


def perform_batch_action(op, paths, conv_id=""):
    """
    Execute composite actions on one or more files:
    - pin: Star & protect files from context compaction
    - unpin: Remove from starred list
    - archive: Copy/archive files into D:\\projects\\Archived_Docs and record in archivedFiles
    - unarchive: Remove from archived list
    - copy_chat_refs: Copy @path references to Windows clipboard for instant pasting into chat
    """
    cfg = load_user_config()
    pins = list(cfg.get("pinnedFiles") or [])
    archived = list(cfg.get("archivedFiles") or [])
    norm_paths = [os.path.normpath(p.strip()) for p in (paths or []) if p and isinstance(p, str) and p.strip()]
    norm_paths = [p for p in norm_paths if os.path.exists(p)]

    if not norm_paths and op not in ("unpin", "unarchive", "forget"):
        return {"ok": False, "error": "未找到有效的文件路径"}

    sp = get_store_paths()

    if op == "pin":
        for p in norm_paths:
            if not any(x.lower() == p.lower() for x in pins):
                pins.insert(0, p)
        cfg["pinnedFiles"] = pins
        save_user_config(cfg)
        sync_anti_compaction_manifest(pins, conv_id)
        return {"ok": True, "op": op, "count": len(norm_paths), "pinnedFiles": pins}

    if op == "unpin":
        raw_Checks = {os.path.normpath(p.strip()).lower() for p in (paths or []) if p}
        pins = [x for x in pins if x.lower() not in raw_Checks]
        cfg["pinnedFiles"] = pins
        save_user_config(cfg)
        sync_anti_compaction_manifest(pins, conv_id)
        return {"ok": True, "op": op, "pinnedFiles": pins}

    if op == "archive":
        res = dsh_sync.archive_files_dsh(
            paths or [],
            sp["config"],
            sp["archiveIndex"],
            sp["defaultArchiveDir"],
        )
        return {
            "ok": True,
            "op": op,
            "count": len(res.get("copied") or []),
            "copied": res.get("copied") or [],
            "skipped": res.get("skipped") or [],
            "archiveDir": res.get("archivedDir") or str(sp["defaultArchiveDir"]),
            "archivedFiles": (res.get("config") or {}).get("archivedFiles") or [],
        }

    if op == "unarchive":
        res = dsh_sync.unarchive_files_dsh(
            paths or [],
            sp["config"],
            sp["archiveIndex"],
        )
        return {
            "ok": True,
            "op": op,
            "archivedFiles": (res.get("config") or {}).get("archivedFiles") or [],
        }

    if op == "forget":
        res = dsh_sync.forget_files_dsh(
            paths or [],
            sp["config"],
            sp["archiveIndex"],
            sp["deletedIndex"],
            sp["sentIndex"],
            pinned_manifest_sync_cb=lambda new_pins: sync_anti_compaction_manifest(new_pins, conv_id),
        )
        return res

    if op in ("attach", "copy_chat_refs"):
        files = []
        for p in norm_paths:
            side = build_side_uri(p, conv_id)
            if side.get("ok") and side.get("file"):
                item = dict(side["file"])
                item["openUri"] = side.get("uri") or item.get("fileUri") or ""
                item["sideKind"] = side.get("kind") or "external"
                files.append(item)
        return {"ok": True, "op": "attach", "count": len(files), "files": files}

    return {"ok": False, "error": f"未知操作: {op}"}


def load_user_config():
    p = get_config_path()
    if not p.exists():
        return default_config()
    cfg = dsh_sync.load_settings(p)
    # 兼容非常老的无 watchedDirs 配置文件：仅当键缺失（非用户显式清空）时补回默认目录
    try:
        raw = dsh_sync.read_json_safe(p, {})
        if isinstance(raw, dict) and "watchedDirs" not in raw:
            cfg["watchedDirs"] = default_config()["watchedDirs"]
    except Exception:
        pass
    return cfg


def save_user_config(cfg):
    try:
        dsh_sync.save_settings(get_config_path(), cfg)
        return True
    except Exception:
        return False



LAST_SIDECAR_SEEN = 0.0
PENDING_INTERNAL_OPEN = None
INTERNAL_LOCK = None

_CACHED_APPS = None
_CACHED_APPS_AT = 0.0


def detect_installed_apps(custom_apps=None):
    global _CACHED_APPS, _CACHED_APPS_AT
    now = time.time()
    if _CACHED_APPS is not None and (now - _CACHED_APPS_AT) < 30:
        return _merge_custom_apps(_CACHED_APPS, custom_apps or [])

    apps = [
        {
            "id": "default",
            "name": "系统默认程序 (Default)",
            "icon": "⚡",
            "desc": "使用操作系统关联的默认软件直接打开",
            "builtin": True,
        },
        {
            "id": "open_with_dialog",
            "name": "选择其他应用… (系统打开方式弹窗)",
            "icon": "🪟",
            "desc": "唤起 Windows 原生“你要如何打开这个文件？”选择窗口",
            "builtin": True,
        },
        {
            "id": "reveal",
            "name": "在资源管理器中定位 (Explorer)",
            "icon": "📂",
            "desc": "打开所在文件夹并高亮选中该文件",
            "builtin": True,
        },
    ]

    if IS_WIN:
        local_app = os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
        prog = os.environ.get("ProgramFiles", "C:\\Program Files")
        prog86 = os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)")
        sys_root = os.environ.get("SystemRoot", "C:\\Windows")

        candidates = [
            ("antigravity", "Antigravity", "🚀", [
                os.path.join(local_app, "Programs", "antigravity", "Antigravity.exe"),
                os.path.join(local_app, "Programs", "Antigravity IDE", "Antigravity IDE.exe"),
            ]),
            ("vscode", "VS Code", "📘", [
                os.path.join(local_app, "Programs", "Microsoft VS Code", "Code.exe"),
                os.path.join(prog, "Microsoft VS Code", "Code.exe"),
                "D:\\Program Files\\Microsoft VS Code\\Code.exe",
            ]),
            ("cursor", "Cursor", "🖱️", [
                os.path.join(local_app, "Programs", "cursor", "Cursor.exe"),
            ]),
            ("wps", "WPS Office", "📄", [
                os.path.join(local_app, "Kingsoft", "WPS Office", "ksolaunch.exe"),
                os.path.join(prog, "Kingsoft", "WPS Office", "ksolaunch.exe"),
                os.path.join(prog86, "Kingsoft", "WPS Office", "ksolaunch.exe"),
            ]),
            ("powerpoint", "PowerPoint", "📊", [
                os.path.join(prog, "Microsoft Office", "root", "Office16", "POWERPNT.EXE"),
                os.path.join(prog86, "Microsoft Office", "root", "Office16", "POWERPNT.EXE"),
            ]),
            ("excel", "Excel", "📗", [
                os.path.join(prog, "Microsoft Office", "root", "Office16", "EXCEL.EXE"),
                os.path.join(prog86, "Microsoft Office", "root", "Office16", "EXCEL.EXE"),
            ]),
            ("word", "Word", "📘", [
                os.path.join(prog, "Microsoft Office", "root", "Office16", "WINWORD.EXE"),
                os.path.join(prog86, "Microsoft Office", "root", "Office16", "WINWORD.EXE"),
            ]),
            ("edge", "Microsoft Edge", "🌐", [
                os.path.join(prog86, "Microsoft", "Edge", "Application", "msedge.exe"),
                os.path.join(prog, "Microsoft", "Edge", "Application", "msedge.exe"),
            ]),
            ("chrome", "Google Chrome", "🌍", [
                os.path.join(prog, "Google", "Chrome", "Application", "chrome.exe"),
                os.path.join(prog86, "Google", "Chrome", "Application", "chrome.exe"),
                os.path.join(local_app, "Google", "Chrome", "Application", "chrome.exe"),
            ]),
            ("notepadpp", "Notepad++", "📝", [
                os.path.join(prog, "Notepad++", "notepad++.exe"),
                os.path.join(prog86, "Notepad++", "notepad++.exe"),
                "D:\\Program Files\\Notepad++\\notepad++.exe",
            ]),
            ("typora", "Typora", "✍️", [
                os.path.join(prog, "Typora", "Typora.exe"),
                os.path.join(local_app, "Programs", "Typora", "Typora.exe"),
            ]),
            ("notepad", "记事本 (Notepad)", "🗒️", [
                os.path.join(sys_root, "System32", "notepad.exe"),
            ]),
            ("powershell", "PowerShell (在此目录打开)", "💻", [
                os.path.join(sys_root, "System32", "WindowsPowerShell", "v1.0", "powershell.exe"),
            ]),
        ]

        for cid, cname, cicon, cpaths in candidates:
            hit = next((cp for cp in cpaths if os.path.exists(cp)), None)
            if hit:
                apps.append({
                    "id": cid,
                    "name": cname,
                    "icon": cicon,
                    "exe": hit,
                    "desc": hit,
                })

    _CACHED_APPS = apps
    _CACHED_APPS_AT = now
    return _merge_custom_apps(apps, custom_apps or [])


def _merge_custom_apps(base_apps, custom_apps):
    out = list(base_apps)
    for ca in custom_apps:
        if not isinstance(ca, dict) or not ca.get("name") or not ca.get("exe"):
            continue
        out.append({
            "id": f"custom:{ca.get('id') or ca['name']}",
            "name": ca["name"],
            "icon": ca.get("icon") or "🔧",
            "exe": ca["exe"],
            "desc": ca["exe"],
            "custom": True,
        })
    return out


def unquote_arg(val):
    if not isinstance(val, str):
        return "" if val is None else str(val)
    s = val.strip()
    if len(s) >= 2 and s.startswith('"') and s.endswith('"'):
        try:
            return str(json.loads(s))
        except Exception:
            return s[1:-1]
    return s


def file_uri_to_local_path(uri_str):
    try:
        raw = re.sub(r"#L\d+(?:-L?\d+)?$", "", uri_str.strip(), flags=re.IGNORECASE)
        if not raw.lower().startswith("file://"):
            return ""
        rest = re.sub(r"^file:/+", "", raw, flags=re.IGNORECASE)
        rest = unquote(rest)
        if IS_WIN:
            if re.match(r"^[a-zA-Z]:", rest):
                return os.path.normpath(rest)
            if re.match(r"^/[a-zA-Z]:", rest):
                return os.path.normpath(rest[1:])
        return os.path.normpath("/" + rest)
    except Exception:
        return ""



FILE_TYPE_GROUPS = [
    ("word", "Word", {".docx", ".doc", ".odt", ".rtf"}),
    ("markdown", "Markdown", {".md", ".mdx", ".markdown"}),
    ("ppt", "PPT", {".pptx", ".ppt", ".odp", ".key"}),
    ("excel", "Excel", {".xls", ".xlsx", ".xlsm", ".csv", ".tsv", ".ods", ".numbers"}),
    ("pdf", "PDF", {".pdf"}),
    ("image", "图片", {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp", ".ico", ".tif", ".tiff", ".avif"}),
    ("text", "文本/配置", {".txt", ".log", ".ini", ".cfg", ".conf", ".env", ".yaml", ".yml", ".toml", ".xml", ".properties"}),
    ("web", "网页/样式", {".html", ".htm", ".css", ".scss", ".sass", ".less", ".vue", ".svelte", ".astro"}),
    ("media", "音视频", {".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a", ".mp4", ".mov", ".avi", ".mkv", ".webm"}),
    ("archive", "压缩包", {".zip", ".tar", ".gz", ".tgz", ".bz2", ".xz", ".7z", ".rar", ".zst"}),
    ("design", "设计稿", {".fig", ".sketch", ".xd", ".psd", ".ai", ".eps"}),
    ("database", "数据库", {".db", ".sqlite", ".sqlite3", ".mdb", ".accdb", ".parquet"}),
    ("executable", "可执行程序", {".exe", ".msi", ".app", ".dmg", ".pkg", ".deb", ".rpm", ".appimage"}),
    ("font", "字体", {".ttf", ".otf", ".woff", ".woff2", ".eot"}),
    ("disk", "磁盘镜像", {".iso", ".img", ".vhd", ".vhdx"}),
    ("binary", "二进制", {".bin", ".dll", ".so", ".dylib", ".wasm", ".o", ".a", ".lib", ".class", ".pyc"}),
    ("folder", "文件夹", set()),
]


def classify_extension(ext, is_dir=False):
    cat, _ = dsh_sync.classify_extension_full(ext, is_dir=is_dir)
    meta = dsh_sync.CATEGORY_META_UI.get(cat, ("其他", "slate", "📄", 50))
    e = (ext or "").lower()
    is_readable = bool(
        is_dir
        or e in dsh_sync.DELIVERABLE_DOC_EXTS
        or e in dsh_sync.IMAGE_EXTS
        or cat in {"media", "archive", "design"}
    )
    return cat, meta[0], is_readable


def describe_file(
    raw_path,
    action_kind="recent",
    step_index=-1,
    *,
    is_user_sent=False,
    allow_missing=False,
    last_known_size=0,
    last_known_mtime_ms=0,
    last_known_is_dir=False,
):
    return dsh_sync.build_file_item(
        raw_path,
        action_kind=action_kind,
        step_index=step_index,
        is_user_sent=is_user_sent,
        allow_missing=allow_missing,
        last_known_size=last_known_size,
        last_known_mtime_ms=last_known_mtime_ms,
        last_known_is_dir=last_known_is_dir,
    )


def resolve_active_conversation(requested_conv):
    if not requested_conv:
        requested_conv = os.environ.get("ANTIGRAVITY_CONVERSATION_ID", "")
    app_dirs = find_app_data_dirs()
    if requested_conv and ID_RE.match(requested_conv):
        for ad in app_dirs:
            if (ad / "brain" / requested_conv).exists():
                return ad, requested_conv

    newest = None
    for ad in app_dirs:
        brain_dir = ad / "brain"
        if not brain_dir.exists():
            continue
        try:
            for entry in os.scandir(brain_dir):
                if not entry.is_dir() or not ID_RE.match(entry.name):
                    continue
                t_path = Path(entry.path) / ".system_generated" / "logs" / "transcript.jsonl"
                target = t_path if t_path.exists() else Path(entry.path)
                try:
                    mtime = target.stat().st_mtime
                    if newest is None or mtime > newest[2]:
                        newest = (ad, entry.name, mtime)
                except Exception:
                    pass
        except Exception:
            pass

    if newest:
        return newest[0], newest[1]
    return (app_dirs[0] if app_dirs else Path.home() / ".gemini" / "antigravity"), (requested_conv or "")


_CONV_PROJECT_CACHE = {}


def parse_workspace_paths(raw_ws):
    """Parse workspaceUris JSON array or pipe-separated paths into normalized directory paths."""
    if not raw_ws:
        return []
    vals = []
    if isinstance(raw_ws, str):
        s = raw_ws.strip()
        if s.startswith("["):
            try:
                vals = json.loads(s)
            except Exception:
                vals = []
        else:
            vals = [x for x in s.split("|") if x]
    elif isinstance(raw_ws, list):
        vals = raw_ws
    out = []
    seen = set()
    for v in vals:
        if not isinstance(v, str) or not v.strip():
            continue
        p = file_uri_to_local_path(v) if v.strip().lower().startswith("file://") else os.path.normpath(v.strip())
        if p and os.path.exists(p):
            try:
                real = str(Path(p).resolve())
            except Exception:
                real = os.path.normpath(p)
            low = real.lower()
            if low not in seen:
                seen.add(low)
                out.append(real)
    return out


def discover_local_dir_roots(cfg):
    """Discover subdirectories inside watchedDirs as local folders (NOT Antigravity Projects)."""
    roots = []
    seen = set()
    for wd in (cfg.get("watchedDirs") or []):
        if not wd or not os.path.exists(wd):
            continue
        try:
            wd_real = str(Path(wd).resolve())
        except Exception:
            wd_real = os.path.normpath(wd)
        try:
            subs = []
            for entry in os.scandir(wd_real):
                if entry.is_dir() and not entry.name.startswith(".") and entry.name.lower() not in NON_PROJECT_SUBDIRS:
                    subs.append((entry.stat().st_mtime, entry.path))
            subs.sort(key=lambda x: x[0], reverse=True)
            for _, sp in subs:
                try:
                    real = str(Path(sp).resolve())
                except Exception:
                    real = os.path.normpath(sp)
                low = real.lower()
                name = os.path.basename(real) or real
                if low in seen or not os.path.isdir(real):
                    continue
                seen.add(low)
                roots.append({
                    "id": f"local:{low}",
                    "name": name,
                    "path": real,
                    "kind": "local_dir",
                    "isWorkspace": False,
                })
        except Exception:
            pass
    return roots


def discover_project_roots(cfg, workspace_paths=None):
    """Discover real Antigravity workspace roots cleanly; local watched subdirs use discover_local_dir_roots."""
    roots = []
    seen = set()
    for wp in (workspace_paths or []):
        try:
            real = str(Path(wp).resolve())
        except Exception:
            real = os.path.normpath(wp)
        low = real.lower()
        name = os.path.basename(real) or real
        if not os.path.isdir(real) or low in seen:
            continue
        seen.add(low)
        roots.append({
            "id": f"agproj:{low}",
            "name": name,
            "path": real,
            "kind": "project",
            "isWorkspace": True,
        })
    return roots


def load_sidebar_db_data(app_data, active_conv_id="", active_workspace_paths=None):
    """
    Read Antigravity's conversation_summaries.db (read-only) to retrieve:
    - conversations: top-level conversations matching the exact left sidebar order & titles
    - realProjects: genuine Antigravity Projects / open workspace folders (empty when user created none)
    - conv_meta_map: dict[conv_id] -> { title, agProjectId, agProjectName, wsPaths, isCurrent }
    """
    real_projects = []
    proj_by_id = {}

    def ensure_real_project(pid, name, path_str="", is_ws=False):
        if not pid:
            return None
        existing = proj_by_id.get(pid)
        if existing:
            if is_ws:
                existing["isWorkspace"] = True
            return existing
        entry = {
            "id": pid,
            "name": name,
            "path": path_str,
            "kind": "project",
            "isWorkspace": bool(is_ws),
        }
        proj_by_id[pid] = entry
        real_projects.append(entry)
        return entry

    # Any currently open Antigravity workspace folder counts as an active project
    for wp in (active_workspace_paths or []):
        try:
            real = str(Path(wp).resolve())
        except Exception:
            real = os.path.normpath(wp)
        if os.path.isdir(real):
            ensure_real_project(f"agproj:{real.lower()}", os.path.basename(real) or real, real, is_ws=True)

    conversations = []
    conv_meta_map = {}

    db_path = Path(app_data) / "conversation_summaries.db" if app_data else None
    rows = []
    if db_path and db_path.exists():
        conn = None
        try:
            db_uri = db_path.resolve().as_uri() + "?mode=ro"
            conn = sqlite3.connect(db_uri, uri=True, timeout=1.5)
            conn.row_factory = sqlite3.Row
            rows = [
                dict(r)
                for r in conn.execute(
                    "SELECT conversation_id, title, project_id, workspace_uris, parent_conversation_id, last_modified_time "
                    "FROM conversation_summaries "
                    "WHERE COALESCE(parent_conversation_id, '') = '' "
                    "ORDER BY last_modified_time DESC"
                ).fetchall()
            ]
        except Exception:
            rows = []
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

    seen_convs = set()
    for r in rows:
        cid = (r.get("conversation_id") or "").strip()
        if not cid or not ID_RE.match(cid) or cid in seen_convs:
            continue
        seen_convs.add(cid)
        raw_title = (r.get("title") or "").strip()
        title = raw_title or (f"对话 {cid[:8]}")
        raw_pid = (r.get("project_id") or "").strip()
        ws_paths = parse_workspace_paths(r.get("workspace_uris") or "")

        ag_proj_id = ""
        ag_proj_name = ""
        if ws_paths:
            wp0 = ws_paths[0]
            try:
                wp0_real = str(Path(wp0).resolve())
            except Exception:
                wp0_real = os.path.normpath(wp0)
            p_entry = ensure_real_project(
                f"agproj:{wp0_real.lower()}",
                os.path.basename(wp0_real) or wp0_real,
                wp0_real,
                is_ws=(cid == active_conv_id and bool(active_workspace_paths)),
            )
            if p_entry:
                ag_proj_id = p_entry["id"]
                ag_proj_name = p_entry["name"]
        elif raw_pid and raw_pid.lower() != "outside-of-project":
            pname = os.path.basename(raw_pid) if os.path.isdir(raw_pid) else raw_pid
            p_entry = ensure_real_project(
                f"agproj:{raw_pid}",
                pname,
                raw_pid if os.path.isdir(raw_pid) else "",
                is_ws=False,
            )
            if p_entry:
                ag_proj_id = p_entry["id"]
                ag_proj_name = p_entry["name"]

        is_cur = (cid == active_conv_id)
        if is_cur and not ag_proj_id and real_projects:
            ws_actives = [p for p in real_projects if p.get("isWorkspace")]
            if ws_actives:
                ag_proj_id = ws_actives[0]["id"]
                ag_proj_name = ws_actives[0]["name"]

        meta = {
            "id": f"conv:{cid}",
            "convId": cid,
            "name": title,
            "kind": "conversation",
            "isCurrent": is_cur,
            "agProjectId": ag_proj_id,
            "agProjectName": ag_proj_name,
            "lastModifiedTime": str(r.get("last_modified_time") or ""),
        }
        conversations.append(meta)
        conv_meta_map[cid] = meta

    # Ensure active conversation always exists even if DB hasn't indexed it yet
    if active_conv_id and ID_RE.match(active_conv_id) and active_conv_id not in seen_convs:
        ws_actives = [p for p in real_projects if p.get("isWorkspace")]
        meta = {
            "id": f"conv:{active_conv_id}",
            "convId": active_conv_id,
            "name": f"当前对话 {active_conv_id[:8]}",
            "kind": "conversation",
            "isCurrent": True,
            "agProjectId": ws_actives[0]["id"] if ws_actives else "",
            "agProjectName": ws_actives[0]["name"] if ws_actives else "",
            "lastModifiedTime": "",
        }
        conversations.insert(0, meta)
        conv_meta_map[active_conv_id] = meta

    # Fallback if DB was completely unavailable: list recent brain folders
    if not rows and app_data:
        brain_dir = Path(app_data) / "brain"
        if brain_dir.exists():
            extra = []
            try:
                for entry in os.scandir(brain_dir):
                    if entry.is_dir() and ID_RE.match(entry.name) and entry.name not in seen_convs:
                        t_path = Path(entry.path) / ".system_generated" / "logs" / "transcript.jsonl"
                        mt = t_path.stat().st_mtime if t_path.exists() else entry.stat().st_mtime
                        extra.append((mt, entry.name))
            except Exception:
                pass
            extra.sort(key=lambda x: x[0], reverse=True)
            for _, cid in extra[:20]:
                seen_convs.add(cid)
                meta = {
                    "id": f"conv:{cid}",
                    "convId": cid,
                    "name": f"历史对话 {cid[:8]}",
                    "kind": "conversation",
                    "isCurrent": (cid == active_conv_id),
                    "agProjectId": "",
                    "agProjectName": "",
                    "lastModifiedTime": "",
                }
                conversations.append(meta)
                conv_meta_map[cid] = meta

    return real_projects, conversations, conv_meta_map


def match_path_to_project(file_path, roots):
    """Longest-prefix match from a filesystem path to known project or local folder roots."""
    if not file_path:
        return None
    low = os.path.normpath(file_path).lower()
    best = None
    best_len = -1
    for root in (roots or []):
        rp = (root.get("path") or "").lower().rstrip("\\/")
        if not rp:
            continue
        if low == rp or low.startswith(rp + os.sep) or low.startswith(rp + "/"):
            if len(rp) > best_len:
                best = root
                best_len = len(rp)
    return best


def infer_conv_project_map(app_data, project_roots, max_convs=24):
    """Map conversation IDs to a real Antigravity workspace/project ONLY when present."""
    res = {}
    if not app_data or not project_roots:
        return res
    brain_dir = Path(app_data) / "brain"
    if not brain_dir.exists():
        return res
    convs = []
    try:
        for entry in os.scandir(brain_dir):
            if entry.is_dir() and ID_RE.match(entry.name):
                t_path = Path(entry.path) / ".system_generated" / "logs" / "transcript.jsonl"
                try:
                    mt = t_path.stat().st_mtime if t_path.exists() else entry.stat().st_mtime
                    convs.append((mt, entry.name, t_path))
                except Exception:
                    pass
    except Exception:
        pass
    convs.sort(key=lambda x: x[0], reverse=True)
    roots_sig = tuple(r["id"] for r in project_roots)

    for mt, cid, t_path in convs[:max_convs]:
        cached = _CONV_PROJECT_CACHE.get(cid)
        if cached and cached[0] == mt and cached[1] == roots_sig:
            if cached[2]:
                res[cid] = cached[2]
            continue
        counts = {}
        if t_path.exists():
            try:
                raw = t_path.read_text(encoding="utf-8", errors="ignore")
                raw_low = raw.lower()
                for root in project_roots:
                    rp_low = (root.get("path") or "").lower()
                    if not rp_low:
                        continue
                    rp_slash = rp_low.replace("\\", "/")
                    c = raw_low.count(rp_low) + (raw_low.count(rp_slash) if rp_slash != rp_low else 0)
                    if c > 0:
                        counts[root["id"]] = (c, root)
            except Exception:
                pass
        best_root = max(counts.values(), key=lambda x: x[0])[1] if counts else None
        _CONV_PROJECT_CACHE[cid] = (mt, roots_sig, best_root)
        if best_root:
            res[cid] = best_root
    return res


def tag_file_project(
    item,
    project_roots=None,
    conv_project_map=None,
    fallback_conv_id="",
    active_conv_id="",
    workspace_projects=None,
    local_dir_roots=None,
    conv_meta_map=None,
):
    """Attach strictly-separated convId/convTitle, agProjectId/agProjectName, and localDirId/localDirName metadata."""
    if not isinstance(item, dict):
        return item

    cid = item.get("convId") or fallback_conv_id or ""
    if not cid and item.get("path"):
        m_brain = re.search(r"[\\/]brain[\\/]([0-9a-f-]{8,})[\\/]", item["path"], flags=re.IGNORECASE)
        if m_brain:
            cid = m_brain.group(1)

    if cid:
        item["convId"] = cid
    cmeta = (conv_meta_map or {}).get(cid) if cid else None
    if cmeta:
        item["convTitle"] = cmeta.get("name") or item.get("convTitle") or ""

    if active_conv_id:
        item["isCurrentConv"] = (cid == active_conv_id) if cid else bool(item.get("isCurrentConv", False))

    matched_ag = match_path_to_project(item.get("path"), project_roots)
    matched_local = match_path_to_project(item.get("path"), local_dir_roots)

    ag_id = ""
    ag_name = ""
    if matched_ag:
        ag_id = matched_ag["id"]
        ag_name = matched_ag["name"]
    elif cmeta and cmeta.get("agProjectId"):
        ag_id = cmeta["agProjectId"]
        ag_name = cmeta.get("agProjectName") or ""
    elif cid and cid == active_conv_id and workspace_projects:
        ws0 = workspace_projects[0]
        ag_id = ws0["id"]
        ag_name = ws0["name"]
    elif cid and conv_project_map and cid in conv_project_map:
        inferred = conv_project_map[cid]
        ag_id = inferred["id"]
        ag_name = inferred["name"]

    item["agProjectId"] = ag_id
    item["agProjectName"] = ag_name
    item["localDirId"] = matched_local["id"] if matched_local else ""
    item["localDirName"] = matched_local["name"] if matched_local else ""

    if ag_id:
        item["projectId"] = ag_id
        item["projectName"] = ag_name
    elif cid:
        item["projectId"] = f"conv:{cid}"
        item["projectName"] = item.get("convTitle") or ("当前对话" if cid == active_conv_id else f"历史对话 {cid[:8]}")
    elif matched_local:
        item["projectId"] = matched_local["id"]
        item["projectName"] = matched_local["name"]
    else:
        item["projectId"] = "scope:__standalone__"
        item["projectName"] = "独立文档"

    return item


def extract_paths_from_user_step(step, ai_created_lower_set, workspace_roots=None):
    """Extract files/folders explicitly sent, uploaded, or @-mentioned by the human user in a USER_INPUT step."""
    found = {}
    if not isinstance(step, dict):
        return []

    def add_cand(raw_p, is_dir=False, allow_missing=False):
        np = dsh_sync.norm_path_str(str(raw_p or ""))
        if not np:
            return
        k = dsh_sync.path_key(np)
        if not k or k in ai_created_lower_set:
            return
        exists = os.path.exists(np)
        if not exists and not allow_missing:
            return
        real_dir = os.path.isdir(np) if exists else bool(is_dir)
        prev = found.get(k)
        if not prev or (exists and not prev.get("exists")):
            found[k] = {"path": np, "isDir": real_dir, "exists": exists}

    # 1. Media attachments explicitly uploaded by the user in this message
    for m in step.get("media") or []:
        if not isinstance(m, dict):
            continue
        uri = m.get("uri") or m.get("path") or ""
        if uri:
            lp = file_uri_to_local_path(uri) if uri.lower().startswith("file://") else os.path.normpath(uri)
            if lp:
                add_cand(lp, allow_missing=True)

    # 2. Extract only from <USER_REQUEST>...</USER_REQUEST> (strip <CONTEXT_SUMMARY> & <SYSTEM_MESSAGE>)
    content = step.get("content")
    if isinstance(content, str) and content:
        for m in re.finditer(r"\[Attachment:[^\]]*\(([A-Za-z]:[\\/][^\r\n()\"'<>]+)\)\]", content):
            add_cand(m.group(1).strip(), allow_missing=True)

        cleaned = re.sub(r"<CONTEXT_SUMMARY>[\s\S]*?</CONTEXT_SUMMARY>", "", content, flags=re.IGNORECASE)
        cleaned = re.sub(r"<SYSTEM_MESSAGE>[\s\S]*?</SYSTEM_MESSAGE>", "", cleaned, flags=re.IGNORECASE)
        user_reqs = re.findall(r"<USER_REQUEST>([\s\S]*?)</USER_REQUEST>", cleaned, flags=re.IGNORECASE)
        user_text = "\n".join(user_reqs) if user_reqs else cleaned

        for m in re.finditer(r"file:///[^\s)\"'\]>`]+", user_text, flags=re.IGNORECASE):
            lp = file_uri_to_local_path(m.group(0))
            if lp:
                add_cand(lp, allow_missing=True)

        # DSH 对齐：解析 @"含空格路径" / @绝对路径 / @相对工作区路径 / @文件夹
        for men in dsh_sync.extract_mentions_from_text(user_text, workspace_roots=workspace_roots, allow_dirs=True):
            add_cand(men["path"], is_dir=bool(men.get("isDir")), allow_missing=True)

        # 兼容直接粘贴未加 @ 的 Windows 绝对文件路径
        for m in re.finditer(r"(?:^|[\s\"'])([A-Za-z]:[\\/][^\s\"'<>|?*]+\.[A-Za-z0-9]{1,8})", user_text):
            add_cand(m.group(1).strip(), allow_missing=False)

    return list(found.values())


def collect_ai_created_paths(conv_folder, workspace_roots=None):
    """Return lowercase path set of files created/written by AI in this conversation."""
    ai_set = set()
    t_path = conv_folder / ".system_generated" / "logs" / "transcript.jsonl"
    if not t_path.exists():
        return ai_set
    try:
        for line in t_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if not line.strip():
                continue
            try:
                step = json.loads(line)
            except Exception:
                continue
            for tc in step.get("tool_calls") or []:
                if not isinstance(tc, dict):
                    continue
                tname = tc.get("name") or ""
                args = tc.get("args") or {}
                for extracted_p, src_kind in dsh_sync.extract_paths_from_tool_call(tname, args, workspace_roots=workspace_roots):
                    if src_kind in ("created", "edited"):
                        ai_set.add(dsh_sync.path_key(extracted_p))
    except Exception:
        pass
    return ai_set


def _is_internal_ignored_path(norm_path: str) -> bool:
    lower = norm_path.lower().replace("/", "\\")
    return (
        ".system_generated" in lower
        or "\\builtin\\skills\\" in lower
        or "\\builtin\\plugins\\" in lower
        or ("\\brain\\" in lower and "\\scratch\\" in lower)
        or "\\browser_evidence\\" in lower
        or "\\browser_sandbox\\" in lower
        or "\\.fl_preview\\" in lower
        or "\\fl_preview\\" in lower
        or "\\file_launcher_preview\\" in lower
        or "\\.file_launcher_preview\\" in lower
    )


def collect_user_sent_files(
    app_data,
    active_conv_id,
    max_items=60,
    conv_roots_map=None,
    workspace_roots=None,
    force_rescan=False,
):
    """
    Collect files & @folders sent/uploaded by the user, backed by persistent incremental sent-index.json
    and preserving missing shells so moved/deleted detection can work cleanly.
    """
    if not app_data:
        return []
    brain_dir = Path(app_data) / "brain"
    if not brain_dir.exists():
        return []

    conv_tasks = []
    if active_conv_id and ID_RE.match(active_conv_id):
        active_folder = brain_dir / active_conv_id
        if active_folder.exists():
            t_path = active_folder / ".system_generated" / "logs" / "transcript.jsonl"
            up_dir = active_folder / ".user_uploaded"
            sig = f"{t_path.stat().st_mtime_ns if t_path.exists() else 0}:{t_path.stat().st_size if t_path.exists() else 0}:{up_dir.stat().st_mtime_ns if up_dir.exists() else 0}"
            conv_tasks.append({
                "convId": active_conv_id,
                "folder": active_folder,
                "isCurrent": True,
                "sig": sig,
            })

    try:
        conv_entries = []
        for entry in os.scandir(brain_dir):
            if entry.is_dir() and ID_RE.match(entry.name) and entry.name != active_conv_id:
                try:
                    conv_entries.append((entry.stat().st_mtime, Path(entry.path), entry.name))
                except Exception:
                    pass
        conv_entries.sort(key=lambda x: x[0], reverse=True)
        for _, cpath, cname in conv_entries[:25]:
            t_path = cpath / ".system_generated" / "logs" / "transcript.jsonl"
            up_dir = cpath / ".user_uploaded"
            try:
                sig = f"{t_path.stat().st_mtime_ns if t_path.exists() else 0}:{t_path.stat().st_size if t_path.exists() else 0}:{up_dir.stat().st_mtime_ns if up_dir.exists() else 0}"
            except Exception:
                sig = "0:0:0"
            conv_tasks.append({
                "convId": cname,
                "folder": cpath,
                "isCurrent": False,
                "sig": sig,
            })
    except Exception:
        pass

    def scan_conv_records(task):
        conv_folder = task["folder"]
        cid_name = task["convId"]
        is_current = bool(task["isCurrent"])
        ws_roots = list((conv_roots_map or {}).get(cid_name) or workspace_roots or [])
        ai_created = collect_ai_created_paths(conv_folder, workspace_roots=ws_roots)
        rec_map = {}

        def record_raw(raw_p, step_idx=0, known_is_dir=False):
            np = dsh_sync.norm_path_str(str(raw_p or ""))
            if not np or _is_internal_ignored_path(np):
                return
            k = dsh_sync.path_key(np)
            if not k:
                return
            exists = os.path.exists(np)
            is_dir = os.path.isdir(np) if exists else bool(known_is_dir)
            size = 0
            mtime_ms = 0
            if exists and not is_dir:
                try:
                    st = os.stat(np)
                    size = int(st.st_size)
                    mtime_ms = int(st.st_mtime * 1000)
                except OSError:
                    pass
            elif exists and is_dir:
                try:
                    mtime_ms = int(os.stat(np).st_mtime * 1000)
                except OSError:
                    pass
            prev = rec_map.get(k)
            if not prev:
                rec_map[k] = {
                    "path": np,
                    "isDir": is_dir,
                    "size": size,
                    "mtimeMs": mtime_ms,
                    "stepIndex": int(step_idx),
                }
            else:
                if step_idx > prev.get("stepIndex", -1):
                    prev["stepIndex"] = int(step_idx)
                if size > 0:
                    prev["size"] = size
                if mtime_ms > 0:
                    prev["mtimeMs"] = mtime_ms

        up_dir = conv_folder / ".user_uploaded"
        if up_dir.exists() and up_dir.is_dir():
            try:
                for entry in os.scandir(up_dir):
                    if entry.is_file():
                        record_raw(entry.path, 10000 if is_current else 5000, known_is_dir=False)
            except Exception:
                pass

        t_path = conv_folder / ".system_generated" / "logs" / "transcript.jsonl"
        if t_path.exists():
            try:
                for line in t_path.read_text(encoding="utf-8", errors="ignore").splitlines():
                    if not line.strip():
                        continue
                    try:
                        step = json.loads(line)
                    except Exception:
                        continue
                    stype = step.get("type") or ""
                    ssource = step.get("source") or ""
                    if stype == "USER_INPUT" or ssource == "USER_EXPLICIT":
                        idx = int(step.get("step_index") or 0)
                        for cand in extract_paths_from_user_step(step, ai_created, workspace_roots=ws_roots):
                            record_raw(cand["path"], idx, known_is_dir=bool(cand.get("isDir")))
            except Exception:
                pass

        return list(rec_map.values())

    sp = get_store_paths()
    raw_items = dsh_sync.sync_sent_index_incremental(
        sp["sentIndex"],
        conv_tasks,
        scan_conv_records,
        force_rescan=force_rescan,
        max_convs=20,
    )

    out = []
    for raw_rec in raw_items:
        info = describe_file(
            raw_rec["path"],
            action_kind="user_sent",
            step_index=int(raw_rec.get("stepIndex") or 0),
            is_user_sent=True,
            allow_missing=True,
            last_known_size=int(raw_rec.get("size") or 0),
            last_known_mtime_ms=int(raw_rec.get("mtimeMs") or 0),
            last_known_is_dir=bool(raw_rec.get("isDir")),
        )
        if not info:
            continue
        info["isUserSent"] = True
        info["isReadable"] = True
        info["convId"] = raw_rec.get("convId") or ""
        info["isCurrentConv"] = bool(raw_rec.get("isCurrentConv"))
        info["sentScope"] = raw_rec.get("sentScope") or "history"
        info["sentScopeLabel"] = raw_rec.get("sentScopeLabel") or "历史会话发送"
        out.append(info)

    out.sort(
        key=lambda x: (
            1 if x.get("sentScope") == "current" else 0,
            0 if x.get("missing") else 1,
            x.get("mtimeMs", 0),
            x.get("stepIndex", 0),
        ),
        reverse=True,
    )
    return out[:max_items]


_CONV_SESSION_CACHE = {}


def collect_session_files(app_data, conv_id, is_current=True, workspace_roots=None):
    if not app_data or not conv_id or not ID_RE.match(conv_id):
        return []
    items = {}

    def upsert(raw_p, action_kind, step_idx=0, allow_missing=False):
        info = describe_file(
            raw_p,
            action_kind=action_kind,
            step_index=step_idx,
            allow_missing=allow_missing,
        )
        if not info:
            return
        if _is_internal_ignored_path(info["path"]):
            return
        lower = dsh_sync.path_key(info["path"])
        prev = items.get(lower)
        if not prev:
            info["convId"] = conv_id
            info["isCurrentConv"] = bool(is_current)
            items[lower] = info
            return
        if ACTION_WEIGHT.get(action_kind, 0) >= ACTION_WEIGHT.get(prev["actionKind"], 0):
            prev["actionKind"] = action_kind
            new_src = dsh_sync.map_action_to_source(action_kind, ext=prev.get("ext", ""), is_user_sent=False)
            prev["source"] = new_src
            prev["sourceLabel"] = dsh_sync.SOURCE_LABELS.get(new_src, prev.get("sourceLabel") or "文件")
        if step_idx > prev["stepIndex"]:
            prev["stepIndex"] = step_idx
        if prev.get("missing") and not info.get("missing"):
            items[lower] = info
            items[lower]["convId"] = conv_id
            items[lower]["isCurrentConv"] = bool(is_current)

    conv_dir = Path(app_data) / "brain" / conv_id

    def scan_artifact_dir(d, depth=0):
        if depth > 2 or not d.exists():
            return
        try:
            for entry in os.scandir(d):
                if entry.name.startswith(".") or entry.name in ("browser_sandbox", "fl_preview"):
                    continue
                if entry.is_dir():
                    scan_artifact_dir(Path(entry.path), depth + 1)
                else:
                    upsert(entry.path, "artifact", 9999)
        except Exception:
            pass

    scan_artifact_dir(conv_dir)

    t_path = conv_dir / ".system_generated" / "logs" / "transcript.jsonl"
    if t_path.exists():
        try:
            for line in t_path.read_text(encoding="utf-8", errors="ignore").splitlines():
                if not line.strip():
                    continue
                try:
                    step = json.loads(line)
                except Exception:
                    continue
                idx = int(step.get("step_index") or 0)
                for tc in step.get("tool_calls") or []:
                    if not isinstance(tc, dict):
                        continue
                    tname = tc.get("name") or ""
                    args = tc.get("args") or {}
                    for p, src_kind in dsh_sync.extract_paths_from_tool_call(tname, args, workspace_roots=workspace_roots):
                        # 仅对 AI 明确创建或编辑的文件保留 missing 空壳，read 不主动生成 missing 避免噪音
                        upsert(p, src_kind, idx, allow_missing=(src_kind in ("created", "edited")))

                if step.get("type") == "PLANNER_RESPONSE" and isinstance(step.get("content"), str):
                    for m in re.finditer(r"file:///[^\s)\"'\]>`]+", step["content"], flags=re.IGNORECASE):
                        lp = file_uri_to_local_path(m.group(0))
                        if lp:
                            upsert(lp, "linked", idx)
        except Exception:
            pass

    result = list(items.values())
    result.sort(
        key=lambda x: (
            0 if x.get("missing") else 1,
            1 if x["ext"] in (".docx", ".doc", ".pptx", ".ppt", ".xlsx", ".pdf", ".md") else 0,
            ACTION_WEIGHT.get(x["actionKind"], 0),
            x["stepIndex"],
            x["mtimeMs"],
        ),
        reverse=True,
    )
    return result


def collect_all_session_files(
    app_data,
    conversations,
    active_conv_id,
    max_convs=20,
    conv_roots_map=None,
    workspace_roots=None,
    force_rescan=False,
):
    """Collect session deliverables per top-level conversation (with transcript mtime cache)."""
    if not app_data:
        return []
    cids = []
    seen_cid = set()
    if active_conv_id and ID_RE.match(active_conv_id):
        cids.append(active_conv_id)
        seen_cid.add(active_conv_id)
    for c in (conversations or []):
        cid = c.get("convId") or ""
        if cid and cid not in seen_cid:
            cids.append(cid)
            seen_cid.add(cid)

    combined = []
    for cid in cids[:max_convs]:
        is_cur = (cid == active_conv_id)
        conv_dir = Path(app_data) / "brain" / cid
        if not conv_dir.exists():
            continue
        t_path = conv_dir / ".system_generated" / "logs" / "transcript.jsonl"
        try:
            sig = (conv_dir.stat().st_mtime, t_path.stat().st_mtime if t_path.exists() else 0.0)
        except Exception:
            sig = None
        ws_roots = list((conv_roots_map or {}).get(cid) or workspace_roots or [])
        cached = _CONV_SESSION_CACHE.get(cid)
        if not force_rescan and not is_cur and cached and sig and cached[0] == sig:
            rows = [dict(x) for x in cached[1]]
        else:
            rows = collect_session_files(app_data, cid, is_current=is_cur, workspace_roots=ws_roots)
            if sig:
                _CONV_SESSION_CACHE[cid] = (sig, [dict(x) for x in rows])
        for row in rows:
            row["convId"] = cid
            row["isCurrentConv"] = is_cur
            combined.append(row)
    return combined


def collect_recent_project_files(watched_dirs, max_items=180, project_roots=None, per_project=30):
    found = []
    seen = set()

    def scan_subtree(base_dir, max_count, max_depth=3):
        bucket = []

        def walk(d, depth=0):
            if depth > max_depth or not os.path.exists(d):
                return
            try:
                for entry in os.scandir(d):
                    if entry.name.startswith("."):
                        continue
                    if entry.is_dir():
                        if entry.name.lower() in NON_PROJECT_SUBDIRS:
                            continue
                        walk(entry.path, depth + 1)
                    else:
                        ext = os.path.splitext(entry.name)[1].lower()
                        if ext not in DELIVERABLE_EXTS:
                            continue
                        lower = entry.path.lower()
                        if lower in seen:
                            continue
                        seen.add(lower)
                        info = describe_file(entry.path, action_kind="recent")
                        if info:
                            bucket.append(info)
            except Exception:
                pass

        walk(base_dir, 0)
        bucket.sort(key=lambda x: x["mtimeMs"], reverse=True)
        return bucket[:max_count]

    # Collect per-project first so large projects cannot crowd out other projects
    if project_roots:
        for pr in project_roots:
            rp = pr.get("path")
            if rp and os.path.exists(rp):
                found.extend(scan_subtree(rp, per_project, max_depth=3))

    # Also collect loose files sitting directly inside watched_dirs roots (depth 0)
    for root in watched_dirs or []:
        if root and os.path.exists(root):
            try:
                loose = []
                for entry in os.scandir(root):
                    if entry.is_file() and not entry.name.startswith("."):
                        ext = os.path.splitext(entry.name)[1].lower()
                        if ext in DELIVERABLE_EXTS:
                            lower = entry.path.lower()
                            if lower not in seen:
                                seen.add(lower)
                                info = describe_file(entry.path, action_kind="recent")
                                if info:
                                    loose.append(info)
                loose.sort(key=lambda x: x["mtimeMs"], reverse=True)
                found.extend(loose[:per_project])
            except Exception:
                pass
            if not project_roots:
                found.extend(scan_subtree(root, max_items, max_depth=3))

    found.sort(key=lambda x: x["mtimeMs"], reverse=True)
    return found[:max_items]


def spawn_detached(args, cwd=None):
    try:
        kwargs = {
            "cwd": cwd or None,
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
        }
        if IS_WIN:
            kwargs["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True
        subprocess.Popen(args, **kwargs)
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def perform_file_action(target_path, mode="default", app_id="", custom_exe=""):
    if not target_path or not isinstance(target_path, str):
        return {"ok": False, "error": "Missing file path"}
    norm = os.path.normpath(target_path.strip())
    if not os.path.exists(norm):
        return {"ok": False, "error": f"File does not exist: {norm}"}
    real = os.path.realpath(norm)
    is_dir = os.path.isdir(real)
    work_dir = real if is_dir else os.path.dirname(real)

    # 1. Reveal in Explorer
    if mode == "reveal" or app_id == "reveal":
        if IS_WIN:
            return spawn_detached(["explorer.exe", real if is_dir else f"/select,{real}"], work_dir)
        if sys.platform == "darwin":
            return spawn_detached(["open", "-R", real], work_dir)
        return spawn_detached(["xdg-open", work_dir], work_dir)

    # 2. Native Windows "Open With..." system dialog
    if mode == "open_with_dialog" or app_id == "open_with_dialog":
        if IS_WIN:
            return spawn_detached(["rundll32.exe", "shell32.dll,OpenAs_RunDLL", real], work_dir)
        if sys.platform == "darwin":
            return spawn_detached(["open", "-a", "Finder", real], work_dir)
        return spawn_detached(["xdg-open", real], work_dir)

    # 3. Specific application
    if mode == "app" or (app_id and app_id != "default"):
        cfg = load_user_config()
        apps = detect_installed_apps(cfg.get("customApps"))
        chosen = next((a for a in apps if a.get("id") == app_id), None)
        exe = custom_exe or (chosen.get("exe") if chosen else "")

        if app_id == "powershell" and IS_WIN:
            safe_dir = work_dir.replace("'", "''")
            return spawn_detached(
                ["cmd.exe", "/c", "start", "powershell.exe", "-NoExit", "-Command", f"Set-Location -LiteralPath '{safe_dir}'"],
                work_dir,
            )
        if not exe or not os.path.exists(exe):
            return {"ok": False, "error": f"Application executable not found: {exe or app_id}"}
        return spawn_detached([exe, real], work_dir)

    # 4. Default open (check per-extension preferred app first)
    cfg = load_user_config()
    ext = "" if is_dir else os.path.splitext(real)[1].lower()
    pref_app = cfg.get("extDefaults", {}).get(ext) if ext else None
    if pref_app and pref_app != "default":
        return perform_file_action(real, mode="app", app_id=pref_app)

    if IS_WIN:
        try:
            os.startfile(real)
            return {"ok": True}
        except Exception:
            if is_dir:
                return spawn_detached(["explorer.exe", real], work_dir)
            return spawn_detached(["rundll32.exe", "url.dll,FileProtocolHandler", real], work_dir)
    if sys.platform == "darwin":
        return spawn_detached(["open", real], work_dir)
    return spawn_detached(["xdg-open", real], work_dir)



import csv
import html as html_mod
import mimetypes
import xml.etree.ElementTree as ET
import zipfile


def preview_docx_to_html(real_path):
    """Extract paragraphs and tables from a .docx file into clean high-contrast HTML."""
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    parts = []
    with zipfile.ZipFile(real_path, "r") as zf:
        if "word/document.xml" not in zf.namelist():
            return "<p>无法在压缩包中找到 word/document.xml</p>"
        xml_bytes = zf.read("word/document.xml")
    root = ET.fromstring(xml_bytes)
    body = root.find("w:body", ns)
    if body is None:
        return "<p>文档内容为空</p>"

    for child in body:
        tag = child.tag.split("}")[-1]
        if tag == "p":
            texts = []
            is_bold = False
            max_sz = 0
            pPr = child.find("w:pPr", ns)
            style_val = ""
            if pPr is not None:
                pStyle = pPr.find("w:pStyle", ns)
                if pStyle is not None:
                    style_val = pStyle.attrib.get(f"{{{ns['w']}}}val", "")
            for r in child.findall(".//w:r", ns):
                rPr = r.find("w:rPr", ns)
                if rPr is not None:
                    if rPr.find("w:b", ns) is not None:
                        is_bold = True
                    sz_el = rPr.find("w:sz", ns)
                    if sz_el is not None:
                        try:
                            sz_v = int(sz_el.attrib.get(f"{{{ns['w']}}}val", "0"))
                            if sz_v > max_sz:
                                max_sz = sz_v
                        except Exception:
                            pass
                for t in r.findall(".//w:t", ns):
                    if t.text:
                        texts.append(t.text)
            line = "".join(texts).strip()
            if not line:
                continue
            esc = html_mod.escape(line)
            if "Heading1" in style_val or "Title" in style_val or max_sz >= 32:
                parts.append(f'<h2 class="doc-h1">{esc}</h2>')
            elif "Heading2" in style_val or max_sz >= 26:
                parts.append(f'<h3 class="doc-h2">{esc}</h3>')
            elif is_bold:
                parts.append(f'<p class="doc-p"><strong>{esc}</strong></p>')
            else:
                parts.append(f'<p class="doc-p">{esc}</p>')
        elif tag == "tbl":
            rows_html = []
            for idx, tr in enumerate(child.findall(".//w:tr", ns)):
                cells_html = []
                for tc in tr.findall("./w:tc", ns):
                    cell_texts = [t.text for t in tc.findall(".//w:t", ns) if t.text]
                    cell_str = html_mod.escape("".join(cell_texts).strip())
                    cell_tag = "th" if idx == 0 else "td"
                    cells_html.append(f"<{cell_tag}>{cell_str}</{cell_tag}>")
                if cells_html:
                    rows_html.append("<tr>" + "".join(cells_html) + "</tr>")
            if rows_html:
                parts.append('<table class="doc-table">' + "".join(rows_html) + "</table>")

    if not parts:
        return "<p>该 Word 文档暂无可提取的文字段落。</p>"
    return "\n".join(parts)


def preview_pptx_to_html(real_path):
    """Extract slide text from .pptx into slide cards."""
    parts = []
    with zipfile.ZipFile(real_path, "r") as zf:
        slide_names = sorted(
            [n for n in zf.namelist() if n.startswith("ppt/slides/slide") and n.endswith(".xml")],
            key=lambda x: int(re.sub(r"\D", "", x) or "0")
        )
        for idx, sname in enumerate(slide_names, 1):
            root = ET.fromstring(zf.read(sname))
            paras = []
            for p in root.iter():
                if p.tag.endswith("}p"):
                    runs = [t.text for t in p.iter() if t.tag.endswith("}t") and t.text]
                    line = "".join(runs).strip()
                    if line:
                        paras.append(html_mod.escape(line))
            body_html = "".join(f'<p class="doc-p">{line}</p>' for line in paras) or '<p class="doc-p">（本页仅包含图片或图形）</p>'
            parts.append(f'<div class="slide-card"><div class="slide-badge">第 {idx} 页幻灯片</div>{body_html}</div>')
    return "\n".join(parts) if parts else "<p>未能从 PPT 中提取到文字内容。</p>"


def preview_xlsx_to_html(real_path):
    """Extract first worksheet cells from .xlsx into an HTML table."""
    with zipfile.ZipFile(real_path, "r") as zf:
        shared = []
        if "xl/sharedStrings.xml" in zf.namelist():
            sroot = ET.fromstring(zf.read("xl/sharedStrings.xml"))
            for si in sroot.iter():
                if si.tag.endswith("}si"):
                    txt = "".join(t.text for t in si.iter() if t.tag.endswith("}t") and t.text)
                    shared.append(txt)
        sheets = sorted([n for n in zf.namelist() if n.startswith("xl/worksheets/sheet") and n.endswith(".xml")])
        if not sheets:
            return "<p>未找到工作表内容。</p>"
        wroot = ET.fromstring(zf.read(sheets[0]))
        rows_html = []
        for r_idx, row in enumerate(wroot.iter()):
            if not row.tag.endswith("}row"):
                continue
            if len(rows_html) >= 60:
                break
            cells = []
            for c in row:
                if not c.tag.endswith("}c"):
                    continue
                ctype = c.attrib.get("t", "")
                val = ""
                for v in c:
                    if v.tag.endswith("}v") and v.text:
                        val = v.text
                    elif v.tag.endswith("}is"):
                        val = "".join(t.text for t in v.iter() if t.tag.endswith("}t") and t.text)
                if ctype == "s":
                    try:
                        val = shared[int(val)]
                    except Exception:
                        pass
                tag = "th" if len(rows_html) == 0 else "td"
                cells.append(f"<{tag}>{html_mod.escape(str(val))}</{tag}>")
            if cells:
                rows_html.append("<tr>" + "".join(cells) + "</tr>")
        return '<table class="doc-table">' + "".join(rows_html) + "</table>" if rows_html else "<p>表格为空。</p>"


def preview_markdown_to_html(text):
    """Simple, clean Markdown-to-HTML renderer for beginners."""
    lines = text.splitlines()
    out = []
    in_code = False
    for raw in lines:
        line = raw.rstrip()
        if line.strip().startswith("```"):
            if not in_code:
                out.append('<pre class="doc-code"><code>')
                in_code = True
            else:
                out.append("</code></pre>")
                in_code = False
            continue
        if in_code:
            out.append(html_mod.escape(line))
            continue
        if not line.strip():
            continue
        esc = html_mod.escape(line)
        esc = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", esc)
        esc = re.sub(r"`([^`]+)`", r'<code class="inline-code">\1</code>', esc)
        if esc.startswith("# "):
            out.append(f'<h2 class="doc-h1">{esc[2:]}</h2>')
        elif esc.startswith("## "):
            out.append(f'<h3 class="doc-h2">{esc[3:]}</h3>')
        elif esc.startswith("### "):
            out.append(f'<h4 class="doc-h3">{esc[4:]}</h4>')
        elif esc.startswith("- ") or esc.startswith("* "):
            out.append(f'<div class="doc-li">• {esc[2:]}</div>')
        elif esc.startswith("&gt; "):
            out.append(f'<div class="doc-quote">{esc[5:]}</div>')
        else:
            out.append(f'<p class="doc-p">{esc}</p>')
    if in_code:
        out.append("</code></pre>")
    return "\n".join(out) or "<p>文档内容为空。</p>"


def docx_to_markdown(real_path):
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    lines = []
    with zipfile.ZipFile(real_path, "r") as zf:
        if "word/document.xml" not in zf.namelist():
            return "# 无法读取 Word 文档内容"
        xml_bytes = zf.read("word/document.xml")
    root = ET.fromstring(xml_bytes)
    body = root.find("w:body", ns)
    if body is None:
        return "# 文档内容为空"

    for child in body:
        tag = child.tag.split("}")[-1]
        if tag == "p":
            texts = []
            is_bold = False
            max_sz = 0
            pPr = child.find("w:pPr", ns)
            style_val = ""
            if pPr is not None:
                pStyle = pPr.find("w:pStyle", ns)
                if pStyle is not None:
                    style_val = pStyle.attrib.get(f"{{{ns['w']}}}val", "")
            for r in child.findall(".//w:r", ns):
                rPr = r.find("w:rPr", ns)
                if rPr is not None:
                    if rPr.find("w:b", ns) is not None:
                        is_bold = True
                    sz_el = rPr.find("w:sz", ns)
                    if sz_el is not None:
                        try:
                            sz_v = int(sz_el.attrib.get(f"{{{ns['w']}}}val", "0"))
                            if sz_v > max_sz:
                                max_sz = sz_v
                        except Exception:
                            pass
                for t in r.findall(".//w:t", ns):
                    if t.text:
                        texts.append(t.text)
            line = "".join(texts).strip()
            if not line:
                continue
            if "Heading1" in style_val or "Title" in style_val or max_sz >= 32:
                lines.append(f"# {line}\n")
            elif "Heading2" in style_val or max_sz >= 26:
                lines.append(f"## {line}\n")
            elif is_bold:
                lines.append(f"**{line}**\n")
            else:
                lines.append(f"{line}\n")
        elif tag == "tbl":
            rows = []
            for tr in child.findall(".//w:tr", ns):
                cells = []
                for tc in tr.findall("./w:tc", ns):
                    cell_texts = [t.text for t in tc.findall(".//w:t", ns) if t.text]
                    cells.append(" ".join("".join(cell_texts).split()).replace("|", "\\|"))
                if cells:
                    rows.append(cells)
            if rows:
                col_cnt = max(len(r) for r in rows)
                norm_rows = [r + [""] * (col_cnt - len(r)) for r in rows]
                lines.append("| " + " | ".join(norm_rows[0]) + " |")
                lines.append("| " + " | ".join(["---"] * col_cnt) + " |")
                for r in norm_rows[1:]:
                    lines.append("| " + " | ".join(r) + " |")
                lines.append("")
    return "\n".join(lines).strip() or "# 该 Word 文档暂无文字内容"


def pptx_to_markdown(real_path):
    lines = []
    with zipfile.ZipFile(real_path, "r") as zf:
        slide_names = sorted(
            [n for n in zf.namelist() if n.startswith("ppt/slides/slide") and n.endswith(".xml")],
            key=lambda x: int(re.sub(r"\D", "", x) or "0")
        )
        for idx, sname in enumerate(slide_names, 1):
            root = ET.fromstring(zf.read(sname))
            lines.append(f"## 第 {idx} 页幻灯片\n")
            for p in root.iter():
                if p.tag.endswith("}p"):
                    runs = [t.text for t in p.iter() if t.tag.endswith("}t") and t.text]
                    line = "".join(runs).strip()
                    if line:
                        lines.append(f"- {line}")
            lines.append("")
    return "\n".join(lines).strip() or "# 未能从 PPT 中提取到文字内容"


def xlsx_to_markdown(real_path):
    with zipfile.ZipFile(real_path, "r") as zf:
        shared = []
        if "xl/sharedStrings.xml" in zf.namelist():
            sroot = ET.fromstring(zf.read("xl/sharedStrings.xml"))
            for si in sroot.iter():
                if si.tag.endswith("}si"):
                    txt = "".join(t.text for t in si.iter() if t.tag.endswith("}t") and t.text)
                    shared.append(txt)
        sheets = sorted([n for n in zf.namelist() if n.startswith("xl/worksheets/sheet") and n.endswith(".xml")])
        if not sheets:
            return "# 未找到工作表内容"
        wroot = ET.fromstring(zf.read(sheets[0]))
        rows = []
        for row in wroot.iter():
            if not row.tag.endswith("}row"):
                continue
            if len(rows) >= 80:
                break
            cells = []
            for c in row:
                if not c.tag.endswith("}c"):
                    continue
                ctype = c.attrib.get("t", "")
                val = ""
                for v in c:
                    if v.tag.endswith("}v") and v.text:
                        val = v.text
                    elif v.tag.endswith("}is"):
                        val = "".join(t.text for t in v.iter() if t.tag.endswith("}t") and t.text)
                if ctype == "s":
                    try:
                        val = shared[int(val)]
                    except Exception:
                        pass
                cells.append(str(val).replace("\n", " ").replace("|", "\\|"))
            if cells:
                rows.append(cells)
        if not rows:
            return "# 表格为空"
        col_cnt = max(len(r) for r in rows)
        norm_rows = [r + [""] * (col_cnt - len(r)) for r in rows]
        out = [
            "| " + " | ".join(norm_rows[0]) + " |",
            "| " + " | ".join(["---"] * col_cnt) + " |",
        ]
        for r in norm_rows[1:]:
            out.append("| " + " | ".join(r) + " |")
        return "\n".join(out)


def build_native_open_uri(info):
    if not info or not info.get("path"):
        return ""
    real = info["path"]
    ext = (info.get("ext") or "").lower()
    if ext in (".docx", ".pptx", ".xlsx"):
        try:
            cache_dir = get_data_base_dir() / "Pinned_Protected_Files"
            cache_dir.mkdir(parents=True, exist_ok=True)
            stem = os.path.splitext(os.path.basename(real))[0]
            out_md = cache_dir / f"{stem}.md"
            if ext == ".docx":
                md_text = docx_to_markdown(real)
            elif ext == ".pptx":
                md_text = pptx_to_markdown(real)
            else:
                md_text = xlsx_to_markdown(real)
            out_md.write_text(md_text, encoding="utf-8")
            return out_md.resolve().as_uri()
        except Exception:
            return info.get("fileUri") or ""
    return info.get("fileUri") or ""


# 宿主右侧分栏 fileView 能直接渲染的格式（.pdf 默认交给浏览器/WPS 打开，避免纯文本 fileView 显示不可预览）
SIDE_NATIVE_EXTS = {
    ".md", ".txt", ".log", ".csv", ".json", ".xml", ".yaml", ".yml",
    ".py", ".js", ".mjs", ".ts", ".css", ".ps1", ".html", ".htm",
    ".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg",
}
SIDE_MIRROR_EXTS = {".docx", ".pptx", ".xlsx"}


def _preview_dir_for(conv_id):
    """Office 预览镜像放在当前会话 brain 目录的 fl_preview 子目录（宿主侧边栏一定可读，且不会混进文件列表）。"""
    resolved_conv = conv_id
    if not (resolved_conv and ID_RE.match(resolved_conv)):
        _, resolved_conv = resolve_active_conversation("")
    if resolved_conv and ID_RE.match(resolved_conv):
        for ad in find_app_data_dirs():
            conv_dir = Path(ad) / "brain" / resolved_conv
            if conv_dir.exists():
                d = conv_dir / "fl_preview"
                d.mkdir(parents=True, exist_ok=True)
                return d
    d = get_data_base_dir() / "file_launcher_preview"
    d.mkdir(parents=True, exist_ok=True)
    return d


def build_side_uri(target_path, conv_id=""):
    """返回 {ok, uri, kind}: kind = native(原文件直开) | mirror(Office 转 Markdown 只读镜像) | external(只能用电脑软件打开)"""
    if target_path == "__AUTO_RELOAD_SIDECAR__":
        return {
            "ok": True,
            "uri": "",
            "kind": "reload",
            "file": {"path": "__AUTO_RELOAD_SIDECAR__", "name": "正在更新插件界面...", "ext": ""},
        }
    info = describe_file(target_path, action_kind="linked")
    if not info or info.get("isDir"):
        return {"ok": False, "error": "文件不存在"}
    ext = (info.get("ext") or "").lower()
    if ext in SIDE_NATIVE_EXTS:
        return {"ok": True, "uri": info["fileUri"], "kind": "native", "file": info}
    if ext in SIDE_MIRROR_EXTS:
        try:
            real = info["path"]
            if ext == ".docx":
                body = docx_to_markdown(real)
            elif ext == ".pptx":
                body = pptx_to_markdown(real)
            else:
                body = xlsx_to_markdown(real)
            out = _preview_dir_for(conv_id) / (os.path.splitext(os.path.basename(real))[0] + ".md")
            header = f"> 📄 **{info['name']}** 的只读预览（原文件未改动）　·　原文件：`{real}`\n\n"
            out.write_text(header + body, encoding="utf-8")
            return {"ok": True, "uri": out.resolve().as_uri(), "kind": "mirror", "file": info}
        except Exception as e:
            return {"ok": True, "uri": "", "kind": "external", "file": info, "error": str(e)}
    return {"ok": True, "uri": "", "kind": "external", "file": info}


def push_ipc_action(action):
    """把动作（open / attach）压入磁盘队列，并立即唤醒处于可见状态的长轮询 File Launcher 面板。"""
    global ACTION_SEQ
    with QUEUE_COND:
        ipc = read_ipc_state()
        now = time.time()
        ACTION_SEQ += 1
        aid = f"{int(now * 1000)}_{ACTION_SEQ}"
        action = dict(action)
        action["id"] = aid
        action["ts"] = now
        q = [a for a in (ipc.get("queue") or []) if now - float(a.get("ts") or 0) < 60.0]
        q.append(action)
        ipc["queue"] = q[-30:]
        ipc["pendingInternalOpen"] = None
        write_ipc_state(ipc)
        vis_active = (now - float(ipc.get("lastSidecarVisible") or 0)) < 20.0
        QUEUE_COND.notify_all()
        return vis_active, aid


def ack_ipc_actions(action_ids):
    ids = [x.strip() for x in (action_ids or []) if x and x.strip()]
    if not ids:
        return
    with QUEUE_COND:
        ipc = read_ipc_state()
        now = time.time()
        acked = {k: v for k, v in (ipc.get("ackedIds") or {}).items() if now - float(v or 0) < 180.0}
        for aid in ids:
            acked[aid] = now
        ipc["ackedIds"] = acked
        write_ipc_state(ipc)


def _conv_bucket_key(conv_id):
    return conv_id if (conv_id and ID_RE.match(conv_id)) else "__global__"


def get_chat_attached(conv_id):
    ipc = read_ipc_state()
    by_conv = ipc.get("chatAttachedByConv") or {}
    key = _conv_bucket_key(conv_id)
    items = list(by_conv.get(key) or [])
    if key != "__global__" and by_conv.get("__global__"):
        # Merge any pre-conversation global attaches cleanly if path still exists
        seen = {str(x.get("path") or "").lower() for x in items}
        for gi in by_conv["__global__"]:
            p = str(gi.get("path") or "")
            if p and p.lower() not in seen:
                items.append(gi)
                seen.add(p.lower())
    out = []
    for item in items:
        p = item.get("path")
        if p and os.path.exists(p):
            out.append(item)
    return out


def record_chat_attached(conv_id, files):
    if not files:
        return get_chat_attached(conv_id)
    with QUEUE_COND:
        ipc = read_ipc_state()
        by_conv = dict(ipc.get("chatAttachedByConv") or {})
        key = _conv_bucket_key(conv_id)
        existing = list(by_conv.get(key) or [])
        by_path = {}
        order = []
        for x in existing:
            lp = str(x.get("path") or "").lower()
            if lp:
                by_path[lp] = x
                order.append(lp)
        now_ms = int(time.time() * 1000)
        for f in files:
            lp = str(f.get("path") or "").lower()
            if not lp:
                continue
            entry = {
                "path": f.get("path"),
                "name": f.get("name"),
                "ext": f.get("ext", ""),
                "badge": f.get("badge", "FILE"),
                "icon": f.get("icon", "📄"),
                "size": f.get("size", 0),
                "openUri": f.get("openUri") or f.get("fileUri") or "",
                "sideKind": f.get("sideKind") or "native",
                "fileUri": f.get("fileUri") or "",
                "projectId": f.get("projectId") or "",
                "projectName": f.get("projectName") or "",
                "convId": f.get("convId") or "",
                "attachedAt": now_ms,
            }
            if lp in by_path:
                by_path[lp] = entry
            else:
                order.insert(0, lp)
                by_path[lp] = entry
        # Deduplicate order preserving first-seen order
        dedup = []
        seen = set()
        for lp in order:
            if lp not in seen and lp in by_path and os.path.exists(by_path[lp]["path"]):
                seen.add(lp)
                dedup.append(by_path[lp])
        by_conv[key] = dedup[:80]
        ipc["chatAttachedByConv"] = by_conv
        write_ipc_state(ipc)
        return dedup[:80]


def remove_chat_attached(conv_id, paths=None, clear=False):
    with QUEUE_COND:
        ipc = read_ipc_state()
        by_conv = dict(ipc.get("chatAttachedByConv") or {})
        key = _conv_bucket_key(conv_id)
        if clear:
            by_conv[key] = []
            if key != "__global__":
                by_conv.pop("__global__", None)
            ipc["queue"] = [a for a in (ipc.get("queue") or []) if a.get("type") != "attach"]
        else:
            drop = {os.path.normpath(p).lower() for p in (paths or []) if p}
            def _norm_key(item):
                raw = str(item.get("path") or "") if isinstance(item, dict) else ""
                return os.path.normpath(raw).lower() if raw else ""
            by_conv[key] = [x for x in (by_conv.get(key) or []) if _norm_key(x) not in drop]
            if key != "__global__" and "__global__" in by_conv:
                by_conv["__global__"] = [x for x in by_conv["__global__"] if _norm_key(x) not in drop]
            new_q = []
            for a in (ipc.get("queue") or []):
                if a.get("type") == "attach":
                    rem = [f for f in (a.get("files") or []) if _norm_key(f) not in drop]
                    if rem:
                        a = dict(a)
                        a["files"] = rem
                        new_q.append(a)
                else:
                    new_q.append(a)
            ipc["queue"] = new_q
        ipc["chatAttachedByConv"] = by_conv
        write_ipc_state(ipc)
        return by_conv.get(key) or []


def append_embed_log(line):
    try:
        dirs = find_app_data_dirs()
        base = dirs[0] if dirs else (Path.home() / ".gemini" / "antigravity")
        with open(base / "file_launcher_embed.log", "a", encoding="utf-8") as fh:
            fh.write(time.strftime("%Y-%m-%d %H:%M:%S") + " " + line + "\n")
    except Exception:
        pass


def generate_file_preview(target_path):
    if target_path == "__AUTO_RELOAD_SIDECAR__":
        return {
            "ok": True,
            "kind": "image",
            "title": "正在更新插件界面...",
            "rawUrl": 'invalid_url" onerror="(function(){var u=new URL(location.href);u.searchParams.set(\'v\',\'2.2_\'+Date.now());location.replace(u.toString())})()',
        }
    if not target_path:
        return {"ok": False, "error": "未提供文件路径"}
    real = os.path.normpath(target_path)
    if not os.path.exists(real):
        return {"ok": False, "error": f"找不到文件：{real}"}
    if os.path.isdir(real):
        try:
            items = sorted(os.listdir(real))[:100]
            li = "".join(f'<div class="doc-li">📁 {html_mod.escape(x)}</div>' for x in items)
            return {"ok": True, "kind": "html", "title": os.path.basename(real), "html": f'<h3 class="doc-h2">文件夹内容（共 {len(items)} 项）</h3>{li}'}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    ext = os.path.splitext(real)[1].lower()
    name = os.path.basename(real)
    try:
        if ext == ".docx":
            return {"ok": True, "kind": "html", "title": name, "badge": "Word 文档内置阅读", "html": preview_docx_to_html(real)}
        if ext == ".pptx":
            return {"ok": True, "kind": "html", "title": name, "badge": "PPT 幻灯片内置阅读", "html": preview_pptx_to_html(real)}
        if ext == ".xlsx":
            return {"ok": True, "kind": "html", "title": name, "badge": "Excel 表格内置阅读", "html": preview_xlsx_to_html(real)}
        if ext in (".csv", ".tsv"):
            delim = "\t" if ext == ".tsv" else ","
            raw_text = Path(real).read_text(encoding="utf-8", errors="replace")
            all_lines = raw_text.splitlines()
            reader = list(csv.reader(all_lines[:100], delimiter=delim))
            rows = []
            for idx, r in enumerate(reader):
                tag = "th" if idx == 0 else "td"
                rows.append("<tr>" + "".join(f"<{tag}>{html_mod.escape(c)}</{tag}>" for c in r) + "</tr>")
            return {
                "ok": True,
                "kind": "html",
                "title": name,
                "badge": f"{ext[1:].upper()} 表格内置阅读",
                "truncated": len(all_lines) > 100,
                "totalLines": len(all_lines),
                "html": '<table class="doc-table">' + "".join(rows) + "</table>",
            }
        if ext in dsh_sync.IMAGE_EXTS:
            return {"ok": True, "kind": "image", "title": name, "badge": "图片内置预览", "rawUrl": f"/api/raw?path={quote(real)}"}
        if ext in (".md", ".mdx", ".markdown"):
            raw_text = Path(real).read_text(encoding="utf-8", errors="replace")
            return {
                "ok": True,
                "kind": "html",
                "title": name,
                "badge": "Markdown 内置阅读",
                "rawText": raw_text[:60000],
                "html": preview_markdown_to_html(raw_text),
            }
        if ext == ".pdf":
            return {
                "ok": True,
                "kind": "pdf",
                "title": name,
                "badge": "PDF 逐页渲染",
                "rawUrl": f"/api/raw?path={quote(real)}",
            }
        if ext in dsh_sync.TEXT_PREVIEW_EXTS:
            raw_bytes = Path(real).read_bytes()
            max_bytes = 96 * 1024
            truncated = len(raw_bytes) > max_bytes
            raw_text = raw_bytes[:max_bytes].decode("utf-8", errors="replace")
            lines = raw_text.splitlines()
            if len(lines) > 1000:
                raw_text = "\n".join(lines[:1000])
                truncated = True
            return {
                "ok": True,
                "kind": "html",
                "title": name,
                "badge": "文本/代码内置阅读",
                "truncated": truncated,
                "totalLines": len(lines),
                "rawText": raw_text,
                "html": f'<pre class="doc-code"><code>{html_mod.escape(raw_text)}</code></pre>',
            }
        return {
            "ok": True,
            "kind": "unsupported",
            "title": name,
            "badge": "外部软件打开",
            "html": f'<p class="doc-p">该格式（{html_mod.escape(ext or "未知")}）暂不支持在面板内直接解析文字，请点击「文件资源管理器」或使用匹配应用打开查看！</p>',
        }
    except Exception as e:
        return {"ok": False, "error": f"预览解析失败：{e}"}



# 按文件后缀精准匹配可用的打开方式（绝不把不相关的软件一股脑塞进去）
EXT_APP_MAP = {
    ".docx": ["word", "wps"],
    ".doc":  ["word", "wps"],
    ".odt":  ["word", "wps"],
    ".rtf":  ["word", "wps", "notepad"],
    ".xlsx": ["excel", "wps"],
    ".xls":  ["excel", "wps"],
    ".xlsm": ["excel", "wps"],
    ".ods":  ["excel", "wps"],
    ".csv":  ["excel", "wps", "notepad", "vscode", "cursor"],
    ".tsv":  ["excel", "wps", "notepad", "vscode", "cursor"],
    ".pptx": ["powerpoint", "wps"],
    ".ppt":  ["powerpoint", "wps"],
    ".odp":  ["powerpoint", "wps"],
    ".md":   ["notepad", "vscode", "cursor", "word", "wps"],
    ".mdx":  ["vscode", "cursor", "notepad"],
    ".markdown": ["notepad", "vscode", "cursor", "word", "wps"],
    ".txt":  ["notepad", "vscode", "cursor", "notepadpp"],
    ".log":  ["notepad", "vscode", "cursor", "notepadpp"],
    ".pdf":  ["edge", "chrome", "wps"],
    ".html": ["edge", "chrome", "vscode", "cursor", "notepad"],
    ".htm":  ["edge", "chrome", "vscode", "cursor", "notepad"],
    ".png":  ["edge", "chrome"],
    ".jpg":  ["edge", "chrome"],
    ".jpeg": ["edge", "chrome"],
    ".webp": ["edge", "chrome"],
    ".gif":  ["edge", "chrome"],
    ".bmp":  ["edge", "chrome"],
    ".ico":  ["edge", "chrome"],
    ".avif": ["edge", "chrome"],
    ".svg":  ["edge", "chrome", "vscode", "cursor"],
    ".py":   ["vscode", "cursor", "notepadpp", "notepad"],
    ".js":   ["vscode", "cursor", "notepadpp", "notepad"],
    ".jsx":  ["vscode", "cursor", "notepadpp", "notepad"],
    ".mjs":  ["vscode", "cursor", "notepadpp", "notepad"],
    ".cjs":  ["vscode", "cursor", "notepadpp", "notepad"],
    ".ts":   ["vscode", "cursor", "notepadpp", "notepad"],
    ".tsx":  ["vscode", "cursor", "notepadpp", "notepad"],
    ".css":  ["vscode", "cursor", "notepadpp", "notepad"],
    ".scss": ["vscode", "cursor", "notepadpp", "notepad"],
    ".json": ["vscode", "cursor", "notepadpp", "notepad"],
    ".yaml": ["vscode", "cursor", "notepadpp", "notepad"],
    ".yml":  ["vscode", "cursor", "notepadpp", "notepad"],
    ".toml": ["vscode", "cursor", "notepadpp", "notepad"],
    ".xml":  ["vscode", "cursor", "edge", "notepad"],
    ".sql":  ["vscode", "cursor", "notepadpp", "notepad"],
    ".sh":   ["vscode", "cursor", "notepad"],
    ".ps1":  ["vscode", "cursor", "notepadpp", "notepad"],
}


def get_matched_apps_for_ext(ext, all_apps):
    """Return installed desktop apps matching this extension, plus user customApps."""
    ext = (ext or "").lower()
    allowed_ids = EXT_APP_MAP.get(ext, ["vscode", "cursor", "notepad"])
    by_id = {a["id"]: a for a in (all_apps or [])}
    matched = []
    seen = set()
    for aid in allowed_ids:
        if aid in by_id and aid not in seen:
            matched.append({"id": aid, "name": by_id[aid]["name"]})
            seen.add(aid)
    for app in (all_apps or []):
        if app.get("isCustom") and app.get("id") not in seen:
            matched.append({"id": app["id"], "name": app["name"]})
            seen.add(app["id"])
    return matched


def run_agentapi(args):
    exe = os.environ.get("ANTIGRAVITY_AGENTAPI_EXE") or "agentapi"
    cmd = [exe, "agentapi"] + args if os.environ.get("ANTIGRAVITY_AGENTAPI_EXE") else ["agentapi"] + args
    try:
        out = subprocess.check_output(cmd, encoding="utf-8", timeout=5)
        return json.loads(out) if out.strip() else {}
    except Exception as e:
        return {"error": str(e)}


class SidecarRequestHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Content-Length", "0")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.end_headers()

    def _send_bytes(self, status, content_type, body_bytes):
        try:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body_bytes)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "*")
            self.send_header("Access-Control-Allow-Private-Network", "true")
            self.end_headers()
            self.wfile.write(body_bytes)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass

    def _send_json(self, status, payload):
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send_bytes(status, "application/json; charset=utf-8", raw)

    def do_GET(self):
        parsed = urlparse(self.path)
        route = parsed.path
        query = {k: v[-1] for k, v in parse_qs(parsed.query).items()}

        if route == "/":
            self._send_bytes(200, "text/html; charset=utf-8", (HERE / "index.html").read_bytes())
            return
        if route == "/preload.js":
            self._send_bytes(200, "application/javascript; charset=utf-8", (HERE / "preload.js").read_bytes())
            return
        if route == "/styles.css":
            self._send_bytes(200, "text/css; charset=utf-8", (HERE / "styles.css").read_bytes())
            return
        if route == "/app.js":
            self._send_bytes(200, "application/javascript; charset=utf-8", (HERE / "app.js").read_bytes())
            return

        if route == "/api/state":
            global LAST_SIDECAR_SEEN, PENDING_INTERNAL_OPEN
            if query.get("client") == "sidecar":
                LAST_SIDECAR_SEEN = time.time()
            fresh = query.get("fresh") in ("1", "true")
            req_conv = query.get("conversationId") or os.environ.get("ANTIGRAVITY_CONVERSATION_ID") or ""
            app_data, conv_id = resolve_active_conversation(req_conv)
            cfg = load_user_config()
            sp = get_store_paths()
            tombstones = dsh_sync.load_tombstones(sp["deletedIndex"])
            archive_records = dsh_sync.load_archive_records(sp["archiveIndex"])

            workspace_paths = parse_workspace_paths(query.get("workspaceUris") or "")
            real_projects, conversations, conv_meta_map = load_sidebar_db_data(app_data, conv_id, workspace_paths)
            local_dir_roots = discover_local_dir_roots(cfg)
            workspace_projects = [r for r in real_projects if r.get("isWorkspace")]
            conv_project_map = infer_conv_project_map(app_data, real_projects)
            apps = detect_installed_apps(cfg.get("customApps"))

            # 为每个会话建立工作区根路径映射，以支持 @相对路径 和 移动重连
            proj_path_by_id = {rp["id"]: rp.get("path", "") for rp in real_projects if rp.get("path")}
            conv_roots_map = {}
            for c_row in conversations:
                cid_k = c_row.get("convId") or ""
                pid_k = conv_project_map.get(cid_k) or c_row.get("agProjectId") or ""
                roots_for_c = []
                if pid_k and proj_path_by_id.get(pid_k):
                    roots_for_c.append(proj_path_by_id[pid_k])
                for wp in workspace_paths:
                    if wp not in roots_for_c:
                        roots_for_c.append(wp)
                conv_roots_map[cid_k] = roots_for_c

            max_rows = int(cfg.get("maxRows") or 800)
            sent_files = collect_user_sent_files(
                app_data,
                conv_id,
                min(max_rows, 200),
                conv_roots_map=conv_roots_map,
                workspace_roots=workspace_paths,
                force_rescan=fresh,
            )
            sent_conv_keys = {(f.get("convId") or "", dsh_sync.path_key(f["path"])) for f in sent_files}
            sent_lower_set = {dsh_sync.path_key(f["path"]) for f in sent_files}

            raw_session = collect_all_session_files(
                app_data,
                conversations,
                conv_id,
                max_convs=20,
                conv_roots_map=conv_roots_map,
                workspace_roots=workspace_paths,
                force_rescan=fresh,
            )
            session_files = [
                f for f in raw_session
                if (f.get("convId") or "", dsh_sync.path_key(f["path"])) not in sent_conv_keys
                and "/.user_uploaded/" not in f["path"].lower().replace("\\", "/")
            ][:max_rows]

            scan_roots = list(real_projects) + [
                r for r in local_dir_roots
                if r.get("path", "").lower() not in {x.get("path", "").lower() for x in real_projects}
            ]
            recent_files = [
                f for f in collect_recent_project_files(
                    cfg.get("watchedDirs"),
                    max_items=min(max_rows, 320),
                    project_roots=scan_roots,
                    per_project=35,
                )
                if dsh_sync.path_key(f["path"]) not in sent_lower_set
                and "/.user_uploaded/" not in f["path"].lower().replace("\\", "/")
                and not dsh_sync.should_suppress_by_tombstone(f["path"], tombstones)
            ][:max_rows]

            search_dirs_for_moved = [r.get("path", "") for r in scan_roots if r.get("path")]
            sent_files = dsh_sync.reconcile_missing_and_moved(sent_files, tombstones, search_dirs_for_moved, sp["deletedIndex"])
            session_files = dsh_sync.reconcile_missing_and_moved(session_files, tombstones, search_dirs_for_moved, sp["deletedIndex"])

            pinned_set = {dsh_sync.path_key(p) for p in cfg.get("pinnedFiles", []) if p}
            archived_set = {dsh_sync.path_key(p) for p in cfg.get("archivedFiles", []) if p} | set(archive_records.keys())
            pinned_files = []
            for p in cfg.get("pinnedFiles", []):
                info = describe_file(p, action_kind="pinned", allow_missing=True)
                if info is not None and not dsh_sync.should_suppress_by_tombstone(info["path"], tombstones):
                    pinned_files.append(info)
            pinned_files = dsh_sync.reconcile_missing_and_moved(pinned_files, tombstones, search_dirs_for_moved, sp["deletedIndex"])

            archived_files = []
            archived_seen_keys = set()
            for p in cfg.get("archivedFiles", []):
                info = describe_file(p, action_kind="archived", allow_missing=True)
                if info is not None:
                    k = dsh_sync.path_key(info["path"])
                    rec = archive_records.get(k) or {}
                    info["archiveInfo"] = rec
                    if rec.get("archivedAt"):
                        info["archivedAt"] = rec["archivedAt"]
                    archived_files.append(info)
                    archived_seen_keys.add(k)
            for ak, rec in archive_records.items():
                if ak in archived_seen_keys:
                    continue
                src_p = rec.get("sourcePath") or ""
                if not src_p:
                    continue
                info = describe_file(
                    src_p,
                    action_kind="archived",
                    allow_missing=True,
                    last_known_size=int(rec.get("size") or 0),
                    last_known_mtime_ms=int(rec.get("archivedAt") or 0),
                )
                if info is not None:
                    info["archiveInfo"] = rec
                    info["archivedAt"] = rec.get("archivedAt") or 0
                    archived_files.append(info)
            archived_files.sort(key=lambda x: x.get("archivedAt") or x.get("mtimeMs") or 0, reverse=True)

            chat_attached_files = get_chat_attached(conv_id)

            known_conv_by_path = {}
            for item in (session_files + sent_files):
                if item.get("convId"):
                    known_conv_by_path.setdefault(dsh_sync.path_key(item["path"]), item["convId"])

            for flist in (session_files, sent_files, recent_files, pinned_files, archived_files, chat_attached_files):
                for item in flist:
                    low_p = dsh_sync.path_key(item["path"])
                    tag_file_project(
                        item,
                        real_projects,
                        conv_project_map=conv_project_map,
                        fallback_conv_id=known_conv_by_path.get(low_p, ""),
                        active_conv_id=conv_id,
                        workspace_projects=workspace_projects,
                        local_dir_roots=local_dir_roots,
                        conv_meta_map=conv_meta_map,
                    )
                    item["isPinned"] = low_p in pinned_set
                    item["isArchived"] = low_p in archived_set
                    if low_p in archive_records and "archiveInfo" not in item:
                        item["archiveInfo"] = archive_records[low_p]
                    if not item.get("source"):
                        item["source"] = dsh_sync.map_action_to_source(
                            item.get("actionKind", "recent"),
                            ext=item.get("ext", ""),
                            is_user_sent=bool(item.get("isUserSent")),
                        )
                        item["sourceLabel"] = dsh_sync.SOURCE_LABELS.get(item["source"], "文件")
                    item["matchedApps"] = get_matched_apps_for_ext(item.get("ext", ""), apps)

            ag_seen_paths = {}
            conv_seen_paths = {}
            local_seen_paths = {}
            for item in (session_files + sent_files + recent_files):
                if item.get("isArchived"):
                    continue
                low_p = dsh_sync.path_key(item["path"])
                if item.get("agProjectId"):
                    ag_seen_paths.setdefault(item["agProjectId"], set()).add(low_p)
                if item.get("convId"):
                    conv_seen_paths.setdefault(item["convId"], set()).add(low_p)
                if item.get("localDirId"):
                    local_seen_paths.setdefault(item["localDirId"], set()).add(low_p)

            real_proj_out = []
            for rp in real_projects:
                cnt = len(ag_seen_paths.get(rp["id"], set()))
                real_proj_out.append({
                    "id": rp["id"],
                    "name": rp["name"],
                    "path": rp.get("path", ""),
                    "kind": "project",
                    "isWorkspace": bool(rp.get("isWorkspace")),
                    "count": cnt,
                })

            conv_out = []
            for c in conversations:
                cid_item = c["convId"]
                cnt = len(conv_seen_paths.get(cid_item, set()))
                conv_out.append({
                    "id": c["id"],
                    "convId": cid_item,
                    "name": c["name"],
                    "kind": "conversation",
                    "isCurrent": bool(cid_item == conv_id),
                    "agProjectId": c.get("agProjectId", ""),
                    "count": cnt,
                })

            local_dirs_out = []
            for ld in local_dir_roots:
                cnt = len(local_seen_paths.get(ld["id"], set()))
                if cnt > 0:
                    local_dirs_out.append({
                        "id": ld["id"],
                        "name": ld["name"],
                        "path": ld["path"],
                        "kind": "local_dir",
                        "isWorkspace": False,
                        "count": cnt,
                    })

            projects = real_proj_out + conv_out + local_dirs_out

            if workspace_projects:
                active_scope_id = workspace_projects[0]["id"]
            elif conv_id and any(c["convId"] == conv_id for c in conv_out):
                active_scope_id = f"conv:{conv_id}"
            elif conv_out:
                active_scope_id = conv_out[0]["id"]
            else:
                active_scope_id = "all"

            pending_doc = None
            with QUEUE_COND:
                ipc = read_ipc_state()
                if query.get("client") == "sidecar":
                    ipc["lastSidecarSeen"] = time.time()
                    if query.get("visible") == "1":
                        ipc["lastSidecarVisible"] = time.time()
                    ipc["clientVer"] = query.get("ver") or "legacy"
                    if query.get("ver") != "2.4":
                        pending_doc = {
                            "file": {
                                "path": "__AUTO_RELOAD_SIDECAR__",
                                "name": "正在更新界面...",
                                "ext": ".docx",
                            },
                            "ts": time.time(),
                        }
                    write_ipc_state(ipc)
            pdf_ready = bool(dsh_sync.find_executable(["pdfinfo"]) and dsh_sync.find_executable(["pdftoppm"]))
            office_ready = bool(pdf_ready and dsh_sync.find_executable(["soffice", "libreoffice"]))
            archive_root = str(dsh_sync.resolve_archive_root(cfg, sp["defaultArchiveDir"]))
            self._send_json(200, {
                "ok": True,
                "serverVer": "2.4",
                "conversationId": conv_id,
                "activeScopeId": active_scope_id,
                "activeProjectId": active_scope_id,
                "realProjects": real_proj_out,
                "conversations": conv_out,
                "localDirs": local_dirs_out,
                "projects": projects,
                "platform": sys.platform,
                "apps": apps,
                "config": cfg,
                "archiveRoot": archive_root,
                "archiveRecords": archive_records,
                "settingsPaths": {k: str(v) for k, v in sp.items()},
                "capabilities": {
                    "pdfPages": pdf_ready,
                    "officePages": office_ready,
                },
                "sessionFiles": session_files,
                "sentFiles": sent_files,
                "recentFiles": recent_files,
                "pinnedFiles": pinned_files,
                "archivedFiles": archived_files,
                "chatAttachedFiles": chat_attached_files,
                "pendingInternalOpen": pending_doc,
            })
            return

        if route == "/api/internal-open":
            target_path = query.get("path") or ""
            conv_q = query.get("conversationId") or os.environ.get("ANTIGRAVITY_CONVERSATION_ID") or ""
            _, resolved_conv = resolve_active_conversation(conv_q)
            use_conv = conv_q if (conv_q and ID_RE.match(conv_q)) else resolved_conv
            side = build_side_uri(target_path, use_conv)
            if not side.get("ok"):
                self._send_json(200, {"ok": False, "error": side.get("error") or "文件不存在"})
                return
            info = dict(side["file"])
            info["openUri"] = side.get("uri") or ""
            info["sideKind"] = side.get("kind")
            info["matchedApps"] = get_matched_apps_for_ext(info.get("ext", ""), detect_installed_apps())
            active, action_id = push_ipc_action({"type": "open", "file": info, "conversationId": use_conv})
            append_embed_log(f"internal-open origin={self.headers.get('Origin')} kind={side.get('kind')} active={active} aid={action_id} path={target_path}")
            self._send_json(200, {"ok": True, "sidecarActive": active, "actionId": action_id, "file": info})
            return

        if route == "/api/attach":
            conv_q = query.get("conversationId") or os.environ.get("ANTIGRAVITY_CONVERSATION_ID") or ""
            _, resolved_conv = resolve_active_conversation(conv_q)
            use_conv = conv_q if (conv_q and ID_RE.match(conv_q)) else resolved_conv
            raw_paths = query.get("paths") or query.get("path") or ""
            try:
                paths = json.loads(raw_paths) if raw_paths.startswith("[") else [p for p in raw_paths.split("|") if p]
            except Exception:
                paths = [raw_paths] if raw_paths else []
            res = perform_batch_action("attach", paths, use_conv)
            files = res.get("files") or []
            if not res.get("ok") or not files:
                self._send_json(200, {"ok": False, "error": res.get("error") or "未找到有效文件"})
                return
            cfg = load_user_config()
            app_data, _ = resolve_active_conversation(use_conv)
            real_projects, _, conv_meta_map = load_sidebar_db_data(app_data, use_conv, None)
            local_dir_roots = discover_local_dir_roots(cfg)
            conv_project_map = infer_conv_project_map(app_data, real_projects)
            apps = detect_installed_apps(cfg.get("customApps"))
            for item in files:
                tag_file_project(
                    item,
                    real_projects,
                    conv_project_map=conv_project_map,
                    active_conv_id=use_conv,
                    local_dir_roots=local_dir_roots,
                    conv_meta_map=conv_meta_map,
                )
                item["matchedApps"] = get_matched_apps_for_ext(item.get("ext", ""), apps)
            chat_attached = record_chat_attached(use_conv, files)
            active, action_id = push_ipc_action({"type": "attach", "files": files, "conversationId": use_conv})
            append_embed_log(f"attach origin={self.headers.get('Origin')} count={len(files)} active={active} aid={action_id}")
            self._send_json(200, {
                "ok": True,
                "sidecarActive": active,
                "actionId": action_id,
                "count": len(files),
                "files": files,
                "chatAttachedFiles": chat_attached,
            })
            return

        if route == "/api/attach-record":
            conv_q = query.get("conversationId") or os.environ.get("ANTIGRAVITY_CONVERSATION_ID") or ""
            _, resolved_conv = resolve_active_conversation(conv_q)
            use_conv = conv_q if (conv_q and ID_RE.match(conv_q)) else resolved_conv
            raw_paths = query.get("paths") or query.get("path") or ""
            try:
                paths = json.loads(raw_paths) if raw_paths.startswith("[") else [p for p in raw_paths.split("|") if p]
            except Exception:
                paths = [raw_paths] if raw_paths else []
            res = perform_batch_action("attach", paths, use_conv)
            files = res.get("files") or []
            cfg = load_user_config()
            app_data, _ = resolve_active_conversation(use_conv)
            real_projects, _, conv_meta_map = load_sidebar_db_data(app_data, use_conv, None)
            local_dir_roots = discover_local_dir_roots(cfg)
            conv_project_map = infer_conv_project_map(app_data, real_projects)
            for item in files:
                tag_file_project(
                    item,
                    real_projects,
                    conv_project_map=conv_project_map,
                    active_conv_id=use_conv,
                    local_dir_roots=local_dir_roots,
                    conv_meta_map=conv_meta_map,
                )
            chat_attached = record_chat_attached(use_conv, files)
            self._send_json(200, {"ok": True, "count": len(files), "files": files, "chatAttachedFiles": chat_attached})
            return

        if route == "/api/attached":
            conv_q = query.get("conversationId") or os.environ.get("ANTIGRAVITY_CONVERSATION_ID") or ""
            _, resolved_conv = resolve_active_conversation(conv_q)
            use_conv = conv_q if (conv_q and ID_RE.match(conv_q)) else resolved_conv
            self._send_json(200, {
                "ok": True,
                "conversationId": use_conv,
                "chatAttachedFiles": get_chat_attached(use_conv),
            })
            return

        if route == "/api/detach":
            conv_q = query.get("conversationId") or os.environ.get("ANTIGRAVITY_CONVERSATION_ID") or ""
            _, resolved_conv = resolve_active_conversation(conv_q)
            use_conv = conv_q if (conv_q and ID_RE.match(conv_q)) else resolved_conv
            op = query.get("op") or ""
            raw_paths = query.get("paths") or query.get("path") or ""
            try:
                paths = json.loads(raw_paths) if raw_paths.startswith("[") else [p for p in raw_paths.split("|") if p]
            except Exception:
                paths = [raw_paths] if raw_paths else []
            chat_attached = remove_chat_attached(use_conv, paths, clear=(op == "clear"))
            with QUEUE_COND:
                ipc = read_ipc_state()
                now = time.time()
                if (now - float(ipc.get("lastSidecarVisible") or 0)) < 20.0:
                    q = [a for a in (ipc.get("queue") or []) if a.get("type") != "sync_attached" and now - float(a.get("ts") or 0) < 60.0]
                    q.append({"type": "sync_attached", "chatAttachedFiles": chat_attached, "conversationId": use_conv, "ts": now})
                    ipc["queue"] = q[-30:]
                    write_ipc_state(ipc)
                    QUEUE_COND.notify_all()
            append_embed_log(f"detach op={op or 'single'} count={len(paths)} remain={len(chat_attached)}")
            self._send_json(200, {"ok": True, "chatAttachedFiles": chat_attached})
            return

        if route == "/api/ack":
            raw_ids = query.get("ids") or query.get("id") or ""
            ids = [x for x in raw_ids.split(",") if x.strip()]
            ack_ipc_actions(ids)
            self._send_json(200, {"ok": True, "acked": ids})
            return

        if route == "/api/action-status":
            aid = (query.get("id") or "").strip()
            with QUEUE_COND:
                ipc = read_ipc_state()
                now = time.time()
                acked = aid in (ipc.get("ackedIds") or {})
                vis = (now - float(ipc.get("lastSidecarVisible") or 0)) < 20.0
            self._send_json(200, {"ok": True, "id": aid, "acked": acked, "visible": vis})
            return

        if route == "/api/visibility":
            vis = query.get("visible") == "1"
            with QUEUE_COND:
                ipc = read_ipc_state()
                now = time.time()
                ipc["lastSidecarSeen"] = now
                if vis:
                    ipc["lastSidecarVisible"] = now
                else:
                    ipc["lastSidecarVisible"] = 0.0
                write_ipc_state(ipc)
            self._send_json(200, {"ok": True, "visible": vis})
            return

        if route == "/api/side-uri":
            conv_q = query.get("conversationId") or os.environ.get("ANTIGRAVITY_CONVERSATION_ID") or ""
            res = build_side_uri(query.get("path") or "", conv_q)
            res.pop("file", None)
            self._send_json(200, res)
            return

        if route == "/api/embed-log":
            append_embed_log(f"embed origin={self.headers.get('Origin')} msg={query.get('msg') or ''}")
            self._send_bytes(200, "image/gif", b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;")
            return

        if route == "/api/poll-open":
            visible = query.get("visible") == "1"
            try:
                wait_sec = min(max(float(query.get("wait") or "0"), 0.0), 20.0)
            except Exception:
                wait_sec = 0.0
            deadline = time.time() + wait_sec
            with QUEUE_COND:
                ipc = read_ipc_state()
                now = time.time()
                ipc["lastSidecarSeen"] = now
                if visible:
                    ipc["lastSidecarVisible"] = now
                    queue = [a for a in (ipc.get("queue") or []) if now - float(a.get("ts") or 0) < 60.0]
                else:
                    queue = []

                if visible and not queue and wait_sec > 0:
                    write_ipc_state(ipc)
                    while True:
                        rem = deadline - time.time()
                        if rem <= 0:
                            break
                        QUEUE_COND.wait(timeout=rem)
                        ipc = read_ipc_state()
                        now = time.time()
                        queue = [a for a in (ipc.get("queue") or []) if now - float(a.get("ts") or 0) < 60.0]
                        if queue:
                            break
                elif not visible and wait_sec > 0:
                    # Sleep cleanly without touching or draining queued actions when obscured/hidden
                    ipc["lastSidecarVisible"] = 0.0
                    write_ipc_state(ipc)
                    rem = deadline - time.time()
                    if rem > 0:
                        QUEUE_COND.wait(timeout=min(rem, 10.0))

                now = time.time()
                ipc = read_ipc_state()
                ipc["lastSidecarSeen"] = now
                if visible:
                    ipc["lastSidecarVisible"] = now
                    ipc["queue"] = []
                    ipc["pendingInternalOpen"] = None
                else:
                    ipc["lastSidecarVisible"] = 0.0
                write_ipc_state(ipc)
            self._send_json(200, {"ok": True, "visible": visible, "queue": queue, "pendingInternalOpen": None})
            return

        if route == "/api/preview":
            target_path = query.get("path") or ""
            self._send_json(200, generate_file_preview(target_path))
            return

        if route == "/api/raw":
            target_path = os.path.normpath(query.get("path") or "")
            if os.path.isfile(target_path):
                ctype, _ = mimetypes.guess_type(target_path)
                self._send_bytes(200, ctype or "application/octet-stream", Path(target_path).read_bytes())
                return
            self._send_bytes(404, "text/plain; charset=utf-8", b"File not found")
            return

        if route == "/api/open":
            target_path = query.get("path") or ""
            mode = query.get("mode") or "default"
            app_id = query.get("appId") or ""
            custom_exe = query.get("customExe") or ""
            remember = query.get("rememberExt") in ("1", "true")

            if remember and target_path and app_id:
                ext = os.path.splitext(target_path)[1].lower()
                if ext:
                    cfg = load_user_config()
                    cfg.setdefault("extDefaults", {})[ext] = app_id
                    save_user_config(cfg)

            res = perform_file_action(target_path, mode=mode, app_id=app_id, custom_exe=custom_exe)
            self._send_json(200, res)
            return

        if route == "/api/batch":
            op = query.get("op") or ""
            raw_paths = query.get("paths") or query.get("path") or ""
            try:
                paths = json.loads(raw_paths) if raw_paths.startswith("[") else [p for p in raw_paths.split("|") if p]
            except Exception:
                paths = [raw_paths] if raw_paths else []
            conv_id = query.get("conversationId") or os.environ.get("ANTIGRAVITY_CONVERSATION_ID") or ""
            self._send_json(200, perform_batch_action(op, paths, conv_id))
            return

        if route == "/api/open-folder":
            target_path = query.get("path") or ""
            res = perform_file_action(target_path, mode="reveal")
            self._send_json(200, res)
            return

        if route == "/api/pdf-pages":
            target_path = query.get("path") or ""
            cfg = load_user_config()
            sp = get_store_paths()
            res = dsh_sync.render_document_pages(
                target_path,
                sp["rendersDir"],
                pdf_max_pages=cfg.get("pdfMaxPages", 20),
                pdf_dpi=cfg.get("pdfDpi", 110),
            )
            self._send_json(200, res)
            return

        if route == "/api/pdf-image":
            token = query.get("token") or ""
            page_str = query.get("page") or "1"
            sp = get_store_paths()
            img_path = dsh_sync.resolve_render_image_path(sp["rendersDir"], token, page_str)
            if not img_path:
                self._send_bytes(404, "text/plain; charset=utf-8", b"Rendered page not found")
                return
            try:
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                data_bytes = img_path.read_bytes()
                self.send_header("Content-Length", str(len(data_bytes)))
                self.send_header("Cache-Control", "private, max-age=3600")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(data_bytes)
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
            return

        if route == "/api/settings":
            cfg = load_user_config()
            sp = get_store_paths()
            pdf_ready = bool(dsh_sync.find_executable(["pdfinfo"]) and dsh_sync.find_executable(["pdftoppm"]))
            office_ready = bool(pdf_ready and dsh_sync.find_executable(["soffice", "libreoffice"]))
            self._send_json(200, {
                "ok": True,
                "settings": cfg,
                "archiveRoot": str(dsh_sync.resolve_archive_root(cfg, sp["defaultArchiveDir"])),
                "paths": {k: str(v) for k, v in sp.items()},
                "apps": detect_installed_apps(cfg.get("customApps")),
                "capabilities": {"pdfPages": pdf_ready, "officePages": office_ready},
            })
            return

        if route == "/api/pin":
            target_path = (query.get("path") or "").strip()
            op = query.get("op") or "add"
            conv_id = query.get("conversationId") or os.environ.get("ANTIGRAVITY_CONVERSATION_ID") or ""
            if not target_path:
                self._send_json(200, {"ok": False, "error": "Missing path"})
                return
            norm = os.path.normpath(target_path)
            cfg = load_user_config()
            pins = list(cfg.get("pinnedFiles") or [])
            if op == "remove":
                pins = [p for p in pins if p.lower() != norm.lower()]
            else:
                if not os.path.exists(norm):
                    self._send_json(200, {"ok": False, "error": f"Path not found: {norm}"})
                    return
                if not any(p.lower() == norm.lower() for p in pins):
                    pins.insert(0, norm)
            cfg["pinnedFiles"] = pins
            save_user_config(cfg)
            sync_anti_compaction_manifest(pins, conv_id)
            self._send_json(200, {"ok": True, "pinnedFiles": pins})
            return

        if route == "/api/config":
            cfg = load_user_config()
            op = query.get("op") or ""
            if op == "set_ext_default":
                ext = (query.get("ext") or "").lower()
                app_id = query.get("appId") or "default"
                if ext:
                    if app_id == "default":
                        cfg.get("extDefaults", {}).pop(ext, None)
                    else:
                        cfg.setdefault("extDefaults", {})[ext] = app_id
                    save_user_config(cfg)
            elif op == "add_watched_dir":
                d = os.path.normpath((query.get("dir") or "").strip())
                if not d or not os.path.exists(d):
                    self._send_json(200, {"ok": False, "error": f"Directory does not exist: {d}"})
                    return
                if not any(x.lower() == d.lower() for x in cfg["watchedDirs"]):
                    cfg["watchedDirs"].append(d)
                    save_user_config(cfg)
            elif op == "remove_watched_dir":
                d = os.path.normpath((query.get("dir") or "").strip())
                cfg["watchedDirs"] = [x for x in cfg["watchedDirs"] if x.lower() != d.lower()]
                save_user_config(cfg)
            elif op == "add_custom_app":
                name = (query.get("name") or "").strip()
                exe = os.path.normpath((query.get("exe") or "").strip())
                if not name or not exe or not os.path.exists(exe):
                    self._send_json(200, {"ok": False, "error": f"Executable not found: {exe}"})
                    return
                cfg["customApps"] = [a for a in cfg["customApps"] if a.get("name", "").lower() != name.lower()]
                cid = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "app"
                cfg["customApps"].append({"id": cid, "name": name, "exe": exe, "icon": "🔧"})
                save_user_config(cfg)
            elif op == "remove_custom_app":
                name = (query.get("name") or "").strip()
                cfg["customApps"] = [a for a in cfg["customApps"] if a.get("name", "").lower() != name.lower()]
                save_user_config(cfg)

            cfg = load_user_config()
            self._send_json(200, {"ok": True, "config": cfg, "apps": detect_installed_apps(cfg.get("customApps"))})
            return

        self._send_bytes(404, "text/plain; charset=utf-8", b"Not found")

    def do_POST(self):
        parsed = urlparse(self.path)
        route = parsed.path
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length).decode("utf-8", errors="ignore") if length > 0 else "{}"
        try:
            data = json.loads(body) if body else {}
        except Exception:
            data = {}

        if route == "/_sidecar/get-conversation-metadata":
            conv_id = data.get("conversationId") or os.environ.get("ANTIGRAVITY_CONVERSATION_ID") or ""
            self._send_json(200, run_agentapi(["get-conversation-metadata", conv_id]))
            return
        if route == "/_sidecar/send-message":
            conv_id = data.get("conversationId") or os.environ.get("ANTIGRAVITY_CONVERSATION_ID") or ""
            msg = data.get("message") or ""
            self._send_json(200, run_agentapi(["send-message", conv_id, msg]))
            return
        if route == "/_sidecar/new-conversation":
            msg = data.get("message") or ""
            model = data.get("model") or "flash"
            self._send_json(200, run_agentapi(["new-conversation", "--model", model, msg]))
            return

        if route == "/api/settings":
            sp = get_store_paths()
            patch = data.get("settings") if isinstance(data.get("settings"), dict) else data
            cfg = dsh_sync.update_settings_patch(sp["config"], patch if isinstance(patch, dict) else {})
            pdf_ready = bool(dsh_sync.find_executable(["pdfinfo"]) and dsh_sync.find_executable(["pdftoppm"]))
            office_ready = bool(pdf_ready and dsh_sync.find_executable(["soffice", "libreoffice"]))
            self._send_json(200, {
                "ok": True,
                "settings": cfg,
                "config": cfg,
                "archiveRoot": str(dsh_sync.resolve_archive_root(cfg, sp["defaultArchiveDir"])),
                "paths": {k: str(v) for k, v in sp.items()},
                "apps": detect_installed_apps(cfg.get("customApps")),
                "capabilities": {"pdfPages": pdf_ready, "officePages": office_ready},
            })
            return

        if route == "/api/batch":
            op = str(data.get("op") or "")
            paths = data.get("paths") or ([data.get("path")] if data.get("path") else [])
            conv_id = data.get("conversationId") or os.environ.get("ANTIGRAVITY_CONVERSATION_ID") or ""
            self._send_json(200, perform_batch_action(op, paths, conv_id))
            return

        if route == "/api/open":
            target_path = str(data.get("path") or "")
            mode = str(data.get("mode") or "default")
            app_id = str(data.get("appId") or "")
            custom_exe = str(data.get("customExe") or "")
            remember = bool(data.get("rememberExt"))
            if remember and target_path and app_id:
                ext = os.path.splitext(target_path)[1].lower()
                if ext:
                    cfg = load_user_config()
                    cfg.setdefault("extDefaults", {})[ext] = app_id
                    save_user_config(cfg)
            self._send_json(200, perform_file_action(target_path, mode=mode, app_id=app_id, custom_exe=custom_exe))
            return

        if route == "/api/open-folder":
            target_path = str(data.get("path") or "")
            self._send_json(200, perform_file_action(target_path, mode="reveal"))
            return

        if route == "/api/pin":
            target_path = str(data.get("path") or "").strip()
            op = str(data.get("op") or "add")
            conv_id = data.get("conversationId") or os.environ.get("ANTIGRAVITY_CONVERSATION_ID") or ""
            if not target_path:
                self._send_json(200, {"ok": False, "error": "Missing path"})
                return
            norm = os.path.normpath(target_path)
            cfg = load_user_config()
            pins = list(cfg.get("pinnedFiles") or [])
            if op == "remove":
                pins = [p for p in pins if p.lower() != norm.lower()]
            else:
                if not os.path.exists(norm):
                    self._send_json(200, {"ok": False, "error": f"Path not found: {norm}"})
                    return
                if not any(p.lower() == norm.lower() for p in pins):
                    pins.insert(0, norm)
            cfg["pinnedFiles"] = pins
            save_user_config(cfg)
            sync_anti_compaction_manifest(pins, conv_id)
            self._send_json(200, {"ok": True, "pinnedFiles": pins})
            return

        if route == "/api/forget":
            paths = data.get("paths") or ([data.get("path")] if data.get("path") else [])
            conv_id = data.get("conversationId") or os.environ.get("ANTIGRAVITY_CONVERSATION_ID") or ""
            sp = get_store_paths()
            res = dsh_sync.forget_files_dsh(
                paths,
                sp["config"],
                sp["archiveIndex"],
                sp["deletedIndex"],
                sp["sentIndex"],
                pinned_manifest_sync_cb=lambda new_pins: sync_anti_compaction_manifest(new_pins, conv_id),
            )
            if res.get("ok") and conv_id and res.get("forgotten"):
                try:
                    remove_chat_attached(conv_id, res["forgotten"])
                except Exception:
                    pass
            self._send_json(200, res)
            return

        if route == "/api/delete":
            paths = data.get("paths") or ([data.get("path")] if data.get("path") else [])
            confirm = data.get("confirm") is True
            conv_id = data.get("conversationId") or os.environ.get("ANTIGRAVITY_CONVERSATION_ID") or ""
            sp = get_store_paths()
            preview_roots = []
            if app_dirs := find_app_data_dirs():
                brain_p = Path(app_dirs[0]) / "brain"
                if brain_p.is_dir():
                    try:
                        preview_roots = [Path(e.path) / "fl_preview" for e in os.scandir(brain_p) if e.is_dir()]
                    except Exception:
                        pass
            res = dsh_sync.delete_files_permanently_dsh(
                paths,
                confirm,
                sp["config"],
                sp["archiveIndex"],
                sp["deletedIndex"],
                sp["sentIndex"],
                preview_roots=preview_roots,
                renders_dir=sp["rendersDir"],
                pinned_manifest_sync_cb=lambda new_pins: sync_anti_compaction_manifest(new_pins, conv_id),
            )
            if res.get("deleted") and conv_id:
                try:
                    remove_chat_attached(conv_id, res["deleted"])
                except Exception:
                    pass
            self._send_json(200, res)
            return

        if route == "/api/pdf-pages":
            target_path = str(data.get("path") or "")
            cfg = load_user_config()
            sp = get_store_paths()
            max_p = data.get("maxPages") or cfg.get("pdfMaxPages", 20)
            dpi = data.get("dpi") or cfg.get("pdfDpi", 110)
            res = dsh_sync.render_document_pages(
                target_path,
                sp["rendersDir"],
                pdf_max_pages=max_p,
                pdf_dpi=dpi,
            )
            self._send_json(200, res)
            return

        self._send_json(404, {"error": "Not found"})


def main():
    if "--selftest" in sys.argv:
        app_data, conv_id = resolve_active_conversation("")
        cfg = load_user_config()
        apps = detect_installed_apps(cfg.get("customApps"))
        session_files = collect_session_files(app_data, conv_id)
        recent_files = collect_recent_project_files(cfg.get("watchedDirs"), 10)
        print(json.dumps({
            "selftest": "PASS",
            "appData": str(app_data),
            "convId": conv_id,
            "detectedAppsCount": len(apps),
            "detectedApps": [a["name"] for a in apps],
            "sessionFilesCount": len(session_files),
            "sampleSessionFiles": [f["path"] for f in session_files[:5]],
            "recentFilesCount": len(recent_files),
            "sampleRecentFiles": [f["path"] for f in recent_files[:5]],
        }, ensure_ascii=False, indent=2))
        return

    ThreadingHTTPServer.daemon_threads = True
    ThreadingHTTPServer.allow_reuse_address = True
    fixed_port = 18765
    try:
        bridge_server = ThreadingHTTPServer(("127.0.0.1", fixed_port), SidecarRequestHandler)
        t = threading.Thread(target=bridge_server.serve_forever, daemon=True)
        t.start()
        print(f"[sidecar-bridge] listening on 127.0.0.1:{fixed_port}", flush=True)
    except Exception as e:
        print(f"[sidecar-bridge] port {fixed_port} skipped: {e}", flush=True)

    port = int(os.environ.get("ANTIGRAVITY_SIDECAR_WEB_PORT") or "0")
    server = ThreadingHTTPServer(("127.0.0.1", port), SidecarRequestHandler)
    actual_port = server.server_address[1]
    print(f"[sidecar] listening on 127.0.0.1:{actual_port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
