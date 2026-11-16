---
name: file-launcher
description: Open the File Launcher side panel or register target files/directories so clicking a filename opens it directly in the Antigravity right sidebar, copies @ file references in one click, multi-selects files for batch actions, stars files for anti-compaction, or opens with matched desktop apps.
---

# File Launcher Skill

Use this skill when the user wants to:
- Click a generated file or deliverable to preview it directly in the Antigravity right sidebar (`fileView`);
- Project-first hierarchical isolation (`项目隔离`) keeping unrelated workspaces strictly separated, while allowing one-click copy of `@文件名（完整路径）` references (`复制引用`) for cross-project/cross-conversation chatting;
- Multi-select deliverables to copy `@` references in batch (`复制引用`), star/pin, archive, or remove index entries;
- Star/pin files for anti-compaction protection or archive deliverables into `Archived_Docs` (uses `D:\projects\Archived_Docs` when present, or `~/Documents/AntigravityFileLauncher/Archived_Docs` otherwise);
- Choose an "Open With" application (Windows native "Open With..." dialog, VS Code, WPS/Office, browser, or custom executable) or reveal in File Explorer (`explorer /select`).

## 1. Opening the File Launcher Side Panel

Emit the UI plugin pill link in your response so the user can toggle the **File Launcher** panel in one click:

```markdown
[File Launcher](sidecar://file-launcher/launcher_pane/)
```

## 2. How the File Launcher Panel Works Automatically

The `file-launcher/launcher_pane` sidecar automatically discovers files without requiring manual registration:
1. **Current Session Files**: Parses the active conversation's `transcript.jsonl` / `transcript_full.jsonl` (including `run_command` / helper-script deliverable outputs, `PLANNER_RESPONSE` file links, and `fl_preview` origins) and artifact folder (`<appData>/brain/<conversationId>/`) in real time while ignoring internal wrapper files like `file_capsules.html` and `*.metadata.json`.
2. **Recent Project Deliverables**: Scans configured watched directories (defaults to `D:\projects` if present, otherwise Desktop) and workspace roots for recently created or updated deliverables (`.pptx`, `.pdf`, `.docx`, `.xlsx`, `.html`, `.md`, `.png`, source files, etc.).
3. **Pinned / Custom Files**: Reads `~/.gemini/antigravity/file_launcher_config.json` for user-pinned files, custom watched folders, and custom "Open With" applications.

Note: Never emit broken "加入对话框 / 一键引用" (`bAttach` / `/api/attach`) buttons in embedded cards; always use **`复制引用`** (`@文件名（完整路径）`). To let users open a deliverable in Antigravity's native right sidebar in one click even before opening the sidecar, also emit a concise native `file:///` Markdown preview link (for Office docs, point to its `fl_preview/<name>.md` mirror).

## 3. Programmatically Pinning a Key Deliverable (Optional)

If a workflow generates a final deliverable in an unconventional location outside the conversation transcript or watched directories, you can append or add its path to `~/.gemini/antigravity/file_launcher_config.json` under the `pinnedFiles` array so it appears at the top of the File Launcher panel immediately.
