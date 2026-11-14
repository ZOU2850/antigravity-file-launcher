# File Launcher Rules

When completing a task that creates, modifies, or outputs files:

1. **对话中只展示可读文档，绝不重复罗列 (Readable Docs Only, No Duplicate Lists)**:
   - 在对话回复与默认文件列表中，只向用户展示**可读的成品文档与媒体文件**（`.docx`, `.doc`, `.pptx`, `.ppt`, `.xlsx`, `.xls`, `.csv`, `.pdf`, `.md`, `.txt`, 图片或音视频），默认不展示 `.py`, `.css`, `.js`, `.json` 等代码文件。
   - **严禁重复**：当通过 `<agent-embed>` 展示了交互式文件条后，**不要**再在下方用 Markdown 列表重复罗列一次这些文档。
2. **Codex 极简文件条 + 智能「打开方式 ▾」**:
   - 生成的 HTML 组件采用 Codex 桌面端单色极简风格（`36px` 单行卡片，无 Emoji，无多余「预览」按钮）。
   - 点击左侧文件名直接用系统默认软件打开；右侧仅保留一个 **`打开方式 ▾`** 下拉菜单，里面包含：
     1. **`Antigravity 内部打开`**（通过本地桥接 `/api/internal-open` 或内嵌阅读器直接在反重力内部打开）
     2. **按后缀精准匹配到的本机软件**（如 `.docx` 只列 Word / WPS，绝不一股脑塞入不相关软件）
     3. **`文件资源管理器`**（在文件夹中定位选中）
     4. **`选择打开方式...`**（呼出 Windows 系统原生打开方式弹窗）
3. **保留底部 `File Launcher` 面板入口**:
   - 在回复末尾单独一行保留 `[File Launcher](sidecar://file-launcher/launcher_pane/)`。
