$ErrorActionPreference = "Stop"

$SourceDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$TargetDir = Join-Path $env:USERPROFILE ".gemini\config\plugins\file-launcher"

Write-Host "Installing Antigravity File Launcher plugin (v2.4.1) to: $TargetDir" -ForegroundColor Cyan

if (-not (Test-Path $TargetDir)) {
    New-Item -ItemType Directory -Path $TargetDir -Force | Out-Null
}

# 直接覆盖同步文件：即使 Antigravity 当前正在运行 Sidecar 占用目录句柄也能安全更新全部文件
$Items = @("plugin.json", "README.md", "CHANGELOG.md", "assets", "rules", "skills", "sidecars")
foreach ($item in $Items) {
    $src = Join-Path $SourceDir $item
    if (Test-Path $src) {
        Copy-Item -Path $src -Destination $TargetDir -Recurse -Force
    }
}

Write-Host "Successfully installed File Launcher v2.4.1!" -ForegroundColor Green
Write-Host "If Antigravity is currently running, disable/re-enable the plugin or restart Antigravity to load the new backend." -ForegroundColor DarkGray
Write-Host "Manage it in Antigravity: customization://file-launcher" -ForegroundColor Yellow
Write-Host "Open panel in chat:       sidecar://file-launcher/launcher_pane/" -ForegroundColor Yellow
