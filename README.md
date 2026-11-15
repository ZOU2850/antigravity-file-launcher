# Antigravity File Launcher (`file-launcher`)

**让 Google Antigravity 拥有像 Codex 桌面端一样的文件管理与一键直达体验：点击即在右侧分栏预览、严格按对话与项目隔离、跨对话引用进输入框，并按文件后缀精准匹配本机软件打开。**

---

## ✨ 核心功能

1. **对话与项目严格隔离（与左侧边栏对齐）**
   - 顶层作用域下拉选择器按 **Antigravity 项目/工作区**、**左侧边栏历史对话**、**本地目录** 逐一隔离，绝不把无关文件混杂在同一视图。
   - 当未建立任何工作区/项目时，清晰标注 `项目: 0`，列表精确对齐左侧边栏各个独立对话标题（基于本地 `conversation_summaries.db` 与会话产物目录）。

2. **全自动发现与分类产出文件**
   - 自动解析当前及历史对话的 `transcript.jsonl`、会话 Artifact 目录以及 `我发送的文件`（只含附件本身）。
   - 按文档类型清晰归类（Word、Markdown、PPT、Excel、PDF、图片、文本/代码等），也可一键按修改时间排序或搜索筛选。

3. **默认侧边栏直开 + 内置阅读兜底**
   - 点击文件名即可在 Antigravity 右侧分栏（`fileView`）打开预览：
     - `.md`、纯文本、代码、图片：原文件直接预览；
     - `.docx` / `.pptx` / `.xlsx`：自动提取正文并生成只读 Markdown 镜像到 `<brain>/<conv_id>/fl_preview/` 后秒开，原文件零改动；
     - 当宿主右侧边栏分栏不可用时，自动回退至插件内置阅读器视图预览。

4. **多选「加入对话框」与跨对话引用（双向同步 + 一键补发气泡）**
   - 支持单选或批量勾选任意对话/目录下的文件，点击 **`加入对话框`**，自动通过 `OPEN_SIDECAR` 唤醒侧边栏，调用宿主 `addArtifactComment` 接口在聊天输入框上方生成原生的引用胶囊（`1 Comment` 气泡）。
   - **双向状态同步**：对话内嵌卡片（`file_capsules.html`）与右侧 `File Launcher` 面板之间实时同步已加入文件，任一端点击 `×` 或`清空`，另一端都会自动更新。
   - **一键补发与直接发送**：若气泡未显示或曾在输入框中手动删除，可点 **`🔄 补发气泡`** 重新注入；也可随时点 **`🚀 直接发给 AI`** 或 **`📋 复制引用`**。

5. **按后缀精准匹配「打开方式 ▾」**
   - **用电脑软件打开**：根据后缀自动匹配已安装的对应软件（如 `.docx` 匹配 Word / WPS，`.xlsx` 匹配 Excel / WPS，`.md` 匹配 Antigravity / VS Code / 记事本等）。
   - **Windows 原生弹窗**：支持直接呼出系统原生的“你要如何打开这个文件？”（`OpenAs_RunDLL`）以及 **`文件资源管理器`** 定位选中（`explorer.exe /select`）。
   - 支持在设置中添加自定义 `.exe` 路径及设置按后缀默认打开方式。

6. **⭐ 收藏（防上下文压缩） & 📦 归档备份**
   - **`★ 收藏(防压缩)`**：写入防压缩保护清单（同时备份至当前会话目录与 `Pinned_Protected_Files/PINNED_FILES_MANIFEST.md`），防止长对话压缩上下文后丢失关键参考路径。
   - **`📦 归档`**：一键复制备份文件到 `Archived_Docs` 目录（Windows 下存在 `D:\projects` 时存入 `D:\projects\Archived_Docs`，否则存入 `~/Documents/AntigravityFileLauncher/Archived_Docs`）。

---

## 📦 目录结构

```text
antigravity-file-launcher/
├── plugin.json                        # Antigravity 插件清单
├── README.md                          # 说明文档与限制说明
├── install.ps1                        # Windows 一键安装/覆盖脚本
├── .gitignore                         # 忽略 __pycache__、日志与系统缓存文件
├── assets/
│   └── logo.svg                       # 插件图标
├── rules/
│   └── AGENTS.md                      # 自动规则：汇报文档时嵌入极简卡片并在末尾附面板入口
├── skills/
│   └── file-launcher/
│       └── SKILL.md                   # 技能说明：侧边栏直开、项目隔离与收藏清单位置
└── sidecars/
    └── launcher_pane/
        ├── sidecar.json               # Sidecar 启动配置（默认运行 python main.py）
        ├── main.py                    # Python 本地后端与桥接服务（端口 18765 + Sidecar API）
        ├── preload.js                 # Antigravity Sidecar JS 桥接脚本
        ├── index.html                 # 面板前端页面
        ├── styles.css                 # 跟随宿主明暗主题的 Codex 风格样式
        ├── app.js                     # 面板前端状态管理、宿主通信与气泡注入逻辑
        ├── main.mjs                   # 早期 Node.js 兼容后端（备用）
        └── package.json               # Node 配置（备用）
```

---

## 🚀 安装与使用指南

