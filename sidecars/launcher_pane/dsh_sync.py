# -*- coding: utf-8 -*-
"""
DSH v1.4.3 对齐核心模块 (dsh_sync.py)
提供 Antigravity File Launcher 与 DSH File Launcher 全面功能对齐的纯标准库后端能力：
1. 线程安全锁与原子 JSON/文本写入
2. 统一 Settings 校验、持久化与兼容迁移（主题、自动刷新、间隔、PDF 渲染、归档目录等）
3. 20+ 全量文件分类与文件夹识别（含 design/database/font/disk/binary/executable/folder）
4. 增强 @引用（引号路径、工作区相对路径、@文件夹、自然语言尾部裁剪）与工具调用提取
5. 增量持久化 sent-index、缺失空壳 (missing)、移动重连 (moved)、删除/遗忘墓碑 (deleted)
6. 日期子目录归档 (YYYY-MM-DD/) + 防重名冲突后缀 + 安全二次确认永久删除 (/api/delete) + 移除记录 (/api/forget)
7. 基于 pdfinfo/pdftoppm (+ 可选 soffice) 的 PDF/Office 逐页 JPEG 渲染与缓存自动清理
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


STATE_LOCK = threading.RLock()

# ---------------------------------------------------------------------------
# 1. 全量文件分类体系（对齐 DSH v1.4.3 lib/util.js）
# ---------------------------------------------------------------------------

CATEGORY_BY_EXTENSION: Dict[str, Tuple[str, str]] = {
    # Word / 文档
    ".doc": ("word", "DOC"),
    ".docx": ("word", "DOCX"),
    ".odt": ("word", "ODT"),
    ".rtf": ("word", "RTF"),
    # PPT / 演示文稿
    ".ppt": ("ppt", "PPT"),
    ".pptx": ("ppt", "PPTX"),
    ".odp": ("ppt", "ODP"),
    ".key": ("ppt", "KEY"),
    # Excel / 表格与数据
    ".xls": ("excel", "XLS"),
    ".xlsx": ("excel", "XLSX"),
    ".xlsm": ("excel", "XLSM"),
    ".csv": ("excel", "CSV"),
    ".tsv": ("excel", "TSV"),
    ".ods": ("excel", "ODS"),
    ".numbers": ("excel", "NUM"),
    # PDF
    ".pdf": ("pdf", "PDF"),
    # Markdown
    ".md": ("markdown", "MD"),
    ".mdx": ("markdown", "MDX"),
    ".markdown": ("markdown", "MD"),
    # 纯文本 / 配置 / 日志
    ".txt": ("text", "TXT"),
    ".log": ("text", "LOG"),
    ".ini": ("text", "INI"),
    ".cfg": ("text", "CFG"),
    ".conf": ("text", "CONF"),
    ".env": ("text", "ENV"),
    ".yaml": ("text", "YAML"),
    ".yml": ("text", "YML"),
    ".toml": ("text", "TOML"),
    ".xml": ("text", "XML"),
    ".properties": ("text", "PROP"),
    # 图片
    ".png": ("image", "PNG"),
    ".jpg": ("image", "JPG"),
    ".jpeg": ("image", "JPG"),
    ".gif": ("image", "GIF"),
    ".webp": ("image", "WEBP"),
    ".svg": ("image", "SVG"),
    ".bmp": ("image", "BMP"),
    ".ico": ("image", "ICO"),
    ".tif": ("image", "TIF"),
    ".tiff": ("image", "TIF"),
    ".avif": ("image", "AVIF"),
    # Web 前端
    ".html": ("web", "HTML"),
    ".htm": ("web", "HTM"),
    ".css": ("web", "CSS"),
    ".scss": ("web", "SCSS"),
    ".sass": ("web", "SASS"),
    ".less": ("web", "LESS"),
    ".vue": ("web", "VUE"),
    ".svelte": ("web", "SVELTE"),
    ".astro": ("web", "ASTRO"),
    # 代码 / 脚本 / 结构化数据
    ".py": ("code", "PY"),
    ".js": ("code", "JS"),
    ".jsx": ("code", "JSX"),
    ".mjs": ("code", "MJS"),
    ".cjs": ("code", "CJS"),
    ".ts": ("code", "TS"),
    ".tsx": ("code", "TSX"),
    ".json": ("code", "JSON"),
    ".jsonc": ("code", "JSONC"),
    ".jsonl": ("code", "JSONL"),
    ".sh": ("code", "SH"),
    ".bash": ("code", "SH"),
    ".zsh": ("code", "ZSH"),
    ".ps1": ("code", "PS1"),
    ".bat": ("code", "BAT"),
    ".cmd": ("code", "CMD"),
    ".go": ("code", "GO"),
    ".rs": ("code", "RS"),
    ".java": ("code", "JAVA"),
    ".kt": ("code", "KT"),
    ".kts": ("code", "KTS"),
    ".c": ("code", "C"),
    ".h": ("code", "H"),
    ".cc": ("code", "CPP"),
    ".cpp": ("code", "CPP"),
    ".cxx": ("code", "CPP"),
    ".hpp": ("code", "HPP"),
    ".cs": ("code", "CS"),
    ".rb": ("code", "RB"),
    ".php": ("code", "PHP"),
    ".swift": ("code", "SWIFT"),
    ".dart": ("code", "DART"),
    ".lua": ("code", "LUA"),
    ".r": ("code", "R"),
    ".sql": ("code", "SQL"),
    ".graphql": ("code", "GQL"),
    ".gql": ("code", "GQL"),
    ".proto": ("code", "PROTO"),
    # 音视频媒体
    ".mp3": ("media", "MP3"),
    ".wav": ("media", "WAV"),
    ".flac": ("media", "FLAC"),
    ".aac": ("media", "AAC"),
    ".ogg": ("media", "OGG"),
    ".m4a": ("media", "M4A"),
    ".mp4": ("media", "MP4"),
    ".mov": ("media", "MOV"),
    ".avi": ("media", "AVI"),
    ".mkv": ("media", "MKV"),
    ".webm": ("media", "WEBM"),
    # 压缩包
    ".zip": ("archive", "ZIP"),
    ".tar": ("archive", "TAR"),
    ".gz": ("archive", "GZ"),
    ".tgz": ("archive", "TGZ"),
    ".bz2": ("archive", "BZ2"),
    ".xz": ("archive", "XZ"),
    ".7z": ("archive", "7Z"),
    ".rar": ("archive", "RAR"),
    ".zst": ("archive", "ZST"),
    # 设计源文件
    ".fig": ("design", "FIG"),
    ".sketch": ("design", "SKETCH"),
    ".xd": ("design", "XD"),
    ".psd": ("design", "PSD"),
    ".ai": ("design", "AI"),
    ".eps": ("design", "EPS"),
    # 可执行与安装包
    ".exe": ("executable", "EXE"),
    ".msi": ("executable", "MSI"),
    ".app": ("executable", "APP"),
    ".dmg": ("executable", "DMG"),
    ".pkg": ("executable", "PKG"),
    ".deb": ("executable", "DEB"),
    ".rpm": ("executable", "RPM"),
    ".appimage": ("executable", "APPIMG"),
    # 数据库
    ".db": ("database", "DB"),
    ".sqlite": ("database", "SQLITE"),
    ".sqlite3": ("database", "SQLITE"),
    ".mdb": ("database", "MDB"),
    ".accdb": ("database", "ACCDB"),
    ".parquet": ("database", "PARQ"),
    # 字体
    ".ttf": ("font", "TTF"),
    ".otf": ("font", "OTF"),
    ".woff": ("font", "WOFF"),
    ".woff2": ("font", "WOFF2"),
    ".eot": ("font", "EOT"),
    # 磁盘镜像
    ".iso": ("disk", "ISO"),
    ".img": ("disk", "IMG"),
    ".vhd": ("disk", "VHD"),
    ".vhdx": ("disk", "VHDX"),
    # 二进制与编译产物
    ".bin": ("binary", "BIN"),
    ".dll": ("binary", "DLL"),
    ".so": ("binary", "SO"),
    ".dylib": ("binary", "DYLIB"),
    ".wasm": ("binary", "WASM"),
    ".o": ("binary", "OBJ"),
    ".a": ("binary", "LIB"),
    ".lib": ("binary", "LIB"),
    ".class": ("binary", "CLASS"),
    ".pyc": ("binary", "PYC"),
}

OFFICE_CONVERTIBLE_EXTS = {".docx", ".doc", ".pptx", ".ppt", ".xlsx", ".xls", ".odt", ".odp", ".ods", ".rtf"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp", ".ico", ".tif", ".tiff", ".avif"}
TEXT_PREVIEW_EXTS = {
    ext
    for ext, (cat, _) in CATEGORY_BY_EXTENSION.items()
    if cat in {"markdown", "text", "web", "code"}
}
DELIVERABLE_DOC_EXTS = {
    ".docx", ".doc", ".odt", ".rtf",
    ".pptx", ".ppt", ".odp",
    ".xlsx", ".xls", ".xlsm", ".csv", ".tsv", ".ods",
    ".pdf", ".md", ".mdx", ".markdown", ".txt", ".html", ".htm",
}
KNOWN_MENTION_EXTS = set(CATEGORY_BY_EXTENSION.keys()) | {".dockerfile", ".makefile", ".lock"}


def classify_extension_full(ext: str, is_dir: bool = False) -> Tuple[str, str]:
    """返回 (category, badge)。支持文件夹及 20+ 细分文件类型。"""
    if is_dir:
        return "folder", "DIR"
    ext_l = (ext or "").strip().lower()
    if ext_l and not ext_l.startswith("."):
        ext_l = "." + ext_l
    if ext_l in CATEGORY_BY_EXTENSION:
        return CATEGORY_BY_EXTENSION[ext_l]
    if ext_l and len(ext_l) > 1:
        badge = re.sub(r"[^A-Za-z0-9]", "", ext_l[1:]).upper()[:6] or "FILE"
        return "other", badge
    return "other", "FILE"


# ---------------------------------------------------------------------------
# 2. 路径归一化与原子读写
# ---------------------------------------------------------------------------

def norm_path_str(raw: str) -> str:
    """规范化本地文件/目录路径字符串，去除引号及多余分隔符。"""
    if not raw or not isinstance(raw, str):
        return ""
    s = raw.strip()
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        s = s[1:-1].strip()
    if not s:
        return ""
    if s.startswith("~"):
        s = os.path.expanduser(s)
    # 兼容 Git Bash / MSYS 风格 /d/foo -> D:\foo
    m_msys = re.match(r"^/([a-zA-Z])/(.+)$", s)
    if os.name == "nt" and m_msys:
        s = f"{m_msys.group(1).upper()}:/{m_msys.group(2)}"
    return os.path.normpath(s)


def path_key(raw: str) -> str:
    """用于跨平台比较的路径键（Windows 下不区分大小写，消除尾斜杠）。"""
    p = norm_path_str(raw)
    if not p:
        return ""
    # 保留盘符根路径如 D:\
    if len(p) > 3 and p.endswith(("\\", "/")):
        p = p.rstrip("\\/")
    return p.lower() if os.name == "nt" else p


def atomic_write_text(target: Path, content: str) -> None:
    """使用同目录临时文件 + flush/fsync + os.replace 原子写入 UTF-8 文本。"""
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".tmp_", suffix=".part", dir=str(target.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fp:
            fp.write(content)
            fp.flush()
            try:
                os.fsync(fp.fileno())
            except OSError:
                pass
        os.replace(tmp_name, str(target))
    except Exception:
        try:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
        except OSError:
            pass
        raise


def atomic_write_json(target: Path, payload: Any) -> None:
    """在 STATE_LOCK 保护下原子写入 JSON。"""
    raw = json.dumps(payload, ensure_ascii=False, indent=2)
    with STATE_LOCK:
        atomic_write_text(target, raw)


def read_json_safe(target: Path, default: Any = None) -> Any:
    """安全读取 JSON 文件，若不存在或损坏返回 default 副本。"""
    try:
        p = Path(target)
        if not p.is_file():
            return json.loads(json.dumps(default)) if default is not None else None
        with STATE_LOCK:
            data = json.loads(p.read_text(encoding="utf-8"))
        return data
    except Exception:
        return json.loads(json.dumps(default)) if default is not None else None


def get_store_paths(base_dir: Path) -> Dict[str, Path]:
    """统一管理 Sidecar 插件数据目录与各持久化状态文件路径。"""
    base = Path(base_dir)
    base.mkdir(parents=True, exist_ok=True)
    return {
        "baseDir": base,
        "config": base / "file_launcher_config.json",
        "ipc": base / "file_launcher_ipc.json",
        "archiveIndex": base / "file_launcher_archive.json",
        "deletedIndex": base / "file_launcher_deleted.json",
        "sentIndex": base / "file_launcher_sent_index.json",
        "rendersDir": base / "fl_renders",
        "defaultArchiveDir": base / "Archived_Docs",
        "pinnedManifestDir": base / "Pinned_Protected_Files",
    }


# ---------------------------------------------------------------------------
# 3. 统一 Settings 体系（兼容 Antigravity 原配置 + 对齐 DSH v1.4.3）
# ---------------------------------------------------------------------------

VALID_THEMES = {"host", "light", "dark", "system"}
VALID_SCOPES = {"auto", "current", "all", "session", "sent", "workspace", "pinned"}
VALID_CLICK_ACTIONS = {"sidecar", "preview", "system"}
VALID_LANGUAGES = {"zh", "en"}


def _clamp_int(val: Any, minimum: int, maximum: int, fallback: int) -> int:
    try:
        n = int(float(val))
    except (TypeError, ValueError):
        return fallback
    return max(minimum, min(maximum, n))


def default_settings() -> Dict[str, Any]:
    return {
        # Antigravity 原有字段（全部向后兼容）
        "watchedDirs": [],
        "pinnedFiles": [],
        "archivedFiles": [],
        "customApps": [],
        "extDefaults": {},
        # DSH 对齐扩展字段
        "appearanceTheme": "host",
        "autoRefresh": True,
        "refreshSeconds": 60,
        "defaultScope": "auto",
        "collapseGroups": True,
        "pdfMaxPages": 20,
        "pdfDpi": 110,
        "maxRows": 800,
        "archiveDir": "",
        "defaultClickAction": "sidecar",
        "language": "zh",
    }


def _dedupe_paths(items: Iterable[Any]) -> List[str]:
    out: List[str] = []
    seen = set()
    for item in items or []:
        if not isinstance(item, str):
            continue
        np = norm_path_str(item)
        if not np:
            continue
        k = path_key(np)
        if k not in seen:
            seen.add(k)
            out.append(np)
    return out


def normalize_settings(raw: Any) -> Dict[str, Any]:
    base = default_settings()
    if not isinstance(raw, dict):
        return base

    out = dict(base)
    out["watchedDirs"] = _dedupe_paths(raw.get("watchedDirs") or [])
    out["pinnedFiles"] = _dedupe_paths(raw.get("pinnedFiles") or [])
    out["archivedFiles"] = _dedupe_paths(raw.get("archivedFiles") or [])

    custom_apps = []
    seen_app_ids = set()
    for app in raw.get("customApps") or []:
        if not isinstance(app, dict):
            continue
        name = str(app.get("name") or "").strip()
        exe = norm_path_str(str(app.get("exe") or ""))
        if not name or not exe:
            continue
        aid = str(app.get("id") or "").strip() or re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "custom-app"
        if aid in seen_app_ids:
            continue
        seen_app_ids.add(aid)
        custom_apps.append({
            "id": aid,
            "name": name,
            "exe": exe,
            "icon": str(app.get("icon") or "🔧"),
        })
    out["customApps"] = custom_apps

    ext_defaults: Dict[str, str] = {}
    if isinstance(raw.get("extDefaults"), dict):
        for k, v in raw["extDefaults"].items():
            if isinstance(k, str) and isinstance(v, str) and k.strip() and v.strip():
                ek = k.strip().lower()
                if not ek.startswith("."):
                    ek = "." + ek
                ext_defaults[ek] = v.strip()
    out["extDefaults"] = ext_defaults

    theme = str(raw.get("appearanceTheme") or "host").strip().lower()
    out["appearanceTheme"] = theme if theme in VALID_THEMES else "host"

    if isinstance(raw.get("autoRefresh"), bool):
        out["autoRefresh"] = raw["autoRefresh"]
    elif isinstance(raw.get("autoRefresh"), str):
        out["autoRefresh"] = raw["autoRefresh"].strip().lower() not in {"0", "false", "no", "off"}

    out["refreshSeconds"] = _clamp_int(raw.get("refreshSeconds"), 5, 300, 60)

    scope = str(raw.get("defaultScope") or "auto").strip().lower()
    out["defaultScope"] = scope if scope in VALID_SCOPES else "auto"

    if isinstance(raw.get("collapseGroups"), bool):
        out["collapseGroups"] = raw["collapseGroups"]
    elif isinstance(raw.get("collapseGroups"), str):
        out["collapseGroups"] = raw["collapseGroups"].strip().lower() not in {"0", "false", "no", "off"}

    out["pdfMaxPages"] = _clamp_int(raw.get("pdfMaxPages"), 1, 40, 20)
    out["pdfDpi"] = _clamp_int(raw.get("pdfDpi"), 80, 160, 110)
    out["maxRows"] = _clamp_int(raw.get("maxRows"), 100, 2000, 800)

    arch_dir = str(raw.get("archiveDir") or "").strip()
    out["archiveDir"] = norm_path_str(arch_dir) if arch_dir else ""

    click_act = str(raw.get("defaultClickAction") or "sidecar").strip().lower()
    out["defaultClickAction"] = click_act if click_act in VALID_CLICK_ACTIONS else "sidecar"

    lang = str(raw.get("language") or "zh").strip().lower()
    out["language"] = lang if lang in VALID_LANGUAGES else "zh"

    return out


def load_settings(config_path: Path) -> Dict[str, Any]:
    with STATE_LOCK:
        raw = read_json_safe(config_path, {})
        return normalize_settings(raw)


def save_settings(config_path: Path, new_cfg: Dict[str, Any]) -> Dict[str, Any]:
    with STATE_LOCK:
        normalized = normalize_settings(new_cfg)
        atomic_write_json(config_path, normalized)
        return normalized


def update_settings_patch(config_path: Path, patch: Dict[str, Any]) -> Dict[str, Any]:
    with STATE_LOCK:
        current = load_settings(config_path)
        if isinstance(patch, dict):
            for k, v in patch.items():
                if k in current or k in default_settings():
                    current[k] = v
        return save_settings(config_path, current)


def resolve_archive_root(settings: Dict[str, Any], default_archive_dir: Path) -> Path:
    custom = (settings.get("archiveDir") or "").strip()
    if custom:
        return Path(norm_path_str(custom))
    return Path(default_archive_dir)


# ---------------------------------------------------------------------------
# 4. 墓碑索引 (deleted/forgotten) 与 归档索引 (archive)
# ---------------------------------------------------------------------------

def load_tombstones(deleted_path: Path) -> Dict[str, Dict[str, Any]]:
    raw = read_json_safe(deleted_path, {})
    if not isinstance(raw, dict):
        return {}
    out: Dict[str, Dict[str, Any]] = {}
    for k, v in raw.items():
        if isinstance(k, str) and isinstance(v, dict):
            out[k] = v
    return out


def save_tombstones(deleted_path: Path, records: Dict[str, Dict[str, Any]]) -> None:
    atomic_write_json(deleted_path, records)


def record_tombstones(deleted_path: Path, paths: Iterable[str], reason: str = "deleted") -> List[str]:
    now_ms = int(time.time() * 1000)
    added: List[str] = []
    with STATE_LOCK:
        records = load_tombstones(deleted_path)
        for p in paths or []:
            np = norm_path_str(str(p))
            k = path_key(np)
            if not k:
                continue
            records[k] = {
                "path": np,
                "reason": reason,
                "ts": now_ms,
            }
            added.append(np)
        save_tombstones(deleted_path, records)
    return added


def clear_tombstones(deleted_path: Path, paths: Iterable[str]) -> bool:
    with STATE_LOCK:
        records = load_tombstones(deleted_path)
        changed = False
        for p in paths or []:
            k = path_key(str(p))
            if k and k in records:
                del records[k]
                changed = True
        if changed:
            save_tombstones(deleted_path, records)
        return changed


def should_suppress_by_tombstone(
    raw_path: str,
    tombstones: Dict[str, Dict[str, Any]],
    *,
    is_explicit_current_event: bool = False,
    clear_paths_collector: Optional[List[str]] = None,
) -> bool:
    """
    判断某个路径是否应被墓碑屏蔽：
    - 若磁盘文件已真实重建（mtime 晚于墓碑时间）或是当前显式新动作（如重新发送/AI 新建），
      自动解除墓碑（放入 clear_paths_collector）。
    - 若文件不存在或时间戳早于墓碑，保持屏蔽，防止已删除/已移除的 ghost 再次回流。
    """
    k = path_key(raw_path)
    if not k or k not in tombstones:
        return False
    entry = tombstones[k]
    tomb_ts = float(entry.get("ts") or 0)
    exists = os.path.exists(raw_path)
    if is_explicit_current_event:
        if clear_paths_collector is not None:
            clear_paths_collector.append(raw_path)
        return False
    if exists:
        try:
            mtime_ms = os.path.getmtime(raw_path) * 1000.0
            if mtime_ms > tomb_ts + 500:
                if clear_paths_collector is not None:
                    clear_paths_collector.append(raw_path)
                return False
        except OSError:
            pass
    return True


def load_archive_records(archive_index_path: Path) -> Dict[str, Dict[str, Any]]:
    raw = read_json_safe(archive_index_path, {})
    if not isinstance(raw, dict):
        return {}
    out: Dict[str, Dict[str, Any]] = {}
    for k, v in raw.items():
        if isinstance(k, str) and isinstance(v, dict):
            out[k] = v
    return out


def unique_target_path(target_dir: Path, filename: str) -> Path:
    """若同名文件已存在，自动追加 (2), (3)... 后缀，绝不覆盖旧归档。"""
    target_dir = Path(target_dir)
    base_name = Path(filename).name
    stem = Path(base_name).stem
    suffix = Path(base_name).suffix
    candidate = target_dir / base_name
    idx = 2
    while candidate.exists():
        candidate = target_dir / f"{stem} ({idx}){suffix}"
        idx += 1
        if idx > 9999:
            candidate = target_dir / f"{stem}_{int(time.time())}{suffix}"
            break
    return candidate


def archive_files_dsh(
    paths: Iterable[str],
    config_path: Path,
    archive_index_path: Path,
    default_archive_dir: Path,
) -> Dict[str, Any]:
    """
    对齐 DSH archive()：
    将文件复制到 <archiveRoot>/YYYY-MM-DD/<name> (防重名覆盖)，
    记录详细映射至 archive_index 并同步更新 settings.archivedFiles。
    """
    with STATE_LOCK:
        settings = load_settings(config_path)
        archive_root = resolve_archive_root(settings, default_archive_dir)
        date_dir = archive_root / datetime.now().strftime("%Y-%m-%d")
        date_dir.mkdir(parents=True, exist_ok=True)

        records = load_archive_records(archive_index_path)
        archived_list = list(settings.get("archivedFiles") or [])
        archived_keys = {path_key(x) for x in archived_list}

        copied: List[Dict[str, str]] = []
        skipped: List[Dict[str, str]] = []
        now_ms = int(time.time() * 1000)

        for raw in paths or []:
            np = norm_path_str(str(raw))
            k = path_key(np)
            if not np or not k:
                continue
            if not os.path.isfile(np):
                skipped.append({"path": np, "reason": "仅支持归档存在的常规文件"})
                continue
            dst = unique_target_path(date_dir, os.path.basename(np))
            try:
                shutil.copy2(np, str(dst))
                size = os.path.getsize(str(dst))
            except Exception as exc:
                skipped.append({"path": np, "reason": str(exc)})
                continue
            dst_str = norm_path_str(str(dst))
            records[k] = {
                "sourcePath": np,
                "archivePath": dst_str,
                "archivedAt": now_ms,
                "size": size,
            }
            if k not in archived_keys:
                archived_list.append(np)
                archived_keys.add(k)
            copied.append({"sourcePath": np, "archivePath": dst_str})

        settings["archivedFiles"] = archived_list
        save_settings(config_path, settings)
        atomic_write_json(archive_index_path, records)

        return {
            "ok": True,
            "archivedDir": str(date_dir),
            "copied": copied,
            "skipped": skipped,
            "config": settings,
        }


def unarchive_files_dsh(
    paths: Iterable[str],
    config_path: Path,
    archive_index_path: Path,
) -> Dict[str, Any]:
    """取消归档标记（不删除磁盘已复制的归档副本，对齐 DSH）。"""
    with STATE_LOCK:
        settings = load_settings(config_path)
        records = load_archive_records(archive_index_path)
        remove_keys = {path_key(str(p)) for p in (paths or []) if path_key(str(p))}

        settings["archivedFiles"] = [
            p for p in (settings.get("archivedFiles") or [])
            if path_key(p) not in remove_keys
        ]
        for rk in remove_keys:
            records.pop(rk, None)

        save_settings(config_path, settings)
        atomic_write_json(archive_index_path, records)
        return {"ok": True, "removedKeys": len(remove_keys), "config": settings}


# ---------------------------------------------------------------------------
# 5. sent-index 增量持久化 + 移动重连 (moved) + @引用 / 工具参数提取
# ---------------------------------------------------------------------------

def load_sent_index(sent_index_path: Path) -> Dict[str, Any]:
    raw = read_json_safe(sent_index_path, None)
    if not isinstance(raw, dict) or raw.get("version") != 1 or not isinstance(raw.get("conversations"), dict):
        return {"version": 1, "conversations": {}}
    return raw


def save_sent_index(sent_index_path: Path, index_data: Dict[str, Any]) -> None:
    atomic_write_json(sent_index_path, index_data)


def remove_paths_from_sent_index(sent_index_path: Path, paths: Iterable[str]) -> bool:
    remove_keys = {path_key(str(p)) for p in (paths or []) if path_key(str(p))}
    if not remove_keys:
        return False
    with STATE_LOCK:
        idx = load_sent_index(sent_index_path)
        convs = idx.get("conversations") or {}
        changed = False
        for cid, entry in convs.items():
            if not isinstance(entry, dict) or not isinstance(entry.get("items"), list):
                continue
            orig = entry["items"]
            filtered = [it for it in orig if path_key(str(it.get("path") or "")) not in remove_keys]
            if len(filtered) != len(orig):
                entry["items"] = filtered
                changed = True
        if changed:
            save_sent_index(sent_index_path, idx)
        return changed


def _looks_like_path_token(s: str) -> bool:
    if not s or len(s) < 2:
        return False
    # 排除邮箱与纯用户名：必须包含盘符、路径斜杠、~ 或已知后缀
    if re.match(r"^[A-Za-z]:[\\/]", s):
        return True
    if s.startswith(("\\\\", "/", "~/")):
        return True
    if "/" in s or "\\" in s:
        return True
    _, ext = os.path.splitext(s)
    if ext and ext.lower() in KNOWN_MENTION_EXTS:
        return True
    return False


def _trim_and_resolve_candidate(
    raw_token: str,
    workspace_roots: Optional[List[str]] = None,
    allow_dirs: bool = True,
) -> Optional[Tuple[str, bool, bool]]:
    """
    对齐 DSH pathsFromMentionText 的尾部自然语言裁剪：
    1. 尝试直接匹配或拼接 workspace_roots 匹配磁盘文件/目录；
    2. 逐词/逐标点剥离尾部文字，再次匹配磁盘文件/目录；
    3. 若磁盘均不存在，如果格式明显像带扩展名或绝对路径的文件，返回 (best_norm, is_dir, exists=False) 作为潜在 missing 追踪。
    """
    token = (raw_token or "").strip().strip("`")
    if not token:
        return None
    # 剔除 URL
    if re.match(r"^[a-zA-Z]+://", token):
        return None

    roots = [norm_path_str(r) for r in (workspace_roots or []) if r]

    def probe(cand: str) -> Optional[Tuple[str, bool, bool]]:
        c = cand.strip().rstrip(".,;:!?，。；：！？)]}）】》」』'\"")
        if not c:
            return None
        is_abs = bool(
            re.match(r"^[A-Za-z]:[\\/]", c)
            or c.startswith(("\\\\", "/", "~/"))
        )
        if is_abs:
            np = norm_path_str(c)
            if os.path.isfile(np):
                return (np, False, True)
            if allow_dirs and os.path.isdir(np):
                return (np, True, True)
            return None
        for r in roots:
            joined = norm_path_str(os.path.join(r, c))
            if os.path.isfile(joined):
                return (joined, False, True)
            if allow_dirs and os.path.isdir(joined):
                return (joined, True, True)
        return None

    # 1. 原串尝试 + 从尾部按空白/中文/中文标点边界回溯（最多试 12 段）
    trial = token
    for _ in range(12):
        hit = probe(trial)
        if hit:
            return hit
        # 优先剥离最后一个空白及其后自然语言，或剥离全角标点/CJK 后缀
        m_space = re.match(r"^(.+?)\s+\S+$", trial)
        if m_space:
            trial = m_space.group(1)
            continue
        m_cjk = re.match(r"^([A-Za-z0-9_./\\:~-]+?)[\u4e00-\u9fff，。；：！？、（）【】《》「」『』,;!?()\[\]{}].*$", trial)
        if m_cjk and m_cjk.group(1) != trial:
            trial = m_cjk.group(1)
            continue
        break

    # 2. 若未在磁盘找到，判断是否值得作为 missing 空壳保留
    clean = token.split()[0].strip(".,;:!?，。；：！？)]}）】》」』'\"")
    if not clean or not _looks_like_path_token(clean):
        return None
    if re.match(r"^[A-Za-z]:[\\/]", clean) or clean.startswith(("\\\\", "/", "~/")):
        return (norm_path_str(clean), False, False)
    if roots and ("/" in clean or "\\" in clean or os.path.splitext(clean)[1].lower() in KNOWN_MENTION_EXTS):
        return (norm_path_str(os.path.join(roots[0], clean)), False, False)
    return None


def extract_mentions_from_text(
    text: str,
    workspace_roots: Optional[List[str]] = None,
    allow_dirs: bool = True,
) -> List[Dict[str, Any]]:
    """
    从用户输入文本中解析全部 @引用 路径（支持引号路径、相对路径、绝对路径、@文件夹、防误判）。
    返回: [{"path": str, "isDir": bool, "exists": bool}, ...]
    """
    if not text or "@" not in text:
        return []

    found: Dict[str, Dict[str, Any]] = {}

    def record(res: Optional[Tuple[str, bool, bool]]):
        if not res:
            return
        p, is_dir, exists = res
        k = path_key(p)
        if not k:
            return
        if k not in found or (exists and not found[k]["exists"]):
            found[k] = {"path": p, "isDir": is_dir, "exists": exists}

    # 1. @"..." / @'...' / @`...` 带空格引用
    for m in re.finditer(r"""(?:^|(?<=[\s(\[{"'：:，,]))@(["'`])([^"'`\r\n]{2,360})\1""", text):
        cand = m.group(2).strip()
        if not _looks_like_path_token(cand) and not os.path.exists(norm_path_str(cand)):
            # 试工作区相对路径
            if workspace_roots:
                res = _trim_and_resolve_candidate(cand, workspace_roots, allow_dirs=allow_dirs)
                record(res)
                continue
        if re.match(r"^[A-Za-z]:[\\/]", cand) or cand.startswith(("\\\\", "/", "~/")):
            np = norm_path_str(cand)
            if os.path.isfile(np):
                record((np, False, True))
            elif allow_dirs and os.path.isdir(np):
                record((np, True, True))
            else:
                record((np, False, False))
        else:
            record(_trim_and_resolve_candidate(cand, workspace_roots, allow_dirs=allow_dirs))

    # 2. 未加引号的 @path：对每个合法起始 @ 单独截取后续一段文本向回裁剪（防止同行多个 @ 相互吞并）
    for m in re.finditer(r"""(?:^|(?<=[\s(\[{"'：:，,]))@(?=([^\s"'`<>\r\n]))""", text):
        tail = text[m.end():].splitlines()[0][:240]
        if not tail or tail.startswith(('"', "'", "`")):
            continue
        # 若后续文本里紧邻着空白+@（另一个引用），截取到那里之前与整段双试，确保不会遗漏也不能跨句吞掉后续引用
        next_at = re.search(r"\s@", tail)
        seg = tail[:next_at.start()] if next_at else tail
        record(_trim_and_resolve_candidate(seg, workspace_roots, allow_dirs=allow_dirs))

    return list(found.values())


def extract_paths_from_apply_patch(patch_text: str) -> List[Tuple[str, str]]:
    """从 Codex / DSH apply_patch 补丁文本中提取文件操作与来源类型。"""
    results: List[Tuple[str, str]] = []
    if not patch_text or not isinstance(patch_text, str):
        return results
    for line in patch_text.splitlines():
        s = line.strip()
        if s.startswith("*** Add File:"):
            p = s[len("*** Add File:"):].strip()
            if p:
                results.append((p, "created"))
        elif s.startswith("*** Update File:"):
            p = s[len("*** Update File:"):].strip()
            if p:
                results.append((p, "edited"))
        elif s.startswith("*** Move to:"):
            p = s[len("*** Move to:"):].strip()
            if p:
                results.append((p, "edited"))
    return results


def extract_paths_from_tool_call(
    tool_name: str,
    args_obj: Any,
    workspace_roots: Optional[List[str]] = None,
) -> List[Tuple[str, str]]:
    """
    统一提取 Antigravity (write_file/edit_file/read_file/write_to_file/replace_file_content/view_file)
    以及 DSH / Codex (apply_patch) 工具调用中的文件路径与规范 source 类别。
    返回 [(norm_path, source_kind), ...], source_kind ∈ {"created", "edited", "read"}
    """
    if not isinstance(args_obj, dict):
        return []
    tname = (tool_name or "").strip().lower()

    if tname == "apply_patch":
        patch = args_obj.get("patch") or args_obj.get("input") or args_obj.get("raw") or ""
        out = []
        for raw_p, sk in extract_paths_from_apply_patch(str(patch)):
            res = _trim_and_resolve_candidate(raw_p, workspace_roots, allow_dirs=False)
            if res:
                out.append((res[0], sk))
            elif os.path.isabs(raw_p):
                out.append((norm_path_str(raw_p), sk))
        return out

    if tname in {"write_file", "write_to_file", "create_file"}:
        kind = "created"
    elif tname in {"edit_file", "replace_file_content", "multi_replace_file_content", "update_file"}:
        kind = "edited"
    elif tname in {"read_file", "view_file", "view_file_outline", "view_code_item"}:
        kind = "read"
    else:
        return []

    raw_candidates: List[str] = []
    for key in ("Path", "path", "TargetFile", "target_file", "AbsolutePath", "absolute_path", "file_path", "targetPath"):
        val = args_obj.get(key)
        if isinstance(val, str) and val.strip():
            raw_candidates.append(val.strip())
    for key in ("Paths", "paths", "files", "TargetFiles"):
        val = args_obj.get(key)
        if isinstance(val, list):
            for item in val:
                if isinstance(item, str) and item.strip():
                    raw_candidates.append(item.strip())

    out_paths: List[Tuple[str, str]] = []
    seen = set()
    for rc in raw_candidates:
        if os.path.isabs(rc) or re.match(r"^[A-Za-z]:[\\/]", rc):
            np = norm_path_str(rc)
        elif workspace_roots:
            res = _trim_and_resolve_candidate(rc, workspace_roots, allow_dirs=False)
            np = res[0] if res else norm_path_str(os.path.join(workspace_roots[0], rc))
        else:
            np = norm_path_str(rc)
        k = path_key(np)
        if k and k not in seen:
            seen.add(k)
            out_paths.append((np, kind))
    return out_paths


def detect_moved_target(
    old_path: str,
    expected_size: Optional[int],
    is_dir: bool,
    search_dirs: Iterable[str],
    exclude_paths: Optional[set] = None,
) -> Optional[str]:
    """
    当历史上记录的文件路径已不存在时，在关联项目/会话目录中按文件名（与文件大小/目录属性）查找移动后的新路径。
    若找到唯一高置信度匹配则返回新路径，否则返回 None。
    """
    base_name = os.path.basename(old_path)
    if not base_name:
        return None
    base_lower = base_name.lower() if os.name == "nt" else base_name
    exclude = exclude_paths or set()

    matches: List[str] = []
    skip_names = {"node_modules", ".git", "__pycache__", ".venv", "venv", "dist", "build"}
    for root_dir in search_dirs or []:
        if not root_dir or not os.path.isdir(root_dir):
            continue
        root_norm = norm_path_str(root_dir)
        # 限制扫描深度防遍历整个磁盘
        base_depth = root_norm.count(os.sep)
        for cur_root, dirs, files in os.walk(root_norm):
            dirs[:] = [d for d in dirs if d not in skip_names and not d.startswith(".tmp")]
            if cur_root.count(os.sep) - base_depth > 4:
                dirs[:] = []
                continue
            if is_dir:
                for d in dirs:
                    dn = d.lower() if os.name == "nt" else d
                    if dn == base_lower:
                        cand = norm_path_str(os.path.join(cur_root, d))
                        if path_key(cand) not in exclude and path_key(cand) != path_key(old_path):
                            matches.append(cand)
            else:
                for f in files:
                    fn = f.lower() if os.name == "nt" else f
                    if fn == base_lower:
                        cand = norm_path_str(os.path.join(cur_root, f))
                        if path_key(cand) not in exclude and path_key(cand) != path_key(old_path):
                            if expected_size is not None and expected_size > 0:
                                try:
                                    sz = os.path.getsize(cand)
                                    # 大小完全相等，或仅细微偏差
                                    if sz == expected_size or abs(sz - expected_size) <= max(64, int(expected_size * 0.05)):
                                        matches.append(cand)
                                except OSError:
                                    pass
                            else:
                                matches.append(cand)
            if len(matches) >= 3:
                break

    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        # 多同名候选时，取最近修改的一份，前提是 expected_size 完全匹配或仅有一份最近
        try:
            matches.sort(key=lambda p: os.path.getmtime(p), reverse=True)
            return matches[0]
        except OSError:
            return matches[0]
    return None


# ---------------------------------------------------------------------------
# 6. 安全永久删除 (/api/delete) & 移除记录 (/api/forget)
# ---------------------------------------------------------------------------

def forget_files_dsh(
    paths: Iterable[str],
    config_path: Path,
    archive_index_path: Path,
    deleted_index_path: Path,
    sent_index_path: Path,
    pinned_manifest_sync_cb=None,
) -> Dict[str, Any]:
    """
    移除不存在记录 / 遗忘指定路径（不删磁盘文件），清理收藏/归档/sent索引并写入墓碑以防止重新扫回 ghost。
    """
    target_paths = [norm_path_str(str(p)) for p in (paths or []) if norm_path_str(str(p))]
    if not target_paths:
        return {"ok": False, "error": "缺少目标路径"}

    remove_keys = {path_key(p) for p in target_paths}
    with STATE_LOCK:
        settings = load_settings(config_path)
        settings["pinnedFiles"] = [p for p in (settings.get("pinnedFiles") or []) if path_key(p) not in remove_keys]
        settings["archivedFiles"] = [p for p in (settings.get("archivedFiles") or []) if path_key(p) not in remove_keys]
        save_settings(config_path, settings)

        records = load_archive_records(archive_index_path)
        arch_changed = False
        for rk in remove_keys:
            if rk in records:
                del records[rk]
                arch_changed = True
        if arch_changed:
            atomic_write_json(archive_index_path, records)

        remove_paths_from_sent_index(sent_index_path, target_paths)
        record_tombstones(deleted_index_path, target_paths, reason="forgotten")

    if pinned_manifest_sync_cb:
        try:
            pinned_manifest_sync_cb(settings.get("pinnedFiles") or [])
        except Exception:
            pass

    return {"ok": True, "forgotten": target_paths, "config": settings}


def delete_files_permanently_dsh(
    paths: Iterable[str],
    confirm: bool,
    config_path: Path,
    archive_index_path: Path,
    deleted_index_path: Path,
    sent_index_path: Path,
    preview_roots: Optional[Iterable[Path]] = None,
    renders_dir: Optional[Path] = None,
    pinned_manifest_sync_cb=None,
) -> Dict[str, Any]:
    """
    对齐 DSH POST /api/file-launcher.delete：
    - 必须 confirm is True，否则拒绝；
    - 仅支持删除真实存在的常规文件，严禁删除目录（防误删工作区）；
    - 删除源文件、关联只读预览镜像，清理 pin/archive/sent-index，记录 tombstone。
    """
    if confirm is not True:
        return {"ok": False, "error": "永久删除需要 confirm=true 明确确认"}

    target_paths = [norm_path_str(str(p)) for p in (paths or []) if norm_path_str(str(p))]
    if not target_paths:
        return {"ok": False, "error": "未提供有效文件路径"}

    deleted: List[str] = []
    errors: List[Dict[str, str]] = []

    for np in target_paths:
        if os.path.isdir(np):
            errors.append({"path": np, "error": "安全限制：仅支持永久删除文件，不支持直接删除文件夹"})
            continue
        if not os.path.isfile(np):
            errors.append({"path": np, "error": "文件不存在或已删除，请使用“移除记录”清理"})
            continue
        try:
            os.unlink(np)
            deleted.append(np)
        except Exception as exc:
            errors.append({"path": np, "error": f"删除失败: {exc}"})
            continue

        # 清理对应的 fl_preview 只读 Markdown 镜像
        if preview_roots:
            stem = Path(np).stem
            h6 = hashlib.md5(np.lower().encode("utf-8", errors="ignore")).hexdigest()[:6]
            mirror_name = f"{stem}_{h6}.preview.md"
            for pr in preview_roots:
                try:
                    mfile = Path(pr) / mirror_name
                    if mfile.is_file():
                        mfile.unlink()
                except OSError:
                    pass

    if deleted:
        del_keys = {path_key(p) for p in deleted}
        with STATE_LOCK:
            settings = load_settings(config_path)
            settings["pinnedFiles"] = [p for p in (settings.get("pinnedFiles") or []) if path_key(p) not in del_keys]
            settings["archivedFiles"] = [p for p in (settings.get("archivedFiles") or []) if path_key(p) not in del_keys]
            save_settings(config_path, settings)

            records = load_archive_records(archive_index_path)
            for dk in del_keys:
                records.pop(dk, None)
            atomic_write_json(archive_index_path, records)

            remove_paths_from_sent_index(sent_index_path, deleted)
            record_tombstones(deleted_index_path, deleted, reason="deleted")

        if renders_dir and Path(renders_dir).is_dir():
            prune_renders(Path(renders_dir), keep_max=40)

        if pinned_manifest_sync_cb:
            try:
                pinned_manifest_sync_cb(settings.get("pinnedFiles") or [])
            except Exception:
                pass
    else:
        settings = load_settings(config_path)

    return {
        "ok": len(deleted) > 0 and len(errors) == 0,
        "partialOk": len(deleted) > 0,
        "deleted": deleted,
        "errors": errors,
        "config": settings,
    }


# ---------------------------------------------------------------------------
# 7. PDF & Office 逐页渲染引擎 (/api/pdf-pages, /api/pdf-image)
# ---------------------------------------------------------------------------

_EXTRA_WIN_BIN_DIRS = [
    r"C:\Program Files\LibreOffice\program",
    r"C:\Program Files (x86)\LibreOffice\program",
    r"C:\Program Files\poppler\Library\bin",
    r"C:\Program Files\poppler\bin",
]


def find_executable(cmd_names: Iterable[str]) -> Optional[str]:
    """在 PATH 与 Windows 常见软件目录中查找可执行文件。"""
    for name in cmd_names:
        found = shutil.which(name)
        if found:
            return found
    if os.name == "nt":
        local_app = os.environ.get("LOCALAPPDATA") or ""
        user_prof = os.environ.get("USERPROFILE") or ""
        candidates_dirs = list(_EXTRA_WIN_BIN_DIRS)
        if local_app:
            candidates_dirs.append(os.path.join(local_app, "Programs", "MiKTeX", "miktex", "bin", "x64"))
        if user_prof:
            candidates_dirs.append(os.path.join(user_prof, "scoop", "shims"))
        for d in candidates_dirs:
            if not os.path.isdir(d):
                continue
            for name in cmd_names:
                for ext in (".exe", ".com", ""):
                    p = os.path.join(d, name + ext)
                    if os.path.isfile(p):
                        return p
    return None


def prune_renders(renders_dir: Path, keep_max: int = 60) -> int:
    """保留最近使用的 keep_max 份页面渲染缓存，清理多余目录以防磁盘占用膨胀。"""
    rdir = Path(renders_dir)
    if not rdir.is_dir():
        return 0
    subdirs = []
    try:
        for entry in rdir.iterdir():
            if entry.is_dir():
                try:
                    mtime = entry.stat().st_mtime
                except OSError:
                    mtime = 0
                subdirs.append((mtime, entry))
    except OSError:
        return 0

    if len(subdirs) <= keep_max:
        return 0
    subdirs.sort(key=lambda x: x[0], reverse=True)
    removed = 0
    for _, old_dir in subdirs[keep_max:]:
        try:
            shutil.rmtree(str(old_dir), ignore_errors=True)
            removed += 1
        except Exception:
            pass
    return removed


def _run_subprocess_quiet(cmd: List[str], timeout: int = 35) -> Tuple[int, str, str]:
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW") else 0
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        creationflags=creationflags,
    )
    return proc.returncode, proc.stdout or "", proc.stderr or ""


def render_document_pages(
    raw_path: str,
    renders_dir: Path,
    pdf_max_pages: int = 20,
    pdf_dpi: int = 110,
) -> Dict[str, Any]:
    """
    渲染 PDF 或 Office 文档为逐页 JPEG 图像：
    - PDF: 直接使用 pdfinfo + pdftoppm；
    - Office (.docx/.pptx/.xlsx 等): 若检测到 soffice/libreoffice，先转 PDF 再逐页渲染；否则明确返回 fallback 信号，由前端平滑切换内置文本/HTML/侧栏视图。
    """
    np = norm_path_str(raw_path)
    if not np or not os.path.isfile(np):
        return {"ok": False, "code": "NOT_FOUND", "error": "文件不存在"}

    ext = os.path.splitext(np)[1].lower()
    if ext != ".pdf" and ext not in OFFICE_CONVERTIBLE_EXTS:
        return {"ok": False, "code": "UNSUPPORTED_EXT", "error": f"不支持分页渲染的文件类型: {ext}"}

    max_pages = _clamp_int(pdf_max_pages, 1, 40, 20)
    dpi = _clamp_int(pdf_dpi, 80, 160, 110)

    try:
        st = os.stat(np)
    except OSError as exc:
        return {"ok": False, "code": "STAT_FAILED", "error": str(exc)}

    pdfinfo_bin = find_executable(["pdfinfo"])
    pdftoppm_bin = find_executable(["pdftoppm"])
    if not pdfinfo_bin or not pdftoppm_bin:
        return {
            "ok": False,
            "code": "NO_PDF_TOOLS",
            "error": "本机未找到 pdfinfo/pdftoppm，无法按页渲染图像预览，请使用侧边栏或本地软件打开。",
        }

    token_seed = f"{path_key(np)}|{st.st_mtime_ns}|{st.st_size}|{dpi}|{max_pages}"
    token = hashlib.sha256(token_seed.encode("utf-8", errors="ignore")).hexdigest()[:24]

    rdir = Path(renders_dir)
    out_dir = rdir / token
    meta_file = out_dir / "meta.json"

    # 缓存命中直接返回
    if meta_file.is_file():
        cached = read_json_safe(meta_file, None)
        if isinstance(cached, dict) and cached.get("ok") and isinstance(cached.get("pageFiles"), list):
            all_present = all((out_dir / fname).is_file() for fname in cached["pageFiles"])
            if all_present:
                try:
                    os.utime(str(out_dir), None)
                except OSError:
                    pass
                return {
                    "ok": True,
                    "cached": True,
                    "token": token,
                    "totalPages": cached["totalPages"],
                    "renderedPages": len(cached["pageFiles"]),
                    "truncated": bool(cached.get("truncated")),
                    "dpi": dpi,
                    "sourceExt": ext,
                    "pages": [
                        f"/api/pdf-image?token={token}&page={i + 1}"
                        for i in range(len(cached["pageFiles"]))
                    ],
                }

    out_dir.mkdir(parents=True, exist_ok=True)
    pdf_source = np

    # Office 先转 PDF
    if ext in OFFICE_CONVERTIBLE_EXTS:
        soffice_bin = find_executable(["soffice", "libreoffice"])
        if not soffice_bin:
            return {
                "ok": False,
                "code": "NO_OFFICE_CONVERTER",
                "error": "本机未安装 LibreOffice，已回退到内置内容/侧边栏只读预览。",
            }
        try:
            rc, _, err = _run_subprocess_quiet(
                [soffice_bin, "--headless", "--norestore", "--convert-to", "pdf", "--outdir", str(out_dir), np],
                timeout=45,
            )
            converted_candidates = list(out_dir.glob("*.pdf"))
            if rc != 0 or not converted_candidates:
                return {
                    "ok": False,
                    "code": "OFFICE_CONVERT_FAILED",
                    "error": f"Office 转 PDF 失败，已回退内置文本预览。{err[:160]}",
                }
            pdf_source = str(converted_candidates[0])
        except Exception as exc:
            return {
                "ok": False,
                "code": "OFFICE_CONVERT_FAILED",
                "error": f"Office 转 PDF 超时或失败 ({exc})，已回退内置预览。",
            }

    # 读取总页数
    total_pages = 1
    try:
        rc, out_txt, err_txt = _run_subprocess_quiet([pdfinfo_bin, pdf_source], timeout=15)
        if rc == 0:
            m_pages = re.search(r"^Pages:\s*(\d+)", out_txt, re.MULTILINE)
            if m_pages:
                total_pages = max(1, int(m_pages.group(1)))
    except Exception:
        total_pages = 1

    last_page = min(total_pages, max_pages)
    prefix = str(out_dir / "page")

    # 清理之前残余页图
    for old_jpg in out_dir.glob("page-*.jpg"):
        try:
            old_jpg.unlink()
        except OSError:
            pass

    try:
        rc, _, err_txt = _run_subprocess_quiet(
            [pdftoppm_bin, "-jpeg", "-r", str(dpi), "-f", "1", "-l", str(last_page), pdf_source, prefix],
            timeout=60,
        )
    except Exception as exc:
        return {"ok": False, "code": "RENDER_TIMEOUT", "error": f"PDF 渲染失败: {exc}"}

    def _page_sort_key(p: Path) -> Tuple[int, str]:
        m = re.search(r"(\d+)\.jpg$", p.name, re.IGNORECASE)
        return (int(m.group(1)) if m else 0, p.name)

    page_files = sorted(out_dir.glob("page-*.jpg"), key=_page_sort_key)
    if rc != 0 or not page_files:
        return {
            "ok": False,
            "code": "RENDER_FAILED",
            "error": f"pdftoppm 渲染失败: {(err_txt or '').strip()[:180]}",
        }

    file_names = [pf.name for pf in page_files]
    meta_payload = {
        "ok": True,
        "token": token,
        "totalPages": max(total_pages, len(file_names)),
        "renderedPages": len(file_names),
        "truncated": total_pages > max_pages,
        "dpi": dpi,
        "sourceExt": ext,
        "pageFiles": file_names,
        "createdAt": int(time.time() * 1000),
    }
    atomic_write_json(meta_file, meta_payload)
    prune_renders(rdir, keep_max=60)

    return {
        "ok": True,
        "cached": False,
        "token": token,
        "totalPages": meta_payload["totalPages"],
        "renderedPages": meta_payload["renderedPages"],
        "truncated": meta_payload["truncated"],
        "dpi": dpi,
        "sourceExt": ext,
        "pages": [f"/api/pdf-image?token={token}&page={i + 1}" for i in range(len(file_names))],
    }


def resolve_render_image_path(renders_dir: Path, token: str, page_str: str) -> Optional[Path]:
    """严格校验 token 与 page 参数并返回 JPEG 图像路径，严防路径穿越。"""
    if not token or not re.fullmatch(r"[a-f0-9]{16,32}", token):
        return None
    try:
        page_num = int(page_str)
    except (TypeError, ValueError):
        return None
    if page_num < 1 or page_num > 200:
        return None

    rdir = Path(renders_dir).resolve()
    target_dir = (rdir / token).resolve()
    try:
        target_dir.relative_to(rdir)
    except ValueError:
        return None

    meta_file = target_dir / "meta.json"
    meta = read_json_safe(meta_file, None)
    if not isinstance(meta, dict) or not isinstance(meta.get("pageFiles"), list):
        return None
    files = meta["pageFiles"]
    if page_num > len(files):
        return None

    fname = str(files[page_num - 1])
    if "/" in fname or "\\" in fname or ".." in fname:
        return None
    img_path = (target_dir / fname).resolve()
    try:
        img_path.relative_to(target_dir)
    except ValueError:
        return None
    return img_path if img_path.is_file() else None



# ---------------------------------------------------------------------------
# 8. Source 归一化、Missing 空壳、Moved 重连与 sent-index 增量协调
# ---------------------------------------------------------------------------

CATEGORY_META_UI: Dict[str, Tuple[str, str, str, int]] = {
    "word": ("Word", "blue", "📘", 95),
    "ppt": ("PPT", "amber", "📊", 100),
    "excel": ("Excel", "green", "📗", 95),
    "pdf": ("PDF", "red", "📕", 95),
    "markdown": ("Markdown", "slate", "📝", 82),
    "text": ("文本/配置", "slate", "📄", 76),
    "image": ("图片", "cyan", "🖼️", 86),
    "web": ("网页/样式", "purple", "🌐", 84),
    "code": ("代码", "blue", "🧩", 68),
    "media": ("音视频", "purple", "🎬", 88),
    "archive": ("压缩包", "amber", "📦", 80),
    "design": ("设计稿", "purple", "🎨", 84),
    "executable": ("可执行程序", "red", "⚙️", 55),
    "database": ("数据库", "amber", "🗄️", 64),
    "font": ("字体", "slate", "🔤", 52),
    "disk": ("磁盘镜像", "slate", "💿", 50),
    "binary": ("二进制", "slate", "🔩", 40),
    "folder": ("文件夹", "amber", "📁", 75),
    "other": ("其他", "slate", "📄", 50),
}

SOURCE_LABELS: Dict[str, str] = {
    "delivered": "交付",
    "created": "生成",
    "edited": "修改",
    "attachment": "发送",
    "read": "读取",
    "pinned": "收藏",
    "archived": "归档",
    "recent": "工作区",
}


def map_action_to_source(action_kind: str, ext: str = "", is_user_sent: bool = False) -> str:
    """将内部 actionKind 归一化为与 DSH 对齐的 source 维度。"""
    if is_user_sent or action_kind == "user_sent":
        return "attachment"
    ak = (action_kind or "").lower()
    if ak == "pinned":
        return "pinned"
    if ak == "archived":
        return "archived"
    if ak == "read":
        return "read"
    if ak == "edited":
        return "edited"
    if ak in {"artifact", "linked"}:
        return "delivered"
    if ak == "created":
        if (ext or "").lower() in DELIVERABLE_DOC_EXTS:
            return "delivered"
        return "created"
    return "recent"


def build_file_item(
    raw_path: str,
    action_kind: str = "recent",
    step_index: int = -1,
    *,
    is_user_sent: bool = False,
    last_known_size: int = 0,
    last_known_mtime_ms: int = 0,
    last_known_is_dir: bool = False,
    allow_missing: bool = False,
) -> Optional[Dict[str, Any]]:
    """
    构造增强文件条目（支持 20+ 类型、文件夹、可选 missing 空壳与规范 source）。
    """
    norm = norm_path_str(raw_path)
    if not norm:
        return None
    exists = os.path.exists(norm)
    if not exists and not allow_missing:
        return None

    missing = not exists
    if exists:
        try:
            st = os.stat(norm)
            is_dir = os.path.isdir(norm)
            size = 0 if is_dir else int(st.st_size)
            mtime_ms = int(st.st_mtime * 1000)
        except OSError:
            return None
    else:
        is_dir = bool(last_known_is_dir)
        size = int(last_known_size or 0)
        mtime_ms = int(last_known_mtime_ms or 0)

    ext = "" if is_dir else os.path.splitext(norm)[1].lower()
    category, badge = classify_extension_full(ext, is_dir=is_dir)
    cat_label, color, icon, priority = CATEGORY_META_UI.get(category, ("其他", "slate", "📄", 50))
    if ext == ".csv":
        cat_label = "Excel/数据"
    elif ext == ".svg":
        icon = "🎨"

    try:
        file_uri = Path(norm).as_uri()
    except Exception:
        file_uri = "file:///" + norm.replace("\\", "/")

    source = map_action_to_source(action_kind, ext=ext, is_user_sent=is_user_sent)
    is_readable = bool(
        is_user_sent
        or is_dir
        or ext in DELIVERABLE_DOC_EXTS
        or ext in IMAGE_EXTS
        or category in {"media", "archive", "design"}
    )

    return {
        "path": norm,
        "name": os.path.basename(norm) or norm,
        "dir": os.path.dirname(norm),
        "ext": ext,
        "isDir": is_dir,
        "size": size,
        "mtimeMs": mtime_ms,
        "fileUri": file_uri,
        "badge": badge,
        "color": color,
        "icon": icon,
        "priority": priority,
        "actionKind": action_kind,
        "source": source,
        "sourceLabel": SOURCE_LABELS.get(source, "文件"),
        "stepIndex": step_index,
        "category": category,
        "categoryLabel": cat_label,
        "isReadable": is_readable,
        "missing": missing,
        "moved": False,
        "movedFrom": "",
    }


def reconcile_missing_and_moved(
    items: List[Dict[str, Any]],
    tombstones: Dict[str, Dict[str, Any]],
    search_dirs: Iterable[str],
    deleted_index_path: Path,
) -> List[Dict[str, Any]]:
    """
    结合墓碑与项目目录，过滤已删除项，尝试把 missing 项重连至新路径 (moved=True)。
    """
    existing_keys = {path_key(it["path"]) for it in items if not it.get("missing") and it.get("path")}
    clear_list: List[str] = []
    out: List[Dict[str, Any]] = []
    search_list = [norm_path_str(d) for d in (search_dirs or []) if d and os.path.isdir(d)]

    for it in items:
        raw_p = it.get("path") or ""
        if not raw_p:
            continue
        is_explicit_recent = bool(it.get("isCurrentConv") and not it.get("missing"))
        if should_suppress_by_tombstone(
            raw_p,
            tombstones,
            is_explicit_current_event=is_explicit_recent,
            clear_paths_collector=clear_list,
        ):
            continue

        if it.get("missing") and search_list:
            cand = detect_moved_target(
                raw_p,
                expected_size=it.get("size") or None,
                is_dir=bool(it.get("isDir")),
                search_dirs=search_list,
                exclude_paths=existing_keys,
            )
            if cand and os.path.exists(cand):
                # 用新路径重建 item 并保留原身份字段
                rebuilt = build_file_item(
                    cand,
                    action_kind=it.get("actionKind") or "recent",
                    step_index=it.get("stepIndex", -1),
                    is_user_sent=bool(it.get("isUserSent")),
                )
                if rebuilt:
                    for carry_key in ("isUserSent", "convId", "isCurrentConv", "sentScope", "sentScopeLabel", "source", "sourceLabel"):
                        if carry_key in it and it[carry_key]:
                            rebuilt[carry_key] = it[carry_key]
                    rebuilt["moved"] = True
                    rebuilt["movedFrom"] = raw_p
                    existing_keys.add(path_key(cand))
                    out.append(rebuilt)
                    continue

        out.append(it)

    if clear_list:
        clear_tombstones(deleted_index_path, clear_list)
    return out


def sync_sent_index_incremental(
    sent_index_path: Path,
    conv_tasks: List[Dict[str, Any]],
    scan_conv_cb,
    *,
    force_rescan: bool = False,
    max_convs: int = 20,
) -> List[Dict[str, Any]]:
    """
    增量维护 file_launcher_sent_index.json：
    - 每个会话校验 transcript.jsonl 和 .user_uploaded 的签名，未变化则直接复用已持久化的记录；
    - 仅扫描发生变更的会话，且首次冷启/全扫上限默认 20 个最新会话（当前会话优先），防止全盘扫描造成卡顿或内存暴涨。
    """
    with STATE_LOCK:
        index_data = load_sent_index(sent_index_path)
    convs_store: Dict[str, Any] = index_data.setdefault("conversations", {})
    changed = False

    limited_tasks = conv_tasks[:max_convs]
    merged_by_key: Dict[str, Dict[str, Any]] = {}

    for task in limited_tasks:
        cid = task["convId"]
        is_current = bool(task.get("isCurrent"))
        sig = str(task.get("sig") or "")
        cached_entry = convs_store.get(cid)

        records: List[Dict[str, Any]]
        if not force_rescan and not is_current and isinstance(cached_entry, dict) and cached_entry.get("sig") == sig:
            records = list(cached_entry.get("items") or [])
        elif not force_rescan and is_current and isinstance(cached_entry, dict) and cached_entry.get("sig") == sig:
            records = list(cached_entry.get("items") or [])
        else:
            records = scan_conv_cb(task)
            convs_store[cid] = {
                "sig": sig,
                "updatedAt": int(time.time() * 1000),
                "items": records,
            }
            changed = True

        for rec in records:
            p = rec.get("path") or ""
            k = path_key(p)
            if not k:
                continue
            item = dict(rec)
            item["convId"] = cid
            item["isCurrentConv"] = is_current
            item["sentScope"] = "current" if is_current else "history"
            item["sentScopeLabel"] = "当前会话发送" if is_current else "历史会话发送"

            prev = merged_by_key.get(k)
            if not prev:
                merged_by_key[k] = item
            else:
                if is_current and prev.get("sentScope") != "current":
                    prev["sentScope"] = "current"
                    prev["sentScopeLabel"] = "当前会话发送"
                    prev["isCurrentConv"] = True
                    prev["convId"] = cid
                if int(item.get("stepIndex") or 0) > int(prev.get("stepIndex") or -1):
                    prev["stepIndex"] = int(item.get("stepIndex") or 0)

    # 清理超量历史缓存条数，避免 sent_index.json 无限增长
    if len(convs_store) > 80:
        sorted_cids = sorted(
            convs_store.keys(),
            key=lambda c: float((convs_store.get(c) or {}).get("updatedAt") or 0),
            reverse=True,
        )
        for old_cid in sorted_cids[80:]:
            convs_store.pop(old_cid, None)
            changed = True

    if changed:
        with STATE_LOCK:
            save_sent_index(sent_index_path, index_data)

    return list(merged_by_key.values())
