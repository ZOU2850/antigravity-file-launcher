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
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

HERE = Path(__file__).resolve().parent
IS_WIN = platform.system().lower() == "windows"
ID_RE = re.compile(r"^[0-9a-f-]{8,}$", re.IGNORECASE)

# 默认只展示对普通用户可读的成品文档与媒体文件；代码/配置在侧边栏仅作为单独分类标签按需查看
READABLE_EXTS = {
    ".docx", ".doc", ".pptx", ".ppt", ".xlsx", ".xls", ".csv", ".pdf",
    ".md", ".txt", ".rtf", ".html", ".htm",
    ".png", ".jpg", ".jpeg", ".webp", ".svg", ".gif",
    ".mp4", ".mp3", ".wav"
}
DELIVERABLE_EXTS = READABLE_EXTS | {
    ".py", ".js", ".mjs", ".ts", ".css", ".json", ".ps1", ".xml", ".yaml", ".yml", ".zip"
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


def read_ipc_state():
    p = get_ipc_path()
    if not p.exists():
        return {"lastSidecarSeen": 0.0, "pendingInternalOpen": None}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {"lastSidecarSeen": 0.0, "pendingInternalOpen": None}


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


def default_config():
    default_dir = "D:\\projects" if (IS_WIN and Path("D:\\projects").exists()) else str(Path.home() / "Desktop")
    return {
        "watchedDirs": [default_dir],
        "pinnedFiles": [],
        "archivedFiles": [],
        "customApps": [],
        "extDefaults": {},
    }


import shutil as _shutil


def sync_anti_compaction_manifest(pinned_paths, active_conv_id=""):
    """
    Persist a human- and AI-readable manifest of pinned (anti-compaction protected) files
    both in D:\\projects\\Pinned_Protected_Files and in the active conversation brain directory,
    so context compaction NEVER loses track of starred files.
    """
    prot_dir = Path("D:\\projects\\Pinned_Protected_Files") if IS_WIN else (Path.home() / "Pinned_Protected_Files")
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

    if not norm_paths and op not in ("unpin", "unarchive"):
        return {"ok": False, "error": "未找到有效的文件路径"}

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
        arch_dir = Path("D:\\projects\\Archived_Docs") if IS_WIN else (Path.home() / "Archived_Docs")
        arch_dir.mkdir(parents=True, exist_ok=True)
        archived_out = []
        for p in norm_paths:
            dst = arch_dir / os.path.basename(p)
            try:
                if os.path.isfile(p) and os.path.abspath(p).lower() != os.path.abspath(str(dst)).lower():
                    _shutil.copy2(p, dst)
            except Exception:
                pass
            if not any(x.lower() == p.lower() for x in archived):
                archived.insert(0, p)
            archived_out.append(str(dst))
        cfg["archivedFiles"] = archived
        save_user_config(cfg)
        return {"ok": True, "op": op, "count": len(norm_paths), "archiveDir": str(arch_dir), "archivedFiles": archived}

    if op == "unarchive":
        raw_checks = {os.path.normpath(p.strip()).lower() for p in (paths or []) if p}
        archived = [x for x in archived if x.lower() not in raw_checks]
        cfg["archivedFiles"] = archived
        save_user_config(cfg)
        return {"ok": True, "op": op, "archivedFiles": archived}

    if op == "copy_chat_refs":
        refs = [f"@{p}" for p in norm_paths]
        clip_text = " ".join(refs) + " "
        if IS_WIN:
            try:
                p_clip = subprocess.Popen(["clip.exe"], stdin=subprocess.PIPE)
                p_clip.communicate(input=clip_text.encode("utf-16-le"))
            except Exception:
                pass
        return {"ok": True, "op": op, "count": len(norm_paths), "chatText": clip_text, "refs": refs}

    return {"ok": False, "error": f"未知操作: {op}"}


def load_user_config():
    p = get_config_path()
    cfg = default_config()
    if not p.exists():
        return cfg
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(raw.get("watchedDirs"), list) and raw["watchedDirs"]:
            cfg["watchedDirs"] = raw["watchedDirs"]
        if isinstance(raw.get("pinnedFiles"), list):
            cfg["pinnedFiles"] = raw["pinnedFiles"]
        if isinstance(raw.get("archivedFiles"), list):
            cfg["archivedFiles"] = raw["archivedFiles"]
        if isinstance(raw.get("customApps"), list):
            cfg["customApps"] = raw["customApps"]
        if isinstance(raw.get("extDefaults"), dict):
            cfg["extDefaults"] = raw["extDefaults"]
    except Exception:
        pass
    return cfg


def save_user_config(cfg):
    p = get_config_path()
    try:
        p.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
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
    ("word", "Word", {".docx", ".doc", ".rtf"}),
    ("markdown", "Markdown", {".md"}),
    ("ppt", "PPT", {".pptx", ".ppt"}),
    ("excel", "Excel", {".xlsx", ".xls", ".csv"}),
    ("pdf", "PDF", {".pdf"}),
    ("image", "图片", {".png", ".jpg", ".jpeg", ".webp", ".svg", ".gif"}),
    ("text", "文本/网页", {".txt", ".html", ".htm"}),
]


