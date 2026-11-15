# File Launcher Rules

When completing a task that creates, modifies, or outputs files:

1. **对话中只展示可读文档，绝不重复罗列 (Readable Docs Only, No Duplicate Lists)**:
   - 在对话回复与默认文件列表中，只向用户展示**可读的成品文档与媒体文件**（`.docx`, `.doc`, `.pptx`, `.ppt`, `.xlsx`, `.xls`, `.csv`, `.pdf`, `.md`, `.txt`, 图片或音视频），默认不展示 `.py`, `.css`, `.js`, `.json` 等代码文件。
   - **严禁重复**：当通过 `<agent-embed src="file:///<artifact_path>/file_capsules.html"></agent-embed>` 展示了交互式文件条后，**不要**再在下方用 Markdown 列表重复罗列一次这些文档。
2. **Codex 极简文件条 + 项目隔离 + 跨项目加入对话框 + 默认侧边栏打开**:
   - 生成的 HTML 组件采用 Codex 桌面端极简风格（`36px` 单行卡片，无多余外层滚动条，支持按后缀自动匹配本机软件），并直接使用宿主注入的 CSS 变量（`var(--card)`, `var(--foreground)`, `var(--border)`, `var(--card-border)`）自动跟随 Antigravity 深色/浅色切换。
   - `<agent-embed>` 的 `src` 属性必须使用完整的 `file:///C:/.../file_capsules.html` 路径，且不设置 `height` 属性。
   - **最优先按项目区分隔离**：File Launcher 默认只显示当前工作区项目或当前对话的文件，严禁把无关项目文件混在同一列表；同时支持切换其他项目勾选文件后点 **`加入对话框`**，**跨项目/跨对话引用并持久化显示在对话框与引用栏中**（无需粘贴路径，底层通过 `OPEN_SIDECAR` 自动唤醒侧边栏 + `addArtifactComment` 的 `selection.content` 挂载原生附件胶囊）。
   - **默认点击文件名直接在右侧侧边栏预览**（`.md` / 文本 / 图片直接打开，`.docx` / `.pptx` / `.xlsx` 自动同步只读预览镜像至 `<conv_id>/fl_preview/` 后打开）；支持 **`选择` 多选批量操作**（**`加入对话框`**、`★ 收藏` 防上下文压缩、`📦 归档`）。
   - 右侧保留 **`打开方式 ▾`** 下拉菜单，里面包含：
     1. **`在侧边栏打开`**（默认体验，同时支持在内部弹出卡片中独立滚动）
     2. **按后缀精准匹配到的本机软件**（如 `.docx` 只列 Word / WPS，绝不一股脑塞入不相关软件）
     3. **`文件资源管理器`**（在文件夹中定位选中）
     4. **`选择打开方式...`**（呼出 Windows 系统原生打开方式弹窗）
3. **保留底部 `File Launcher` 面板入口**:
   - 在回复末尾单独一行保留 `[File Launcher](sidecar://file-launcher/launcher_pane/)`。
