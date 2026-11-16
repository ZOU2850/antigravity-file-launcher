# Antigravity File Launcher (`v2.4.0`)

面向 **Google Antigravity** 的 Codex 极简风文档与文件快速启动器插件，现已**全面对齐 `dsh-file-launcher` (`v1.4.3`) 核心能力**，同时完整保留 Antigravity 原生侧边栏与跨对话工作流优势。

---

## ✨ 核心特性（Antigravity 原生 + DSH v1.4.3 对齐）

### 1. 智能文件发现、@引用解析与全量分类
- **全来源感知**：自动提取当前/历史对话的 AI 交付与生成/修改/读取文件、`brain/<conv>` 产出物、`@引用` 与上传附件、工作区项目及监控目录文件。
- **增强 `@引用` 与 `@文件夹` 解析**：支持 `@"含空格路径"`、`@'...'`、工作区相对路径、中文句尾标点裁剪（同行多个 `@` 互不吞并）及 `@目录`（点击或右键直接打开资源管理器）。
- **全量 19 类文件 + 文件夹 (`DIR`)**：完整支持 Word、PPT、Excel/CSV、PDF、Markdown、文本/配置、图片、网页/样式、代码、音视频、压缩包、设计稿 (`.fig/.psd`)、数据库 (`.db/.sqlite`)、字体 (`.ttf/.woff2`)、可执行程序、磁盘镜像、二进制与文件夹。

### 2. 三层精准隔离 + Source × Type 主从复合筛选
- **顶部 `隔离范围` 下拉框**：读取 Antigravity `conversation_summaries.db`，真实分离 **Antigravity 项目**、**左侧边栏对话标题**、**本地监控目录** 与 **全部范围**。
- **`筛选 ▾` 主从双栏弹层**：左栏按来源（对话交付 / AI 生成 / AI 修改 / 我发送的 / 参考读取 / 工作区 / 防压缩收藏）统计，右栏按选定来源联动统计文件类型；已选筛选会在工具栏下方显示可单独点 `×` 清除的标签。
- **独立 `📦 已归档` 开关**：一键切换查看归档备份及其源文件路径，平时隐藏归档项保持列表整洁。
- **多维度排序与分组**：支持 `时间↓ / 时间↑ / 名称 / 类型` 排序，支持 `按类型分组 / 按项目 → 会话两级折叠 / 平铺列表`，搜索或筛选时自动强制展开。

### 3. 双预览体验：侧边栏分栏直开 + 内置 PDF/Office 逐页预览器
- **默认侧边栏分栏直开**（可在设置中切换默认动作）：点击文件名直接在 Antigravity 右侧 `fileView` 分栏打开（`.docx` / `.pptx` / `.xlsx` 自动生成只读预览镜像至 `fl_preview/`）。
- **增强内置预览器**：
  - **PDF / Office 逐页图像浏览**：调用本机 `pdfinfo` / `pdftoppm`（如 MiKTeX / Poppler）逐页高清 JPEG 渲染，装有 LibreOffice (`soffice`) 时支持 Office 转 PDF 分页浏览；无 LibreOffice 时自动平滑回退到内置 DOCX/PPTX/XLSX 结构化阅读并给出提示；
  - 提供 **上一页 / 下一页、滚动追踪页码、50%–250% 缩放持久化、上下文件切换 (`← / →`)、`Esc` 关闭**、一键「分栏打开」以及图片剪贴板「复制图片」。

### 4. 安全文件管理与防上下文压缩
- **按日期归档 + 防重名覆盖**：归档副本保存至 `<archiveRoot>/YYYY-MM-DD/<filename>`，同名文件自动追加 `(2)`、`(3)` 后缀绝不覆盖历史归档；支持自定义归档目录与恢复默认。
- **★ 收藏保留（防上下文压缩）**：同步写入 `Pinned_Protected_Files/PINNED_FILES_MANIFEST.md` 与当前对话保护区。
- **缺失空壳 (`missing`)、移动重连 (`moved`) 与永久删除**：
  - 历史记录文件在磁盘失踪时保留 `不存在` 空壳行并可右键「移除不存在记录」(`/api/forget`)；若文件在项目其他目录出现且文件名匹配，自动重连为 `已移动`；
  - 右键菜单「永久删除文件…」需弹窗二次确认（`POST /api/delete` 带 `confirm=true`），同步清理只读镜像、渲染缓存、pin/archive 并写入墓碑 `file_launcher_deleted.json` 防止再次扫回 ghost（严禁删除文件夹）。