def classify_extension(ext, is_dir=False):
    if is_dir:
        return "other", "文件夹", False
    e = (ext or "").lower()
    for cid, clabel, exts in FILE_TYPE_GROUPS:
        if e in exts:
            return cid, clabel, True
    if e in (".mp4", ".mp3", ".wav"):
        return "media", "音视频", True
    return "code", "代码/其他", False


def describe_file(raw_path, action_kind="recent", step_index=-1):
    if not raw_path or not isinstance(raw_path, str):
        return None
    norm = os.path.normpath(raw_path.strip())
    if not os.path.isabs(norm) or not os.path.exists(norm):
        return None
    try:
        st = os.stat(norm)
    except Exception:
        return None
    is_dir = os.path.isdir(norm)
    ext = "" if is_dir else os.path.splitext(norm)[1].lower()
    if is_dir:
        cat = {"badge": "DIR", "color": "amber", "icon": "📁", "priority": 75}
    else:
        cat = CATEGORY_MAP.get(ext, {
            "badge": (ext[1:] or "FILE").upper()[:6],
            "color": "slate",
            "icon": "📄",
            "priority": 50,
        })
    try:
        file_uri = Path(norm).as_uri()
    except Exception:
        file_uri = "file:///" + norm.replace("\\", "/")

    return {
        "path": norm,
        "name": os.path.basename(norm) or norm,
        "dir": os.path.dirname(norm),
        "ext": ext,
        "isDir": is_dir,
        "size": 0 if is_dir else st.st_size,
        "mtimeMs": int(st.st_mtime * 1000),
        "fileUri": file_uri,
        "badge": cat["badge"],
        "color": cat["color"],
        "icon": cat["icon"],
        "priority": cat["priority"],
        "actionKind": action_kind,
        "stepIndex": step_index,
        "category": classify_extension(ext, is_dir)[0],
        "categoryLabel": classify_extension(ext, is_dir)[1],
        "isReadable": classify_extension(ext, is_dir)[2],
    }


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


def extract_paths_from_user_step(step, ai_created_lower_set):
    """Extract ONLY files explicitly sent/attached by the human user in a USER_INPUT step."""
    paths = []
    if not isinstance(step, dict):
        return paths

    # 1. Media attachments explicitly uploaded by the user in this message
    for m in step.get("media") or []:
        if not isinstance(m, dict):
            continue
        uri = m.get("uri") or m.get("path") or ""
        if uri:
            lp = file_uri_to_local_path(uri) if uri.lower().startswith("file://") else os.path.normpath(uri)
            if lp and os.path.isfile(lp) and lp.lower() not in ai_created_lower_set:
                paths.append(lp)

    # 2. Extract only from <USER_REQUEST>...</USER_REQUEST> (strip <CONTEXT_SUMMARY> & <SYSTEM_MESSAGE>)
    content = step.get("content")
    if isinstance(content, str) and content:
        # Also capture explicit [Attachment: ... (path)] lines if present
        for m in re.finditer(r"\[Attachment:[^\]]*\(([A-Za-z]:[\\/][^\r\n()\"'<>]+)\)\]", content):
            cand = os.path.normpath(m.group(1).strip())
            if os.path.isfile(cand) and cand.lower() not in ai_created_lower_set:
                paths.append(cand)

        # Strip system summary blocks so AI artifacts in summaries are NEVER mistaken for user-sent files
        cleaned = re.sub(r"<CONTEXT_SUMMARY>[\s\S]*?</CONTEXT_SUMMARY>", "", content, flags=re.IGNORECASE)
        cleaned = re.sub(r"<SYSTEM_MESSAGE>[\s\S]*?</SYSTEM_MESSAGE>", "", cleaned, flags=re.IGNORECASE)
        user_reqs = re.findall(r"<USER_REQUEST>([\s\S]*?)</USER_REQUEST>", cleaned, flags=re.IGNORECASE)
        user_text = "\n".join(user_reqs) if user_reqs else cleaned

        for m in re.finditer(r"file:///[^\s)\"'\]>`]+", user_text, flags=re.IGNORECASE):
            lp = file_uri_to_local_path(m.group(0))
            if lp and os.path.isfile(lp) and lp.lower() not in ai_created_lower_set:
                paths.append(lp)

        for m in re.finditer(r"(?:^|[\s@\"'])([A-Za-z]:[\\/][^\s\"'<>|?*]+\.[A-Za-z0-9]{1,8})", user_text):
            cand = os.path.normpath(m.group(1).strip())
            if os.path.isfile(cand) and cand.lower() not in ai_created_lower_set:
                paths.append(cand)

    return paths


