# -*- coding: utf-8 -*-
"""
Antigravity File Launcher <-> DSH v1.4.3 功能对齐综合自动化测试套件
涵盖：
1. dsh_sync 核心单元测试（Settings 校验、20+ 文件分类、@引用与@文件夹提取、工具调用解析、
   日期子目录+防重名归档、删除二次确认与墓碑防回流、缺失空壳与移动重连、sent-index 增量缓存）
2. PDF 逐页渲染与路径穿越安全校验（若本机安装 pdfinfo/pdftoppm 则执行真实 PDF 渲染验证）
3. 隔离 HTTP Server 端到端路由集成测试（GET/POST /api/settings, /api/batch, /api/forget,
   /api/delete, /api/pdf-pages, /api/pdf-image, /api/state, 静态资源）
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock
from urllib.error import HTTPError
from urllib.request import Request, urlopen

REPO_ROOT = Path(__file__).resolve().parent.parent
SIDECAR_DIR = REPO_ROOT / "sidecars" / "launcher_pane"
if str(SIDECAR_DIR) not in sys.path:
    sys.path.insert(0, str(SIDECAR_DIR))

import dsh_sync
import main as server_main


def build_minimal_pdf_bytes() -> bytes:
    """构造合规单页最小 PDF-1.4 字节流，用于不依赖外部库测试 pdfinfo/pdftoppm。"""
    objects = [
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n",
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] /Contents 4 0 R >>\nendobj\n",
        b"4 0 obj\n<< /Length 44 >>\nstream\nBT /F1 12 Tf 20 150 Td (Hello DSH) Tj ET\nendstream\nendobj\n",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for obj in objects:
        offsets.append(len(out))
        out.extend(obj)
    xref_pos = len(out)
    out.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    out.extend(b"0000000000 65535 f \n")
    for off in offsets:
        out.extend(f"{off:010d} 00000 n \n".encode("ascii"))
    out.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode("ascii")
    )
    return bytes(out)


class TestDshSyncCore(unittest.TestCase):
    def test_categories_and_folders(self):
        self.assertEqual(dsh_sync.classify_extension_full("", is_dir=True), ("folder", "DIR"))
        expected = {
            ".docx": ("word", "DOCX"),
            ".pptx": ("ppt", "PPTX"),
            ".xlsx": ("excel", "XLSX"),
            ".pdf": ("pdf", "PDF"),
            ".md": ("markdown", "MD"),
            ".yaml": ("text", "YAML"),
            ".png": ("image", "PNG"),
            ".avif": ("image", "AVIF"),
            ".scss": ("web", "SCSS"),
            ".tsx": ("code", "TSX"),
            ".mp4": ("media", "MP4"),
            ".7z": ("archive", "7Z"),
            ".fig": ("design", "FIG"),
            ".exe": ("executable", "EXE"),
            ".sqlite3": ("database", "SQLITE"),
            ".woff2": ("font", "WOFF2"),
            ".iso": ("disk", "ISO"),
            ".wasm": ("binary", "WASM"),
        }
        for ext, pair in expected.items():
            self.assertEqual(dsh_sync.classify_extension_full(ext), pair, f"mismatch for {ext}")

    def test_settings_normalization_and_bounds(self):
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "file_launcher_config.json"
            raw = {
                "appearanceTheme": "invalid_theme",
                "refreshSeconds": 9999,
                "pdfMaxPages": 0,
                "pdfDpi": 500,
                "maxRows": 10,
                "autoRefresh": "false",
                "collapseGroups": True,
                "defaultClickAction": "preview",
                "language": "en",
                "watchedDirs": [td, td],
                "pinnedFiles": [str(Path(td) / "a.md")],
                "extDefaults": {"md": "vscode"},
            }
            saved = dsh_sync.save_settings(cfg_path, raw)
            self.assertEqual(saved["appearanceTheme"], "host")
            self.assertEqual(saved["refreshSeconds"], 300)
            self.assertEqual(saved["pdfMaxPages"], 1)
            self.assertEqual(saved["pdfDpi"], 160)
            self.assertEqual(saved["maxRows"], 100)
            self.assertFalse(saved["autoRefresh"])
            self.assertEqual(saved["defaultClickAction"], "preview")
            self.assertEqual(saved["language"], "en")
            self.assertEqual(len(saved["watchedDirs"]), 1)
            self.assertEqual(saved["extDefaults"], {".md": "vscode"})

            patched = dsh_sync.update_settings_patch(cfg_path, {"appearanceTheme": "dark", "refreshSeconds": 3})
            self.assertEqual(patched["appearanceTheme"], "dark")
            self.assertEqual(patched["refreshSeconds"], 5)

    def test_mention_extraction_and_folder_support(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td) / "workspace"
            sub = ws / "docs" / "design assets"
            sub.mkdir(parents=True)
            f1 = sub / "my report.pdf"
            f1.write_bytes(b"%PDF-1.4")
            f2 = ws / "src" / "main.py"
            f2.parent.mkdir(parents=True)
            f2.write_text("print(1)", encoding="utf-8")

            msg = (
                f'请帮我检查 @"docs/design assets/my report.pdf" 和 @src/main.py这里面是否有问题，'
                f"另外参考文件夹 @docs，忽略邮箱 user@example.com 和 @张三"
            )
            items = dsh_sync.extract_mentions_from_text(msg, workspace_roots=[str(ws)], allow_dirs=True)
            paths = {dsh_sync.path_key(x["path"]): x for x in items}
            self.assertIn(dsh_sync.path_key(str(f1)), paths)
            self.assertIn(dsh_sync.path_key(str(f2)), paths)
            self.assertIn(dsh_sync.path_key(str(ws / "docs")), paths)
            self.assertTrue(paths[dsh_sync.path_key(str(ws / "docs"))]["isDir"])
            self.assertFalse(any("example.com" in k or "张三" in k for k in paths))

    def test_antigravity_parenthesized_references_and_fl_preview(self):
        with tempfile.TemporaryDirectory() as td:
            shots = Path(td) / "shots"
            shots.mkdir()
            shot = shots / "harness-archived-file.png"
            shot.write_bytes(b"\x89PNG\r\n\x1a\n")
            plan = shots / "plan (2).md"
            plan.write_text("# plan", encoding="utf-8")

            msg = (
                f"@harness-archived-file.png（{shot}） 请顺便看下@plan (2).md（{plan}），"
                f"不要误抓 @张三（产品经理）"
            )
            # 无工作区时同样必须精确解析括号内真实路径
            items_no_ws = dsh_sync.extract_user_references_from_text(msg, workspace_roots=[], allow_dirs=True)
            keys_no_ws = {dsh_sync.path_key(x["path"]) for x in items_no_ws}
            self.assertIn(dsh_sync.path_key(str(shot)), keys_no_ws)
            self.assertIn(dsh_sync.path_key(str(plan)), keys_no_ws)
            self.assertEqual(len(keys_no_ws), 2)

            # 有工作区时绝不允许生成 `name（path` 畸形缺失路径
            ws = Path(td) / "ws"
            ws.mkdir()
            items_ws = dsh_sync.extract_user_references_from_text(msg, workspace_roots=[str(ws)], allow_dirs=True)
            self.assertEqual({dsh_sync.path_key(x["path"]) for x in items_ws}, keys_no_ws)

            # Comments on artifact URI 指向 fl_preview 只读镜像时能反向还原到原 Office 文件
            real_docx = shots / "spec.docx"
            real_docx.write_bytes(b"PK\x03\x04")
            prev_dir = Path(td) / "conv" / "fl_preview"
            prev_dir.mkdir(parents=True)
            mirror_md = prev_dir / "spec.md"
            mirror_md.write_text(f"> 📄 **spec.docx** 的只读预览（原文件未改动）　·　原文件：`{real_docx}`\n\n正文", encoding="utf-8")
            step = {
                "step_index": 12,
                "type": "USER_INPUT",
                "source": "USER_EXPLICIT",
                "content": (
                    f"Comments on artifact URI: {mirror_md.resolve().as_uri()} (page title: \"spec.docx\")\n"
                    f"<USER_REQUEST>\n@harness-archived-file.png（{shot}）\n</USER_REQUEST>"
                ),
            }
            extracted = server_main.extract_paths_from_user_step(step, workspace_roots=[])
            by_k = {dsh_sync.path_key(x["path"]): x for x in extracted}
            self.assertIn(dsh_sync.path_key(str(real_docx)), by_k)
            self.assertIn(dsh_sync.path_key(str(shot)), by_k)
            self.assertTrue(by_k[dsh_sync.path_key(str(real_docx))]["isReference"])
            self.assertTrue(by_k[dsh_sync.path_key(str(shot))]["isReference"])

    def test_tool_call_extraction(self):
        p_w = dsh_sync.extract_paths_from_tool_call("write_file", {"Path": r"D:\proj\a.md"})
        self.assertEqual(p_w, [(dsh_sync.norm_path_str(r"D:\proj\a.md"), "created")])
        p_e = dsh_sync.extract_paths_from_tool_call("edit_file", {"Path": r"D:\proj\a.md"})
        self.assertEqual(p_e, [(dsh_sync.norm_path_str(r"D:\proj\a.md"), "edited")])
        p_r = dsh_sync.extract_paths_from_tool_call("read_file", {"Path": r"D:\proj\ref.py"})
        self.assertEqual(p_r, [(dsh_sync.norm_path_str(r"D:\proj\ref.py"), "read")])
        p_patch = dsh_sync.extract_paths_from_tool_call(
            "apply_patch",
            {"patch": "*** Begin Patch\n*** Add File: src/new.ts\n+1\n*** Update File: src/old.ts\n*** End Patch"},
            workspace_roots=[r"D:\proj"],
        )
        self.assertEqual(len(p_patch), 2)
        self.assertEqual(p_patch[0][1], "created")
        self.assertEqual(p_patch[1][1], "edited")

    def test_archive_collision_and_tombstone_delete_forget(self):
        with tempfile.TemporaryDirectory() as td:
            sp = dsh_sync.get_store_paths(Path(td) / "store")
            work = Path(td) / "work"
            work.mkdir()
            doc = work / "plan.md"
            doc.write_text("# v1", encoding="utf-8")

            # 1. 归档到日期子目录 + 重名不覆盖
            r1 = dsh_sync.archive_files_dsh([str(doc)], sp["config"], sp["archiveIndex"], sp["defaultArchiveDir"])
            self.assertTrue(r1["ok"])
            arch1 = Path(r1["copied"][0]["archivePath"])
            self.assertTrue(arch1.is_file())
            self.assertEqual(arch1.name, "plan.md")

            doc.write_text("# v2", encoding="utf-8")
            r2 = dsh_sync.archive_files_dsh([str(doc)], sp["config"], sp["archiveIndex"], sp["defaultArchiveDir"])
            arch2 = Path(r2["copied"][0]["archivePath"])
            self.assertTrue(arch2.is_file())
            self.assertEqual(arch2.name, "plan (2).md")
            self.assertEqual(arch1.read_text(encoding="utf-8"), "# v1")

            # 2. 取消归档保留物理副本
            dsh_sync.unarchive_files_dsh([str(doc)], sp["config"], sp["archiveIndex"])
            self.assertTrue(arch2.is_file())
            self.assertEqual(dsh_sync.load_settings(sp["config"])["archivedFiles"], [])

            # 3. 永久删除要求 confirm=True 且拒绝文件夹
            bad_dir = dsh_sync.delete_files_permanently_dsh(
                [str(work)], True, sp["config"], sp["archiveIndex"], sp["deletedIndex"], sp["sentIndex"]
            )
            self.assertFalse(bad_dir["ok"])
            self.assertTrue(work.is_dir())

            no_conf = dsh_sync.delete_files_permanently_dsh(
                [str(doc)], False, sp["config"], sp["archiveIndex"], sp["deletedIndex"], sp["sentIndex"]
            )
            self.assertFalse(no_conf["ok"])
            self.assertTrue(doc.is_file())

            # 模拟镜像
            prev_dir = Path(td) / "fl_preview"
            prev_dir.mkdir()
            import hashlib
            h6 = hashlib.md5(str(doc).lower().encode("utf-8")).hexdigest()[:6]
            mirror = prev_dir / f"plan_{h6}.preview.md"
            mirror.write_text("mirror", encoding="utf-8")

            ok_del = dsh_sync.delete_files_permanently_dsh(
                [str(doc)],
                True,
                sp["config"],
                sp["archiveIndex"],
                sp["deletedIndex"],
                sp["sentIndex"],
                preview_roots=[prev_dir],
                renders_dir=sp["rendersDir"],
            )
            self.assertTrue(ok_del["ok"])
            self.assertFalse(doc.exists())
            self.assertFalse(mirror.exists())
            tomb = dsh_sync.load_tombstones(sp["deletedIndex"])
            self.assertIn(dsh_sync.path_key(str(doc)), tomb)
            self.assertTrue(dsh_sync.should_suppress_by_tombstone(str(doc), tomb))

            # 4. 显式重建文件 (更新 mtime) 后墓碑自动解除
            import time
            time.sleep(0.02)
            # 人为将 tomb 时间设为更早以稳定校验，不依赖文件系统时间戳精度
            tomb[dsh_sync.path_key(str(doc))]["ts"] -= 5000
            doc.write_text("# reborn", encoding="utf-8")
            cleared = []
            suppressed = dsh_sync.should_suppress_by_tombstone(str(doc), tomb, clear_paths_collector=cleared)
            self.assertFalse(suppressed)
            self.assertEqual(len(cleared), 1)

    def test_moved_relink_and_sent_index_incremental(self):
        with tempfile.TemporaryDirectory() as td:
            sp = dsh_sync.get_store_paths(Path(td) / "store")
            root = Path(td) / "proj"
            old_dir = root / "old"
            new_dir = root / "new"
            old_dir.mkdir(parents=True)
            new_dir.mkdir(parents=True)

            old_file = old_dir / "slides.txt"
            moved_file = new_dir / "slides.txt"
            payload = "hello-moved-world-payload"
            moved_file.write_text(payload, encoding="utf-8")

            missing_item = dsh_sync.build_file_item(
                str(old_file),
                action_kind="user_sent",
                is_user_sent=True,
                allow_missing=True,
                last_known_size=len(payload.encode("utf-8")),
                last_known_mtime_ms=1000,
            )
            self.assertIsNotNone(missing_item)
            self.assertTrue(missing_item["missing"])

            reconciled = dsh_sync.reconcile_missing_and_moved(
                [missing_item],
                {},
                [str(root)],
                sp["deletedIndex"],
            )
            self.assertEqual(len(reconciled), 1)
            self.assertTrue(reconciled[0]["moved"])
            self.assertEqual(dsh_sync.path_key(reconciled[0]["path"]), dsh_sync.path_key(str(moved_file)))

            # sent-index 缓存命中不重复触发 scan_cb
            calls = []
            def fake_scan(task):
                calls.append(task["convId"])
                return [{"path": str(moved_file), "isDir": False, "size": 25, "mtimeMs": 123, "stepIndex": 1}]

            tasks = [{"convId": "conv-a", "isCurrent": False, "sig": "100:200:0"}]
            first = dsh_sync.sync_sent_index_incremental(sp["sentIndex"], tasks, fake_scan, force_rescan=False)
            self.assertEqual(len(calls), 1)
            self.assertEqual(len(first), 1)
            second = dsh_sync.sync_sent_index_incremental(sp["sentIndex"], tasks, fake_scan, force_rescan=False)
            self.assertEqual(len(calls), 1)  # 命中持久化缓存
            self.assertEqual(len(second), 1)


class TestHttpEndpoints(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.store_dir = self.base / "app_data"
        self.work_dir = self.base / "work"
        self.store_dir.mkdir()
        self.work_dir.mkdir()

        self.cfg_path = self.store_dir / "file_launcher_config.json"
        self.patches = [
            mock.patch.object(server_main, "find_app_data_dirs", return_value=[self.store_dir]),
            mock.patch.object(server_main, "get_config_path", return_value=self.cfg_path),
            mock.patch.object(server_main, "get_data_base_dir", return_value=self.base / "data_base"),
        ]
        for p in self.patches:
            p.start()

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), server_main.SidecarRequestHandler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

    def _req(self, path: str, method: str = "GET", payload=None):
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {"Content-Type": "application/json"} if payload is not None else {}
        req = Request(f"http://127.0.0.1:{self.port}{path}", data=data, headers=headers, method=method)
        with urlopen(req, timeout=10) as resp:
            return resp.status, resp.headers.get("Content-Type", ""), resp.read()

    def test_static_and_settings_and_delete_forget_pdf(self):
        # 1. Static files
        st, _, html_bytes = self._req("/")
        self.assertEqual(st, 200)
        self.assertIn(b"app.js?v=2.4.1", html_bytes)
        self.assertIn(b"settingsModal", html_bytes)
        st, _, css_bytes = self._req("/styles.css")
        self.assertEqual(st, 200)
        self.assertIn(b".fl-context-menu", css_bytes)
        self.assertIn(b".ref-badge", css_bytes)
        st, _, js_bytes = self._req("/app.js")
        self.assertEqual(st, 200)
        self.assertIn(b"openContextMenu", js_bytes)

        # 2. Settings GET/POST
        st, _, raw = self._req("/api/settings")
        self.assertEqual(st, 200)
        data = json.loads(raw)
        self.assertTrue(data["ok"])
        self.assertEqual(data["settings"]["refreshSeconds"], 60)

        st, _, raw = self._req(
            "/api/settings",
            method="POST",
            payload={"settings": {"appearanceTheme": "dark", "refreshSeconds": 45, "pdfMaxPages": 10}},
        )
        updated = json.loads(raw)
        self.assertEqual(updated["settings"]["appearanceTheme"], "dark")
        self.assertEqual(updated["settings"]["refreshSeconds"], 45)
        self.assertEqual(updated["settings"]["pdfMaxPages"], 10)

        # 3. Create sample doc & PDF, verify batch archive, forget, delete & PDF rendering
        doc = self.work_dir / "note.md"
        doc.write_text("# test note", encoding="utf-8")
        st, _, raw = self._req("/api/batch", method="POST", payload={"op": "archive", "paths": [str(doc)]})
        arch = json.loads(raw)
        self.assertTrue(arch["ok"])
        self.assertTrue(Path(arch["copied"][0]["archivePath"]).is_file())

        # Forget
        st, _, raw = self._req("/api/forget", method="POST", payload={"path": str(doc)})
        self.assertTrue(json.loads(raw)["ok"])
        self.assertTrue(doc.is_file())

        # Delete without confirm fails; with confirm removes file
        st, _, raw = self._req("/api/delete", method="POST", payload={"path": str(doc), "confirm": False})
        self.assertFalse(json.loads(raw)["ok"])
        st, _, raw = self._req("/api/delete", method="POST", payload={"path": str(doc), "confirm": True})
        self.assertTrue(json.loads(raw)["ok"])
        self.assertFalse(doc.exists())

        # 4. State payload check & Reference Shell workflow (including stale v1 sentIndex invalidation)
        cid = "8a481173-e4c4-4c2f-a406-8a517fad5743"
        conv_dir = self.store_dir / "brain" / cid
        logs_dir = conv_dir / ".system_generated" / "logs"
        up_dir = conv_dir / ".user_uploaded"
        logs_dir.mkdir(parents=True)
        up_dir.mkdir(parents=True)
        ext_shot = self.base / "shots" / "harness-archived-file.png"
        ext_shot.parent.mkdir(parents=True)
        ext_shot.write_bytes(b"\x89PNG\r\n\x1a\n")
        ai_doc = self.work_dir / "ai_report.md"
        ai_doc.write_text("# AI report", encoding="utf-8")
        up_img = up_dir / "upload_sample.png"
        up_img.write_bytes(b"\x89PNG\r\n\x1a\n")

        transcript_lines = [
            json.dumps({
                "step_index": 1,
                "type": "PLANNER_RESPONSE",
                "tool_calls": [{"name": "write_file", "args": {"Path": str(ai_doc)}}],
            }),
            json.dumps({
                "step_index": 2,
                "type": "USER_INPUT",
                "source": "USER_EXPLICIT",
                "created_at": "2026-11-15T20:49:06+08:00",
                "content": f"<USER_REQUEST>\n@harness-archived-file.png（{ext_shot}） @ai_report.md（{ai_doc}）\n</USER_REQUEST>",
            }),
        ]
        t_file = logs_dir / "transcript.jsonl"
        t_file.write_text("\n".join(transcript_lines), encoding="utf-8")

        # 刻意写入一个命中的旧版 v1 空缓存，验证 v2 schema 能自动作废重扫
        t_stat = t_file.stat()
        stale_sig = f"{t_stat.st_mtime_ns}:{t_stat.st_size}:{up_dir.stat().st_mtime_ns}"
        (self.base / "data_base").mkdir(parents=True, exist_ok=True)
        (self.base / "data_base" / "file_launcher_sent_index.json").write_text(
            json.dumps({"version": 1, "conversations": {cid: {"sig": stale_sig, "updatedAt": 1, "items": []}}}),
            encoding="utf-8",
        )

        st, _, raw = self._req(f"/api/state?client=sidecar&ver=2.4.1&conversationId={cid}")
        state_payload = json.loads(raw)
        self.assertTrue(state_payload["ok"])
        self.assertEqual(state_payload["serverVer"], "2.4.1")
        self.assertIn("codeStale", state_payload)
        self.assertIn("capabilities", state_payload)
        self.assertIn("settingsPaths", state_payload)

        sent_by_k = {dsh_sync.path_key(x["path"]): x for x in state_payload["sentFiles"]}
        self.assertIn(dsh_sync.path_key(str(ext_shot)), sent_by_k)
        self.assertIn(dsh_sync.path_key(str(ai_doc)), sent_by_k)
        self.assertIn(dsh_sync.path_key(str(up_img)), sent_by_k)

        ref_item = sent_by_k[dsh_sync.path_key(str(ext_shot))]
        self.assertTrue(ref_item["isReference"])
        self.assertEqual(ref_item["sentKind"], "reference")
        self.assertEqual(ref_item["refLabel"], "引用")
        self.assertEqual(dsh_sync.path_key(ref_item["refTarget"]), dsh_sync.path_key(str(ext_shot)))
        self.assertFalse(sent_by_k[dsh_sync.path_key(str(up_img))]["isReference"])

        # AI 产出的 ai_report.md 被引用进「我发送的」建壳后，依然完好保留在「本次产出」中
        sess_keys = {dsh_sync.path_key(x["path"]) for x in state_payload["sessionFiles"]}
        self.assertIn(dsh_sync.path_key(str(ai_doc)), sess_keys)
        self.assertNotIn(dsh_sync.path_key(str(up_img)), sess_keys)

        # 通过引用壳子 path 无感直接读取预览内容
        from urllib.parse import quote
        st, _, prev_raw = self._req(f"/api/preview?path={quote(ref_item['path'])}")
        self.assertEqual(st, 200)
        self.assertTrue(json.loads(prev_raw)["ok"])

        # 5. PDF pages & path traversal safety
        pdf_file = self.work_dir / "sample.pdf"
        pdf_file.write_bytes(build_minimal_pdf_bytes())
        st, _, raw = self._req("/api/pdf-pages", method="POST", payload={"path": str(pdf_file)})
        pdf_res = json.loads(raw)
        if dsh_sync.find_executable(["pdfinfo"]) and dsh_sync.find_executable(["pdftoppm"]):
            self.assertTrue(pdf_res["ok"], f"PDF render failed: {pdf_res}")
            self.assertGreaterEqual(pdf_res["renderedPages"], 1)
            img_st, img_ct, img_bytes = self._req(pdf_res["pages"][0])
            self.assertEqual(img_st, 200)
            self.assertEqual(img_ct, "image/jpeg")
            self.assertTrue(len(img_bytes) > 100)
        else:
            self.assertEqual(pdf_res["code"], "NO_PDF_TOOLS")

        # 路径穿越防护验证
        with self.assertRaises(HTTPError) as ctx:
            self._req("/api/pdf-image?token=../../etc&page=1")
        self.assertEqual(ctx.exception.code, 404)


if __name__ == "__main__":
    unittest.main(verbosity=2)
