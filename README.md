# Antigravity File Launcher (`file-launcher`)

**让 Google Antigravity 拥有像 Codex 桌面端一样的「文件结果点击即开 + 自由选择打开方式」体验。**

在 Antigravity 2.0 桌面端中，聊天窗口内的 `file:///` 链接默认倾向于打开内置文本预览，遇到 `.pptx`、`.pdf`、`.docx`、`.xlsx`、`.html` 等交付物时，无法直接拉起外部软件或选择打开方式。

`file-launcher` 是一个基于 Antigravity 原生 **UI Extension (Sidecar)** 机制构建的本地增强插件，在右侧辅助面板提供实时同步的**「文件直达面板」**。

---

## ✨ 核心特性

1. **全自动提取当前对话文件 (`当前对话产出`)**
   - 实时解析当前会话的 `transcript.jsonl` 与会话 Artifact 目录，自动汇总本轮**新建 (`write_file`)、修改 (`edit_file`)、结果链接 (`file:///`)、会话产物**，无需手动复制路径。
2. **自动扫描项目最新交付物 (`项目最新文件`)**
   - 默认自动监控 `D:\projects`（可在面板设置中自由增删监控目录），按修改时间倒序展示最近生成的 `.pptx`、`.pdf`、`.docx`、`.xlsx`、`.html`、`.md`、代码与图片文件。
3. **点击即开 + 完整的「选择打开方式」菜单**
   - **⚡ 默认打开**：点击文件名或「默认打开」按钮，直接调用系统关联程序秒开（如 `.pptx` 直接拉起 PowerPoint / WPS）。
   - **🛠 打开方式▾**：
     - **系统原生“打开方式”弹窗**：一键唤起 Windows 原生 `OpenAs_RunDLL`（“你要如何打开这个文件？”）系统对话框；
     - **自动探测本机常用软件**：自动识别本机已安装的 **Antigravity、VS Code、Cursor、WPS Office、PowerPoint、Excel、Word、Edge、Chrome、Notepad++、Typora、记事本、PowerShell** 等；
     - **自定义添加任意软件**：支持在设置中添加任意 `.exe` 路径；
     - **记住此后缀默认打开方式**：勾选后，以后直接点击同类后缀（如 `.pptx` 或 `.md`）自动使用你偏好的软件打开。
   - **📂 定位文件**：直接打开 Windows 资源管理器并高亮选中该文件（`explorer.exe /select,<path>`）。
   - **👁 内置预览 / 📋 复制路径 / ⭐ 收藏固定**。

---

## 📦 目录结构

```text
antigravity-file-launcher/
├── plugin.json                        # 插件清单
├── README.md                          # 说明文档
├── install.ps1                        # Windows 一键安装/更新脚本
├── assets/
│   └── logo.svg                       # 插件图标
├── rules/
│   └── AGENTS.md                      # 自动规则：产出文件时汇总链接并附上打开面板胶囊
├── skills/
│   └── file-launcher/
│       └── SKILL.md                   # 技能定义：支持通过 sidecar:// 链接一键呼出面板
└── sidecars/
    └── launcher_pane/
        ├── sidecar.json               # Sidecar UI 辅助面板配置
        ├── package.json               # ESM 模块配置
        ├── main.mjs                   # Node.js 本地后端（兼容 sidecar_sdk 与 --selftest 自检）
        ├── index.html                 # 面板前端视图
        ├── styles.css                 # 自适应宿主亮暗主题样式
        └── app.js                     # 前端交互逻辑
```

---

## 🚀 安装与使用

### 方法一：使用 PowerShell 脚本一键安装（Windows）

在仓库根目录下运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

脚本会将插件同步安装到 `~/.gemini/config/plugins/file-launcher`。

### 方法二：通过 Antigravity CLI 安装

```bash
agy plugin install .
```

### 在对话中唤起面板

- 安装并启用后，可在对话右上角辅助面板（Auxiliary Pane）切换到 **File Launcher**；
- 或在聊天中直接点击胶囊链接：`[File Launcher](sidecar://file-launcher/launcher_pane/)`。

### 命令行自检测试

```bash
node ./sidecars/launcher_pane/main.mjs --selftest
```
