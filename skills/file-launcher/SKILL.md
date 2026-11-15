---
name: file-launcher
description: Open the File Launcher side panel or register target files/directories so clicking a filename opens it directly in the Antigravity right sidebar, multi-selects files to attach to chat without pasting, stars files for anti-compaction, or opens with matched desktop apps.
---

# File Launcher Skill

Use this skill when the user wants to:
- Click a generated file or deliverable to preview it directly in the Antigravity right sidebar (`fileView`);
- Project-first hierarchical isolation (`项目隔离`) keeping unrelated workspaces strictly separated, while allowing active cross-project/cross-conversation references into the current dialog (`加入对话框`);
- Multi-select deliverables and attach them directly into the chat box (`加入对话框`) via host `addArtifactComment` (with `selection.content`) and automatic `OPEN_SIDECAR` wakeup without copying or pasting raw paths;
- Star/pin files for anti-compaction protection or archive deliverables into `Archived_Docs` (uses `D:\projects\Archived_Docs` when present, or `~/Documents/AntigravityFileLauncher/Archived_Docs` otherwise);
- Choose an "Open With" application (Windows native "Open With..." dialog, VS Code, WPS/Office, browser, or custom executable) or reveal in File Explorer (`explorer /select`).

## 1. Opening the File Launcher Side Panel

Emit the UI plugin pill link in your response so the user can toggle the **File Launcher** panel in one click:

```markdown
[File Launcher](sidecar://file-launcher/launcher_pane/)
```

## 2. How the File Launcher Panel Works Automatically

The `file-launcher/launcher_pane` sidecar automatically discovers files without requiring manual registration:
1. **Current Session Files**: Parses the active conversation's `transcript.jsonl` and artifact folder (`<appData>/brain/<conversationId>/`) in real time to list every file created (`write_file`), modified (`edit_file`), read (`read_file`), or linked (`file:///...`).
2. **Recent Project Deliverables**: Scans configured watched directories (defaults to `D:\projects` if present, otherwise Desktop) and workspace roots for recently created or updated deliverables (`.pptx`, `.pdf`, `.docx`, `.xlsx`, `.html`, `.md`, `.png`, source files, etc.).
3. **Pinned / Custom Files**: Reads `~/.gemini/antigravity/file_launcher_config.json` for user-pinned files, custom watched folders, and custom "Open With" applications.

## 3. Programmatically Pinning a Key Deliverable (Optional)

If a workflow generates a final deliverable in an unconventional location outside the conversation transcript or watched directories, you can append or add its path to `~/.gemini/antigravity/file_launcher_config.json` under the `pinnedFiles` array so it appears at the top of the File Launcher panel immediately.