def collect_ai_created_paths(conv_folder):
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
                if tc.get("name") in ("write_file", "edit_file"):
                    args = tc.get("args") or {}
                    if isinstance(args, dict):
                        p = unquote_arg(args.get("Path") or args.get("AbsolutePath") or args.get("TargetFile") or "")
                        if p:
                            ai_set.add(os.path.normpath(p).lower())
    except Exception:
        pass
    return ai_set


def collect_user_sent_files(app_data, active_conv_id, max_items=60):
    """Collect ONLY files sent/uploaded by the user, 100% isolated from AI deliverables."""
    if not app_data:
        return []
    brain_dir = Path(app_data) / "brain"
    if not brain_dir.exists():
        return []

    sent_map = {}

    def add_sent(raw_p, is_current_conv, step_idx=0):
        info = describe_file(raw_p, action_kind="user_sent", step_index=step_idx)
        if not info or info.get("isDir"):
            return
        lower = info["path"].lower()
        if (
            ".system_generated" in lower
            or "\\builtin\\skills\\" in lower
            or "\\builtin\\plugins\\" in lower
            or ("\\brain\\" in lower and "\\scratch\\" in lower)
            or "\\browser_evidence\\" in lower
            or "\\browser_sandbox\\" in lower
        ):
            return
        info["isUserSent"] = True
        info["isReadable"] = True
        info["sentScope"] = "current" if is_current_conv else "history"
        info["sentScopeLabel"] = "当前会话发送" if is_current_conv else "历史会话发送"

        prev = sent_map.get(lower)
        if not prev:
            sent_map[lower] = info
        else:
            if is_current_conv and prev.get("sentScope") != "current":
                prev["sentScope"] = "current"
                prev["sentScopeLabel"] = "当前会话发送"
            if step_idx > prev.get("stepIndex", -1):
                prev["stepIndex"] = step_idx

    def scan_conv_for_sent(conv_folder, is_current):
        ai_created = collect_ai_created_paths(conv_folder)

        # A. Scan .user_uploaded folder (100% user-uploaded attachments in Antigravity)
        up_dir = conv_folder / ".user_uploaded"
        if up_dir.exists() and up_dir.is_dir():
            try:
                for entry in os.scandir(up_dir):
                    if entry.is_file():
                        add_sent(entry.path, is_current, 10000 if is_current else 5000)
            except Exception:
                pass

        # B. Scan USER_INPUT steps in transcript.jsonl
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
                        for p in extract_paths_from_user_step(step, ai_created):
                            add_sent(p, is_current, idx)
            except Exception:
                pass

    # 1. Scan active conversation first
    if active_conv_id and ID_RE.match(active_conv_id):
        active_folder = brain_dir / active_conv_id
        if active_folder.exists():
            scan_conv_for_sent(active_folder, True)

    # 2. Scan recent conversations for user-sent files
    try:
        conv_entries = []
        for entry in os.scandir(brain_dir):
            if entry.is_dir() and ID_RE.match(entry.name) and entry.name != active_conv_id:
                try:
                    conv_entries.append((entry.stat().st_mtime, Path(entry.path)))
                except Exception:
                    pass
        conv_entries.sort(key=lambda x: x[0], reverse=True)
        for _, cpath in conv_entries[:15]:
            scan_conv_for_sent(cpath, False)
    except Exception:
        pass

    result = list(sent_map.values())
    result.sort(
        key=lambda x: (
            1 if x.get("sentScope") == "current" else 0,
            x.get("mtimeMs", 0),
            x.get("stepIndex", 0),
        ),
        reverse=True,
    )
    return result[:max_items]


