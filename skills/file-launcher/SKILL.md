---
name: file-launcher
description: Open the File Launcher side panel or register target files/directories so the user can click-to-open files directly, choose an "Open With" application (VS Code, Office/WPS, Notepad, or native Windows Open With dialog), or reveal files in File Explorer.
---

# File Launcher Skill

Use this skill when the user wants to:
- Click-to-open generated files or project deliverables directly in their native desktop application;
- Choose an "Open With" application (e.g., Windows native "Open With..." dialog, VS Code, Antigravity IDE, WPS/Office, browser, or custom executable);
- Reveal a generated file directly in Windows File Explorer (`explorer /select`);
- Pin or register specific files or output directories into the **File Launcher** auxiliary panel.

## 1. Opening the File Launcher Side Panel

Emit the UI plugin pill link in your response so the user can toggle the **File Launcher** panel in one click:

```markdown
[File Launcher](sidecar://file-launcher/launcher_pane/)
```

## 2. How the File Launcher Panel Works Automatically

The `file-launcher/launcher_pane` sidecar automatically discovers files without requiring manual registration:
1. **Current Session Files**: Parses the active conversation's `transcript.jsonl` and artifact folder (`<appData>/brain/<conversationId>/`) in real time to list every file created (`write_file`), modified (`edit_file`), read (`read_file`), or linked (`file:///...`).
2. **Recent Project Deliverables**: Scans `D:\projects` (and any user-configured workspace directories) for recently created or updated deliverables (`.pptx`, `.pdf`, `.docx`, `.xlsx`, `.html`, `.md`, `.png`, source files, etc.).
3. **Pinned / Custom Files**: Reads `~/.gemini/antigravity/file_launcher_config.json` for user-pinned files, custom watched folders, and custom "Open With" applications.

## 3. Programmatically Pinning a Key Deliverable (Optional)

If a workflow generates a final deliverable in an unconventional location outside the conversation transcript or `D:\projects`, you can append or add its path to `~/.gemini/antigravity/file_launcher_config.json` under the `pinnedFiles` array so it appears at the top of the File Launcher panel immediately.
