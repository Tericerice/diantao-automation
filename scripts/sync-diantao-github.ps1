#requires -Version 7.0
<#
.SYNOPSIS
    把本地 diantao 仓库以"本地为准"同步到 GitHub（Tericerice/diantao-automation）。

.DESCRIPTION
    端对端同步机制的执行入口：任务结案 / 本地提交完成后运行本脚本，把本地分支推送到远程。

    行为：
      1. 读取远程分支当前哈希（ls-remote），再 fetch 到 FETCH_HEAD 以便计算提交范围。
      2. 计算本地领先 / 远程领先的提交数，并打印将要推送的提交列表。
      3. 若远程领先（历史分叉），默认拒绝推送；加 -AllowForce 时先自动创建并推送
         backup/remote-master-<时间戳> 备份分支，再用 --force-with-lease 强制推送。
         脚本从不删除任何远程分支。
      4. 推送后回读 ls-remote，校验远程哈希 == 本地 HEAD，不一致则报错退出。

    注意：本机全局 gitconfig 存在 url.https://github.com/.insteadof git@github.com: 改写，
    因此默认 RemoteUrl 必须使用 ssh:// 形式，避免被改写成 https 后触发无凭据交互提示。

.PARAMETER RepoPath
    仓库根目录，默认取当前目录所在 git 仓库。

.PARAMETER RemoteUrl
    推送目标，默认 ssh://git@github.com/Tericerice/diantao-automation.git。

.PARAMETER Branch
    要同步的本地分支，默认 master。

.PARAMETER DryRun
    只 fetch + 打印将要推送的提交范围与推送方式，不做任何写操作。

.PARAMETER AllowForce
    允许在远端历史分叉时强制推送（仍会先自动创建并推送备份分支）。

.PARAMETER Quiet
    静默模式（供 post-commit 钩子使用），只输出错误。

.EXAMPLE
    pwsh scripts/sync-diantao-github.ps1 -DryRun

.EXAMPLE
    pwsh scripts/sync-diantao-github.ps1

.EXAMPLE
    pwsh scripts/sync-diantao-github.ps1 -AllowForce

.NOTES
    退出码：0 = 已同步 / 已在同步状态；1 = 执行失败；2 = 历史分叉且未加 -AllowForce。
#>
[CmdletBinding()]
param(
    [string]$RepoPath = '',
    [string]$RemoteUrl = 'ssh://git@github.com/Tericerice/diantao-automation.git',
    [string]$Branch = 'master',
    [switch]$DryRun,
    [switch]$AllowForce,
    [switch]$Quiet
)

$ErrorActionPreference = 'Stop'

function Write-Sync([string]$Message) {
    if (-not $Quiet) { Write-Host "[sync] $Message" }
}

function Invoke-Git {
    param([string[]]$GitArgs)
    $output = & git @GitArgs 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw ("git " + ($GitArgs -join ' ') + " 失败:`n" + (($output | Out-String).Trim()))
    }
    return (($output | Out-String).Trim())
}

function Get-RemoteHead([string]$Url, [string]$Ref) {
    $raw = Invoke-Git @('ls-remote', $Url, "refs/heads/$Ref")
    if ([string]::IsNullOrWhiteSpace($raw)) { return '' }
    return ($raw -split "`n")[0].Trim().Split("`t")[0]
}

