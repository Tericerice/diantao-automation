#requires -Version 7.0
<#
.SYNOPSIS
    安装/卸载 diantao 仓库的可选 post-commit 自动同步钩子。

.DESCRIPTION
    默认同步方式是"手动脚本"：任务结案或本地提交后显式运行
    scripts/sync-diantao-github.ps1。

    本脚本提供一个可选增强：安装 .git/hooks/post-commit，在每次本地提交后
    自动调用同步脚本（静默模式，不阻塞提交、失败只写日志）。
    钩子默认不做强制推送：历史分叉时同步脚本会以退出码 2 跳过，需人工确认后
    带 -AllowForce 运行。

    可用 `.git/github-sync.disabled` 文件临时停用钩子（删除该文件即恢复）。

.PARAMETER RepoPath
    仓库根目录，默认取当前目录所在 git 仓库。

.PARAMETER Uninstall
    卸载钩子（删除 .git/hooks/post-commit，不删除日志）。

.EXAMPLE
    pwsh scripts/install-github-sync-hook.ps1

.EXAMPLE
    pwsh scripts/install-github-sync-hook.ps1 -Uninstall
#>
[CmdletBinding()]
param(
    [string]$RepoPath = '',
    [switch]$Uninstall
)

$ErrorActionPreference = 'Stop'

function Invoke-Git {
    param([string[]]$GitArgs)
    $output = & git @GitArgs 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw ("git " + ($GitArgs -join ' ') + " 失败:`n" + (($output | Out-String).Trim()))
    }
    return (($output | Out-String).Trim())
}

Push-Location
try {
    if (-not $RepoPath) { $RepoPath = Invoke-Git @('rev-parse', '--show-toplevel') }
    Set-Location $RepoPath

    $hookPath = Join-Path $RepoPath '.git/hooks/post-commit'

    if ($Uninstall) {
        if (Test-Path $hookPath) { Remove-Item $hookPath -Force; Write-Host "[hook] 已卸载 $hookPath" }
        else { Write-Host "[hook] 未安装，无需卸载。" }
        exit 0
    }

    $hookContent = @'
#!/bin/sh
# diantao GitHub auto-sync hook (optional)
# 由 scripts/install-github-sync-hook.ps1 安装；删除本文件即卸载。
# 不阻塞提交：任何失败都只写入 .git/github-sync.log 并返回 0。
repo_root=$(git rev-parse --show-toplevel 2>/dev/null) || exit 0
[ -f "$repo_root/.git/github-sync.disabled" ] && exit 0
script="$repo_root/scripts/sync-diantao-github.ps1"
[ -f "$script" ] || exit 0
log="$repo_root/.git/github-sync.log"
pwsh -NoProfile -File "$script" -Quiet >>"$log" 2>&1
exit 0
'@

    New-Item -ItemType Directory -Force (Split-Path $hookPath) | Out-Null
    Set-Content -Path $hookPath -Value $hookContent -Encoding utf8NoBOM -NoNewline
    Write-Host "[hook] 已安装 $hookPath"

    # Git for Windows 通过 msys 执行钩子，补齐可执行位。
    $bash = Get-Command bash -ErrorAction SilentlyContinue
    if ($bash) {
        & bash -c "chmod +x '$hookPath'" 2>$null
    }

    Write-Host "[hook] 停用方式：New-Item -ItemType File .git/github-sync.disabled"
    Write-Host "[hook] 注意：钩子不会强制推送；历史分叉时请人工运行同步脚本 -AllowForce。"
    exit 0
}
finally {
    Pop-Location
}
