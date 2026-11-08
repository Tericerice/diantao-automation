# diantao GitHub 端对端同步机制

> 目标仓库：`github.com/Tericerice/diantao-automation`
> 同步方向：**以本地为准**（本地 `master` 为准，必要时强制覆盖远程 `master`，远程历史先备份）
> 建立日期：2026-11-08（Trail e-diantao-164）

## 1. 当前状态（2026-11-08）

| 项目 | 值 |
| --- | --- |
| 本地仓库 | `C:/My Github Program/diantao` |
| 本地分支 | `master` |
| 首次强制同步 HEAD | `0809fea27916179da3cb1b70bf3edd0295e7e983`（之后的本地新提交由同步脚本继续推送） |
| 远程备份分支 | `backup/remote-master-20261108`（= 覆盖前的远程 master `e6a90d9`） |
| 推送通道 | SSH key（`ssh://git@github.com/...`），本机全局 `gh` 未登录 |

首次同步时远程 `master` 比本地多 32 个提交（v0.2.x–v0.3.x 发布、更新器等历史）。
这些提交已原样保存在 `backup/remote-master-20261108` 分支中，可随时回滚，未删除任何分支。

## 2. 同步机制

- **执行入口**：`scripts/sync-diantao-github.ps1`
- **触发时机（默认手动）**：任务结案（Worker 输出 `[MCC-ARCHIVE #N]` READY）或本地提交完成后，
  由 **主控 / 用户 / 结案执行者**显式运行同步脚本。Tear Loop 的 `worker-finish` 属于 Tear 仓库，
  本任务不修改它；结案时在 diantao 仓运行本脚本即为闭环。
- **可选自动钩子**：`pwsh scripts/install-github-sync-hook.ps1` 安装 `.git/hooks/post-commit`，
  每次本地提交后静默同步。钩子不强制推送，分叉时跳过并写 `.git/github-sync.log`。
  卸载：`pwsh scripts/install-github-sync-hook.ps1 -Uninstall`；临时停用：创建 `.git/github-sync.disabled`。

### 常用命令

```powershell
# 1) 预演：只 fetch 并打印将要推送的提交范围（验收标准之一）
pwsh scripts/sync-diantao-github.ps1 -DryRun

# 2) 正常同步（快进推送）
pwsh scripts/sync-diantao-github.ps1

# 3) 历史分叉时以本地为准（先自动备份远程 master，再 --force-with-lease 推送）
pwsh scripts/sync-diantao-github.ps1 -AllowForce

# 4) 回读校验
git ls-remote ssh://git@github.com/Tericerice/diantao-automation.git refs/heads/master
```

退出码：`0` 已同步/无需同步；`1` 失败；`2` 历史分叉且未加 `-AllowForce`（未做任何写操作）。

### 脚本安全边界

1. 推送前先用 `ls-remote` + `fetch` 计算提交范围，并打印 `FETCH_HEAD..master` 的提交列表。
2. 历史分叉时必须显式 `-AllowForce`；强制推送前自动创建并推送
   `backup/remote-master-<yyyyMMdd-HHmmss>`，校验备份哈希后才继续。
3. 强制推送使用 `--force-with-lease`，远端在此期间被他人推送时自动中止。
4. 只新增备份分支，**从不删除**任何远程分支、标签或历史。
5. 推送后回读 `ls-remote`，远程哈希必须等于本地 HEAD，否则报错退出。

## 3. 凭据与已知坑

- 本机 `gh` 未登录，HTTPS 推送无凭据；本机 SSH key 已作为 `Tericerice` 通过 GitHub 认证。
- 本机全局 gitconfig 有 `url.https://github.com/.insteadof git@github.com:` 改写，
  直接写 `git@github.com:` 会被改写成 HTTPS 并触发交互式用户名提示。
  因此脚本默认使用 `ssh://git@github.com/Tericerice/diantao-automation.git`，
  该形式不匹配改写前缀，可直接走 SSH。
- 脚本内设置 `GIT_TERMINAL_PROMPT=0` 与 `ssh -o BatchMode=yes`，缺凭据时快速失败而不是卡住。

## 4. 回退方案

```powershell
# 把远程 master 复位到备份分支（覆盖前历史）
git push ssh://git@github.com/Tericerice/diantao-automation.git `
  refs/heads/backup/remote-master-20261108:refs/heads/master --force

# 或恢复某个更早的备份：先 ls-remote 列出 backup/* 分支
git ls-remote ssh://git@github.com/Tericerice/diantao-automation.git 'refs/heads/backup/*'
```

回退本身同样是强制推送，属于高风险操作，执行前请确认目标哈希。
