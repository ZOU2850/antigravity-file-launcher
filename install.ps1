$ErrorActionPreference = "Stop"

$SourceDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$TargetDir = Join-Path $env:USERPROFILE ".gemini\config\plugins\file-launcher"

Write-Host "Installing Antigravity File Launcher plugin to: $TargetDir" -ForegroundColor Cyan

if (Test-Path $TargetDir) {
    Remove-Item -Path $TargetDir -Recurse -Force
}

New-Item -ItemType Directory -Path $TargetDir -Force | Out-Null

$Items = @("plugin.json", "README.md", "assets", "rules", "skills", "sidecars")
foreach ($item in $Items) {
    $src = Join-Path $SourceDir $item
    if (Test-Path $src) {
        Copy-Item -Path $src -Destination $TargetDir -Recurse -Force
    }
}

Write-Host "Successfully installed File Launcher plugin!" -ForegroundColor Green
Write-Host "Manage it in Antigravity: customization://file-launcher" -ForegroundColor Yellow
Write-Host "Open panel in chat:       sidecar://file-launcher/launcher_pane/" -ForegroundColor Yellow
