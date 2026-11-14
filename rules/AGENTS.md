# File Launcher Rules

When completing a task that creates, modifies, or outputs files:

1. **只展示可读文档 (Only Show Readable Documents)**:
   - 在对话中只向用户展示**可读的成品文档与媒体文件**（如 `.docx`, `.doc`, `.pptx`, `.ppt`, `.xlsx`, `.xls`, `.csv`, `.pdf`, `.md`, `.txt`, 图片或音视频）。
   - **一般不显示代码或配置文件**：除非用户明确要求查看代码文件，否则**严禁**在对话的产出文件列表中罗列 `.py`, `.css`, `.js`, `.mjs`, `.ts`, `.json`, `.ps1`, `.sh` 等代码或样式文件。
2. **对话内交互式文件胶囊 + 旁边直接选打开方式 (Inline File Capsules with App Selector)**:
   - 当产出可读文档时，使用 `write_file`（带 `ArtifactMetadata`: `UserFacing: true`, `RequestFeedback: false`）在 `<Artifact Directory Path>` 下生成一个紧凑的高对比度交互式文件胶囊组件（如 `file_capsules.html`），并通过 `<agent-embed src="file:///<Artifact Directory Path>/file_capsules.html"></agent-embed>` 直接嵌入在对话回复中。
   - 每个文件以**圆角胶囊卡片**形式展示，胶囊右侧紧挨着提供：
     - **「⚡ 直接打开」**按钮（调用 `http://127.0.0.1:18765/api/open?path=...&mode=default`）
     - **「🔄 选择打开应用 ▾」**下拉菜单（直接列出系统默认软件、Microsoft Word、WPS Office、记事本、VS Code、Windows「打开方式...」弹窗，选定即可打开）
     - **「👁️ 在对话中直接预览」**按钮（点击直接在胶囊下方展开文档内容阅读器）
     - **「📂 文件夹」**按钮（调用 `mode=reveal` 在资源管理器中选中文件）
3. **保留右侧面板胶囊入口**:
   - 在回复末尾单独一行保留 `[File Launcher](sidecar://file-launcher/launcher_pane/)` 以便用户随时呼出右侧常驻面板。
