# File Launcher Rules

When completing a task that creates, modifies, or outputs files:

1. **对话中只展示可读文档，禁止假功能，并提供真·侧边栏直开链接 (Readable Docs Only)**:
   - 在对话回复与默认文件列表中，只向用户展示**可读的成品文档与媒体文件**（`.docx`, `.doc`, `.pptx`, `.ppt`, `.xlsx`, `.xls`, `.csv`, `.pdf`, `.md`, `.txt`, 图片或音视频），默认不展示 `.py`, `.css`, `.js`, `.json` 等代码脚本及 `file_capsules.html` 外壳本身。
   - **严禁生成「加入对话框 / 一键引用」功能**：绝不生成「加入对话框」「移出对话框」「一键注入引用气泡」、`bAttach` 批量栏、`/api/attach` 或 `ui/update-model-context` 等失效交互，也不要复用旧会话里含此类按钮的过时 `file_capsules.html` 模板；统一只保留 **`复制引用`**（复制 `@文件名（完整路径）`）。
   - **保证能直接在右侧边栏打开文件**：`<agent-embed>` 无法独自唤醒 Antigravity 原生右侧 `fileView` 分栏，因此在展示交互式文件条的同时，对关键成品文档务必在回复中附带精简的原生可点击预览链接（`.md` / `.txt` / 图片直链 `file:///`；`.docx` / `.pptx` / `.xlsx` 同步生成只读预览镜像至 `<conv_id>/fl_preview/<name>.md` 后附 `[📑 侧边栏预览：文件名](file:///.../fl_preview/<name>.md)`），让用户点一下直接打开文件内容，而非只打开插件。
2. **Codex 极简文件条 + 项目隔离 + 复制引用**:
   - 生成的 HTML 组件采用 Codex 桌面端极简风格（`36px` 单行卡片，无多余外层滚动条），使用宿主 CSS 变量（`var(--card)`, `var(--foreground)`, `var(--border)`, `var(--card-border)`）自动适配深浅主题；`<agent-embed>` 的 `src` 必须使用完整 `file:///C:/.../file_capsules.html` 且不设置 `height`。
   - **最优先按项目区分隔离**：File Launcher 默认只显示当前工作区项目或当前对话的文件；切换其他项目后点击行内 **`复制引用`**（或多选批量点 **`复制引用`**），一键复制 `@文件名（完整路径）` 贴入输入框发送，即在「我发送的」里生成可无感打开的「引用」条目。
   - 行内保留 **`复制引用`** 与 **`打开方式 ▾`**（含 `在侧边栏打开`、`用电脑默认/匹配软件打开`、`文件资源管理器`、`选择打开方式...`），支持 **`选择` 多选批量操作**（**`复制引用`**、`★ 收藏`、`📦 归档`、`移除记录`）。
3. **保留底部 `File Launcher` 面板入口**:
   - 在回复末尾单独一行保留 `[File Launcher](sidecar://file-launcher/launcher_pane/)`。