def collect_session_files(app_data, conv_id):
    if not app_data or not conv_id or not ID_RE.match(conv_id):
        return []
    items = {}

    def upsert(raw_p, action_kind, step_idx=0):
        info = describe_file(raw_p, action_kind=action_kind, step_index=step_idx)
        if not info:
            return
        lower = info["path"].lower()
        if (
            ".system_generated" in lower
            or "\\builtin\\skills\\" in lower
            or "\\builtin\\plugins\\" in lower
            or ("\\brain\\" in lower and "\\scratch\\" in lower)
            or "\\.user_uploaded\\" in lower
        ):
            return
        prev = items.get(lower)
        if not prev:
            items[lower] = info
            return
        if ACTION_WEIGHT.get(action_kind, 0) >= ACTION_WEIGHT.get(prev["actionKind"], 0):
            prev["actionKind"] = action_kind
        if step_idx > prev["stepIndex"]:
            prev["stepIndex"] = step_idx

    conv_dir = Path(app_data) / "brain" / conv_id

    def scan_artifact_dir(d, depth=0):
        if depth > 2 or not d.exists():
            return
        try:
            for entry in os.scandir(d):
                if entry.name.startswith(".") or entry.name == "browser_sandbox":
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
                    if not isinstance(args, dict):
                        continue
                    p = unquote_arg(args.get("Path") or args.get("AbsolutePath") or args.get("TargetFile") or "")
                    if p:
                        if tname == "write_file":
                            upsert(p, "created", idx)
                        elif tname == "edit_file":
                            upsert(p, "edited", idx)
                        elif tname == "read_file":
                            upsert(p, "read", idx)

                if step.get("type") == "PLANNER_RESPONSE" and isinstance(step.get("content"), str):
                    for m in re.finditer(r"file:///[^\s)\"'\]>`]+", step["content"], flags=re.IGNORECASE):
                        lp = file_uri_to_local_path(m.group(0))
                        if lp:
                            upsert(lp, "linked", idx)
        except Exception:
            pass

    # Also include any files from D:\projects\file_launcher_test_demo so demo deliverables are always visible at top
    demo_dir = Path(r"D:\projects\file_launcher_test_demo")
    if demo_dir.exists():
        for entry in os.scandir(demo_dir):
            if entry.is_file():
                upsert(entry.path, "created", 99999)

    result = list(items.values())
    result.sort(
        key=lambda x: (
            1 if x["ext"] in (".docx", ".doc", ".pptx", ".ppt", ".xlsx", ".pdf", ".md") else 0,
            ACTION_WEIGHT.get(x["actionKind"], 0),
            x["stepIndex"],
            x["mtimeMs"],
        ),
        reverse=True,
    )
    return result


def collect_recent_project_files(watched_dirs, max_items=50):
    found = []
    seen = set()

    def walk(d, depth=0):
        if depth > 3 or not os.path.exists(d):
            return
        try:
            for entry in os.scandir(d):
                if entry.name.startswith("."):
                    continue
                if entry.is_dir():
                    if entry.name.lower() in SKIP_DIRS:
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
                        found.append(info)
        except Exception:
            pass

    for root in watched_dirs or []:
        if root and os.path.exists(root):
            walk(root, 0)

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
            dirs = find_app_data_dirs()
            base = dirs[0] if dirs else (Path.home() / ".gemini" / "antigravity")
            cache_dir = base / "preview_cache"
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


