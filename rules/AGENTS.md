# File Launcher Rules

When completing a task that creates, modifies, or outputs files:

1. **只展示可读文档，且绝不重复罗列 (Readable Docs Only, No Duplicate Lists)**:
   - 只向用户展示**可读的成品文档与媒体文件**（如 `.docx`, `.doc`, `.pptx`, `.ppt`, `.xlsx`, `.xls`, `.csv`, `.pdf`, `.md`, `.txt`, 图片或音视频），默认不显示 `.py`, `.css`, `.js`, `.json` 等代码文件。
   - **严禁内容重复**：当使用 `<agent-embed>` 渲染了文件胶囊后，**不要**再在下方用 Markdown 列表重复写一遍文件名链接！
2. **极简小巧的单行文件胶囊 + 旁边直接选打开方式 (Compact 28px Inline File Chips)**:
   - 生成的 HTML 组件必须保持**极简紧凑（单行高度约 28px，自适应内容宽度 `inline-flex`，不铺满整行，不加多余标题栏）**。
   - 每个文件胶囊紧挨着提供小巧的：`[👁️ 预览]`、`[⚡ 打开]`、`[选择打开应用 ▾]` 下拉菜单、`[📂]` 文件夹按钮。
3. **保留底部 `File Launcher` 面板入口**:
   - 在回复末尾单独一行保留 `[File Launcher](sidecar://file-launcher/launcher_pane/)`。
