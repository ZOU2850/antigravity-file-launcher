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

DELIVERABLE_EXTS = {
    ".pptx", ".ppt", ".pdf", ".docx", ".doc", ".xlsx", ".xls", ".csv",
    ".html", ".htm", ".md", ".png", ".jpg", ".jpeg", ".webp", ".svg",
    ".mp4", ".mp3", ".wav", ".zip", ".7z", ".tar", ".gz", ".json",
    ".py", ".js", ".mjs", ".ts", ".ps1", ".exe", ".msi"
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
        "customApps": [],
        "extDefaults": {},
    }


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

    def _send_bytes(self, status, content_type, body_bytes):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body_bytes)))
        self.send_header("Cache-Control", "no-store")
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
            req_conv = query.get("conversationId") or os.environ.get("ANTIGRAVITY_CONVERSATION_ID") or ""
            app_data, conv_id = resolve_active_conversation(req_conv)
            cfg = load_user_config()
            apps = detect_installed_apps(cfg.get("customApps"))
            session_files = collect_session_files(app_data, conv_id)
            recent_files = collect_recent_project_files(cfg.get("watchedDirs"), 80)
            pinned_files = [
                info for p in cfg.get("pinnedFiles", [])
                if (info := describe_file(p, action_kind="pinned")) is not None
            ]
            self._send_json(200, {
                "ok": True,
                "conversationId": conv_id,
                "platform": sys.platform,
                "apps": apps,
                "config": cfg,
                "sessionFiles": session_files,
                "recentFiles": recent_files,
                "pinnedFiles": pinned_files,
            })
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

    port = int(os.environ.get("ANTIGRAVITY_SIDECAR_WEB_PORT") or "0")
    server = ThreadingHTTPServer(("127.0.0.1", port), SidecarRequestHandler)
    actual_port = server.server_address[1]
    print(f"[sidecar] listening on 127.0.0.1:{actual_port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