def generate_file_preview(target_path):
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
        if ext == ".csv":
            raw_text = Path(real).read_text(encoding="utf-8", errors="replace")
            reader = list(csv.reader(raw_text.splitlines()[:60]))
            rows = []
            for idx, r in enumerate(reader):
                tag = "th" if idx == 0 else "td"
                rows.append("<tr>" + "".join(f"<{tag}>{html_mod.escape(c)}</{tag}>" for c in r) + "</tr>")
            return {"ok": True, "kind": "html", "title": name, "badge": "CSV 表格内置阅读", "html": '<table class="doc-table">' + "".join(rows) + "</table>"}
        if ext in (".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"):
            return {"ok": True, "kind": "image", "title": name, "badge": "图片内置预览", "rawUrl": f"/api/raw?path={html_mod.escape(real)}"}
        if ext == ".md":
            raw_text = Path(real).read_text(encoding="utf-8", errors="replace")
            return {"ok": True, "kind": "html", "title": name, "badge": "Markdown 内置阅读", "html": preview_markdown_to_html(raw_text)}
        if ext in (".txt", ".json", ".py", ".js", ".mjs", ".ts", ".ps1", ".html", ".htm", ".css", ".xml", ".yaml", ".yml", ".log"):
            raw_text = Path(real).read_text(encoding="utf-8", errors="replace")[:50000]
            return {
                "ok": True,
                "kind": "html",
                "title": name,
                "badge": "文本/代码内置阅读",
                "html": f'<pre class="doc-code"><code>{html_mod.escape(raw_text)}</code></pre>',
            }
        return {
            "ok": True,
            "kind": "unsupported",
            "title": name,
            "badge": "外部软件打开",
            "html": f'<p class="doc-p">该格式（{html_mod.escape(ext or "未知")}）暂不支持在侧边栏直接解析文字，请点击上方<strong>「⚡ 用电脑软件打开」</strong>直接查看！</p>',
        }
    except Exception as e:
        return {"ok": False, "error": f"预览解析失败：{e}"}



# 按文件后缀精准匹配可用的打开方式（绝不把不相关的软件一股脑塞进去）
EXT_APP_MAP = {
    ".docx": ["word", "wps"],
    ".doc":  ["word", "wps"],
    ".rtf":  ["word", "wps", "notepad"],
    ".xlsx": ["excel", "wps"],
    ".xls":  ["excel", "wps"],
    ".csv":  ["excel", "wps", "notepad", "vscode"],
    ".pptx": ["powerpoint", "wps"],
    ".ppt":  ["powerpoint", "wps"],
    ".md":   ["notepad", "vscode", "cursor", "word", "wps"],
    ".txt":  ["notepad", "vscode", "cursor", "notepadpp"],
    ".pdf":  ["edge", "chrome", "wps"],
    ".html": ["edge", "chrome", "vscode", "notepad"],
    ".htm":  ["edge", "chrome", "vscode", "notepad"],
    ".png":  ["edge", "chrome"],
    ".jpg":  ["edge", "chrome"],
    ".jpeg": ["edge", "chrome"],
    ".webp": ["edge", "chrome"],
    ".svg":  ["edge", "chrome", "vscode"],
    ".py":   ["vscode", "cursor", "notepadpp", "notepad"],
    ".js":   ["vscode", "cursor", "notepadpp", "notepad"],
    ".mjs":  ["vscode", "cursor", "notepadpp", "notepad"],
    ".ts":   ["vscode", "cursor", "notepadpp", "notepad"],
    ".css":  ["vscode", "cursor", "notepadpp", "notepad"],
    ".json": ["vscode", "cursor", "notepadpp", "notepad"],
    ".ps1":  ["vscode", "notepadpp", "notepad"],
}