### 5. 一键「复制引用」与浮动右键菜单
- **一键复制 `@` 引用**：每行文件右侧与多选底栏均提供「复制引用」按钮，点击即可按 `@文件名（完整路径）` 格式复制跨项目/跨对话引用文本；在聊天框粘贴发送后，系统会在「我发送的」列表自动生成可无感打开原文件的「引用」条目。
- **浮动自适应可滚动菜单**：整行右键与点「打开方式 ▾」弹出视口边缘防溢出菜单，支持键盘 `↑ / ↓ / Enter / Esc`、按后缀匹配本机应用（支持点击右侧「设为默认」或按住 `Alt` 设为后缀默认）、复制 `@引用` / 完整路径 / 图片、定位文件资源管理器及呼出 Windows 系统打开方式。

### 6. 内置设置面板 (`⚙`) 与低开销运行
- **4 种主题模式（实时生效）**：`跟随宿主 (Host)` / `浅色 (Light)` / `深色 (Dark)` / `跟随系统 (System)`。
- **可控刷新与限流**：后台定时刷新间隔可调 `5–300` 秒（默认 `60` 秒）或关闭；对话内嵌卡片仍通过 `/api/poll-open` 毫秒级长轮询实时响应；持久化 `file_launcher_sent_index.json` 与原子文件写入 (`tempfile + os.replace`) 防止卡顿与配置损坏。

---

## 📦 目录结构

```text
antigravity-file-launcher/
├── plugin.json                  # Antigravity 插件清单 (v2.4.0)
├── CHANGELOG.md                 # 更新日志
├── README.md
├── install.ps1                  # Windows 一键安装脚本
├── assets/logo.svg
├── rules/AGENTS.md              # 对话侧内嵌文件卡片规范
├── skills/file-launcher/SKILL.md
├── sidecars/launcher_pane/
│   ├── sidecar.json
│   ├── preload.js               # 宿主 UI / Workspace / Agent API 桥接
│   ├── main.py                  # Python 标准库后端 + 18765 对话桥接端口
│   ├── dsh_sync.py              # DSH 对齐核心（原子存储、分类、@解析、归档、墓碑、PDF渲染）
│   ├── index.html
│   ├── styles.css
│   └── app.js
└── tests/
    └── test_alignment.py        # 单元测试 + 隔离 HTTP 端到端集成测试
```

---

## 🚀 安装与更新

### 方法一：一键脚本安装（推荐）
在项目根目录运行 PowerShell：

```powershell
.\install.ps1
```

安装路径：`%USERPROFILE%\.gemini\config\plugins\file-launcher`

### 方法二：可选 PDF/Office 逐页增强依赖
- **PDF 逐页预览**：安装 `poppler`（或已有 MiKTeX）确保 `pdfinfo` / `pdftoppm` 可在 `PATH` 中找到（Windows 亦自动检索 MiKTeX / Poppler / Scoop 常见路径）。
- **Office (.docx/.pptx/.xlsx) 转 PDF 分页**：可选安装 LibreOffice（`soffice`）。未安装时插件会自动回退到内置 DOCX/PPTX/XLSX HTML 预览与 Antigravity 侧边栏 `.md` 只读镜像，不影响日常使用。

---

## 🧪 运行验证与自动化测试

```powershell
# 运行全套单元测试与隔离 HTTP Server 端到端集成测试
python -m unittest discover -s .\tests -v

# 运行快速自检（检查本机已识别软件与会话文件发现）
python .\sidecars\launcher_pane\main.py --selftest

# 检查前端 JavaScript 语法
node --check .\sidecars\launcher_pane\app.js
node --check .\sidecars\launcher_pane\preload.js
```

---

## ⚙️ 数据与状态文件位置

所有状态与缓存均存放于用户配置目录（`%USERPROFILE%\.gemini\antigravity\`）及归档根目录，不污染工作区代码库：
- 统一配置：`file_launcher_config.json`
- 归档详情索引：`file_launcher_archive.json`（默认归档副本目录：`D:\projects\Archived_Docs` 或 `~/Documents/AntigravityFileLauncher/Archived_Docs`，可在设置自定义）
- 删除/移除墓碑：`file_launcher_deleted.json`
- 发送文件增量索引：`file_launcher_sent_index.json`
- PDF 页面图像缓存：`fl_renders/`（自动按最近访问保留裁剪）