Push-Location
try {
    if (-not $RepoPath) {
        $RepoPath = Invoke-Git @('rev-parse', '--show-toplevel')
        if ([string]::IsNullOrWhiteSpace($RepoPath)) { throw '当前目录不是 git 仓库，请用 -RepoPath 指定。' }
    }
    Set-Location $RepoPath

    # 非交互：缺少凭据时快速失败，而不是等待人工输入。
    $env:GIT_SSH_COMMAND = 'ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new'
    $env:GIT_TERMINAL_PROMPT = '0'

    $localHead = Invoke-Git @('rev-parse', $Branch)
    Write-Sync "仓库: $RepoPath"
    Write-Sync "本地 ${Branch}: $localHead"
    Write-Sync "远程: $RemoteUrl"

    $remoteHead = Get-RemoteHead $RemoteUrl $Branch
    if (-not $remoteHead) {
        Write-Sync "远程分支 refs/heads/$Branch 不存在，将作为新分支推送。"
        $remoteOnly = 0
        $localOnly = 0
    }
    else {
        Write-Sync "远程 ${Branch}: $remoteHead"
        Invoke-Git @('fetch', '--quiet', '--no-tags', $RemoteUrl, "refs/heads/$Branch") | Out-Null
        $fetchedHead = Invoke-Git @('rev-parse', 'FETCH_HEAD')
        if ($fetchedHead -ne $remoteHead) {
            throw "fetch 后 FETCH_HEAD($fetchedHead) 与 ls-remote($remoteHead) 不一致，可能有并发推送，请重试。"
        }

        $countParts = (Invoke-Git @('rev-list', '--left-right', '--count', "$Branch...FETCH_HEAD")) -split '[^0-9]+' | Where-Object { $_ -ne '' }
        $localOnly = [int]$countParts[0]
        $remoteOnly = [int]$countParts[1]
    }

    if ($localOnly -eq 0 -and $remoteOnly -eq 0) {
        Write-Sync "本地与远程已一致，无需推送。"
        exit 0
    }
    if ($localOnly -eq 0 -and $remoteOnly -gt 0) {
        Write-Sync "本地落后远程 $remoteOnly 个提交，本地无新提交；本脚本不会回退远程。"
        exit 0
    }

    Write-Sync "本地领先 $localOnly 个提交，远程领先 $remoteOnly 个提交。"
    Write-Sync "将要推送的提交（FETCH_HEAD..$Branch）："
    $range = Invoke-Git @('log', '--oneline', '--no-decorate', "FETCH_HEAD..$Branch")
    if (-not $Quiet) { Write-Host $range }

    $diverged = ($remoteOnly -gt 0)
    if ($diverged) {
        if (-not $AllowForce) {
            Write-Sync "远程历史与本地分叉；如确认以本地为准，请加 -AllowForce（脚本会先备份远程历史）。"
            exit 2
        }
        $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
        $backupRef = "backup/remote-master-$stamp"
        Write-Sync "分叉模式：将先把远程 $Branch 备份为 $backupRef"
        if ($DryRun) {
            Write-Sync "[dry-run] 将创建备份分支 $backupRef -> $remoteHead 并推送"
            Write-Sync "[dry-run] 将执行强制推送 $Branch -> $localHead（--force-with-lease）"
            exit 0
        }
        Invoke-Git @('branch', '-f', $backupRef, $remoteHead) | Out-Null
        Invoke-Git @('push', $RemoteUrl, "refs/heads/$backupRef:refs/heads/$backupRef") | Out-Null
        $backupRemote = Get-RemoteHead $RemoteUrl $backupRef
        if ($backupRemote -ne $remoteHead) {
            throw "备份分支推送校验失败：远程 $backupRef=$backupRemote，期望 $remoteHead；已中止，未改动 $Branch。"
        }
        Write-Sync "备份完成：$backupRef = $remoteHead"
    }

    if ($DryRun) {
        $mode = '快进推送'
        if ($diverged) { $mode = '强制推送（已备份远程历史）' }
        Write-Sync "[dry-run] 将执行$mode $Branch -> $localHead"
        exit 0
    }

    if ($diverged) {
        Invoke-Git @('push', $RemoteUrl, "refs/heads/$Branch:refs/heads/$Branch", "--force-with-lease=refs/heads/${Branch}:$remoteHead") | Out-Null
    }
    else {
        Invoke-Git @('push', $RemoteUrl, "refs/heads/$Branch:refs/heads/$Branch") | Out-Null
    }

    $verified = Get-RemoteHead $RemoteUrl $Branch
    if ($verified -ne $localHead) {
        throw "推送后校验失败：远程 $Branch=$verified，本地 HEAD=$localHead。"
    }
    Write-Sync "推送完成并已回读校验：远程 $Branch = $verified"
    exit 0
}
finally {
    Pop-Location
}