### 前置环境
- **操作系统**：推荐 **Windows 10 / 11** + **Google Antigravity** 桌面端
- **运行时**：本机需安装 **Python 3.8+**，并确保终端中可直接执行 `python --version`

### 安装步骤

#### 方式 A：PowerShell 一键安装（推荐）
1. 通过 GitHub Desktop 或 `git clone` 将本仓库克隆到本地：
   ```bash
   git clone <你的仓库地址> antigravity-file-launcher
   cd antigravity-file-launcher
   ```
2. 执行安装脚本：
   ```powershell
   powershell -ExecutionPolicy Bypass -File .\install.ps1
   ```
   脚本会自动将插件文件安装/更新到 `%USERPROFILE%\.gemini\config\plugins\file-launcher`。

#### 方式 B：通过 Antigravity CLI 安装
```bash
agy plugin install .
```

### 日常使用说明
1. **在对话中打开面板**：点击 AI 回复末尾的 `[File Launcher]` 胶囊链接（`sidecar://file-launcher/launcher_pane/`），或在 Antigravity 右侧辅助栏打开 **File Launcher**。
2. **浏览与切换隔离范围**：点击面板顶部的范围选择器，可在「当前对话」「左侧边栏其他对话」「工作区项目」「本地目录」或「全部」之间自由切换。
3. **打开与预览**：点击文件名默认在右侧分栏预览；点击右侧 **`打开方式 ▾`** 可选用匹配桌面软件、系统默认软件、资源管理器定位或系统原生「选择打开方式...」。
4. **跨对话加入对话框**：
   - 点击对话内嵌极简卡片或右侧面板顶部的 **`选择`** 进入勾选模式；
   - 勾选文件后点击 **`加入对话框`**，输入框上方会自动出现引用胶囊，直接输入提问并发送即可；
   - 如气泡未出现或曾在输入框手动删除，可点击 **`🔄 补发气泡`** 重新写入。
5. **从源码更新插件后**：重新运行 `.\install.ps1` 并重开右侧 **File Launcher** 面板（必要时在任务管理器结束旧 `python main.py` 进程即可立即生效）。

### 自检与排错
在仓库目录下可随时运行离线自检，验证 Python 环境、对话目录识别及本机软件探测是否正常：
```powershell
python .\sidecars\launcher_pane\main.py --selftest
```

---

## ⚠️ 已知局限与宿主边界

使用与二次开发前，请了解以下由 Antigravity 宿主机制或平台特性决定的真实局限：

1. **输入框顶部 `Comment` 气泡无法跨端同步删除（核心宿主限制）**
   - Antigravity 宿主（前端内核 `quc`）目前仅向 Sidecar 暴露了单向的 `add-artifact-comment` 写入接口，**没有提供删除/清空评论气泡的接口**，用户在输入框上方点击气泡内删除图标时，也不会向插件或内嵌卡片发送任何回调通知。
   - **实际表现**：
     - 在插件面板或内嵌卡片中点击 `×` 或`清空`：会同步清除双端引用列表与上下文记录，但**不能自动消掉**输入框上方已生成的 `Comment` 气泡（需点击该气泡自身右上角/内部删除图标）。
     - 在输入框手动删掉气泡后：**不会自动同步**移除插件面板中的记录；如需恢复气泡，点击 **`🔄 补发气泡`** 即可重新写入。

2. **外部软件拉起与系统弹窗主要面向 Windows**
   - 原生“打开方式”系统弹窗（`rundll32 shell32.dll,OpenAs_RunDLL`）、文件资源管理器定位（`explorer.exe /select`）及本机常用软件路径探测均围绕 Windows 10/11 编写；macOS / Linux 环境目前未完整适配全部桌面打开动作。

3. **Office 文档侧边栏预览为只读 Markdown 镜像**
   - 由于 Antigravity 原生 `fileView` 不支持直接渲染二进制 `.docx` / `.pptx` / `.xlsx`，侧边栏预览仅提取文本与结构转为只读 `.md` 镜像；复杂排版、图表、公式或批注请通过`打开方式 ▾`用 Word / PowerPoint / Excel / WPS 查看原文件。

4. **内嵌卡片与本地桥接通信依赖端口 `18765`**
   - 聊天窗口内的 `<agent-embed>` 极简文件条默认通过本地回环接口 `http://127.0.0.1:18765` 与右侧 Python Sidecar 通信并轮询动作队列；若本机安全策略限制或端口被其他程序长期占用，内嵌卡片会自动降级，此时请直接点击底部的 `[File Launcher]` 链接在右侧主面板中操作。

5. **对齐左侧边栏名称依赖 Antigravity 本地元数据格式**
   - 对话隔离列表与项目名称通过读取本地 `~/.gemini/antigravity`（包括 `transcript.jsonl`、`conversation_summaries.db` 等）解析；如 Antigravity 客户端后续升级更改了本地数据库结构，可能需要同步更新 `main.py` 中的解析逻辑。

6. **聊天内嵌极简卡片依赖规则配合**
   - 聊天窗口里的 `<agent-embed>` 文件条是由 `rules/AGENTS.md` 引导 AI 在回复结束时生成在会话 Artifact 目录下的局部文档列表；对于插件安装前就已存在的历史对话卡片，请直接通过底部 `[File Launcher]` 入口使用全部最新功能。