def get_matched_apps_for_ext(ext, all_apps):
    """Return only the installed desktop apps that genuinely support this file extension."""
    ext = (ext or "").lower()
    allowed_ids = EXT_APP_MAP.get(ext, ["notepad", "vscode", "cursor"])
    by_id = {a["id"]: a for a in (all_apps or [])}
    matched = []
    for aid in allowed_ids:
        if aid in by_id:
            matched.append({"id": aid, "name": by_id[aid]["name"]})
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
    def log_message(self, fmt, *args):
        pass

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.end_headers()

    def _send_bytes(self, status, content_type, body_bytes):
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
            req_conv = query.get("conversationId") or os.environ.get("ANTIGRAVITY_CONVERSATION_ID") or ""
            app_data, conv_id = resolve_active_conversation(req_conv)
            cfg = load_user_config()
            apps = detect_installed_apps(cfg.get("customApps"))
            sent_files = collect_user_sent_files(app_data, conv_id, 60)
            sent_lower_set = {f["path"].lower() for f in sent_files}
            session_files = [
                f for f in collect_session_files(app_data, conv_id)
                if f["path"].lower() not in sent_lower_set and "\\.user_uploaded\\" not in f["path"].lower()
            ]
            recent_files = [
                f for f in collect_recent_project_files(cfg.get("watchedDirs"), 80)
                if f["path"].lower() not in sent_lower_set and "\\.user_uploaded\\" not in f["path"].lower()
            ]
            pinned_set = {os.path.normpath(p).lower() for p in cfg.get("pinnedFiles", []) if p}
            archived_set = {os.path.normpath(p).lower() for p in cfg.get("archivedFiles", []) if p}
            pinned_files = [
                info for p in cfg.get("pinnedFiles", [])
                if (info := describe_file(p, action_kind="pinned")) is not None
            ]
            archived_files = [
                info for p in cfg.get("archivedFiles", [])
                if (info := describe_file(p, action_kind="archived")) is not None
            ]
            for flist in (session_files, sent_files, recent_files, pinned_files, archived_files):
                for item in flist:
                    low_p = item["path"].lower()
                    item["isPinned"] = low_p in pinned_set
                    item["isArchived"] = low_p in archived_set
                    item["matchedApps"] = get_matched_apps_for_ext(item.get("ext", ""), apps)
            ipc = read_ipc_state()
            pending_doc = None
            if query.get("client") == "sidecar":
                ipc["lastSidecarSeen"] = time.time()
                if ipc.get("pendingInternalOpen"):
                    # Only consume if fresh (within last 60 seconds)
                    p_item = ipc["pendingInternalOpen"]
                    if time.time() - float(p_item.get("ts") or 0) < 60.0:
                        pending_doc = p_item
                    ipc["pendingInternalOpen"] = None
                write_ipc_state(ipc)
            self._send_json(200, {
                "ok": True,
                "conversationId": conv_id,
                "platform": sys.platform,
                "apps": apps,
                "config": cfg,
                "sessionFiles": session_files,
                "sentFiles": sent_files,
                "recentFiles": recent_files,
                "pinnedFiles": pinned_files,
                "archivedFiles": archived_files,
                "pendingInternalOpen": pending_doc,
            })
            return

        if route == "/api/internal-open":
            target_path = query.get("path") or ""
            info = describe_file(target_path, action_kind="linked")
            if not info:
                self._send_json(200, {"ok": False, "error": "文件不存在"})
                return
            info["matchedApps"] = get_matched_apps_for_ext(info.get("ext", ""), detect_installed_apps())
            native_uri = build_native_open_uri(info)
            ipc_file = dict(info)
            if native_uri and (info.get("ext") or "").lower() in (".docx", ".pptx", ".xlsx"):
                ipc_file["fileUri"] = native_uri
                ipc_file["openUri"] = native_uri
                ipc_file["ext"] = ".md"
            ipc = read_ipc_state()
            ipc["pendingInternalOpen"] = {"file": ipc_file, "ts": time.time()}
            write_ipc_state(ipc)
            sidecar_active = (time.time() - float(ipc.get("lastSidecarSeen") or 0)) < 10.0
            self._send_json(200, {
                "ok": True,
                "sidecarActive": sidecar_active,
                "file": info,
            })
            return

        if route == "/api/poll-open":
            ipc = read_ipc_state()
            ipc["lastSidecarSeen"] = time.time()
            pending_doc = None
            if ipc.get("pendingInternalOpen"):
                p_item = ipc["pendingInternalOpen"]
                if time.time() - float(p_item.get("ts") or 0) < 60.0:
                    pending_doc = p_item
                ipc["pendingInternalOpen"] = None
            write_ipc_state(ipc)
            self._send_json(200, {"ok": True, "pendingInternalOpen": pending_doc})
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

        if route == "/api/pin":
            target_path = (query.get("path") or "").strip()
            op = query.get("op") or "add"
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
                    pins.append(norm)
            cfg["pinnedFiles"] = pins
            save_user_config(cfg)
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

    import threading
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
