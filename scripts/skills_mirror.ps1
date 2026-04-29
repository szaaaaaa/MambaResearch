<#
.SYNOPSIS
    把 Claude Code 与 Codex CLI 的 skills 目录做成"双向 mirror"：单一物理源 + 两侧 NTFS junction。

.DESCRIPTION
    问题：Claude Code 默认从 `~/.claude/skills/<name>/SKILL.md` 加载 skill，Codex CLI 从
    `~/.codex/skills/<name>/SKILL.md` 加载。两条路径独立，导致同一个 skill 要写两份。

    解决：把物理文件搬到中立位置（全局 = `~/skills-shared/`，项目 = `<repo>/.skills-shared/`），
    两侧入口都做成 NTFS junction 指向同一物理目录。任何一侧创建 / 修改 skill，落盘都到 shared，
    另一侧立刻可见——真正的双向自动同步，零守护进程。

    本脚本是幂等的：重复跑只补差异（缺 junction 补 junction、未迁移目录搬过去），
    已迁移完成的 skill 完全不动。首次跑会自动备份。

.PARAMETER Scope
    global  — 处理 ~/.claude/skills/ ↔ ~/.codex/skills/
    project — 处理 <CWD>/.claude/skills/ ↔ <CWD>/.codex/skills/
    all     — 两者都跑

.PARAMETER DryRun
    只打印将要执行的操作，不真改文件系统。

.PARAMETER NoBackup
    跳过首次迁移前的备份（不推荐——除非你确认 shared 目录已建好）。

.EXAMPLE
    .\scripts\skills_mirror.ps1 -Scope all -DryRun
    .\scripts\skills_mirror.ps1 -Scope global
    .\scripts\skills_mirror.ps1 -Scope project

.NOTES
    NTFS junction 删除必须用 `cmd /c rmdir` 或 `[IO.Directory]::Delete($p, $false)`，
    绝对不能用 `Remove-Item -Recurse`——后者会递归删进 junction 的目标真目录，导致数据丢失。
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)]
    [ValidateSet('global', 'project', 'all')]
    [string]$Scope,

    [switch]$DryRun,

    [switch]$NoBackup
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

# ---------- 路径常量（由 -Scope 决定生效组）----------

function Get-ScopeRoots {
    param([string]$ScopeName)

    switch ($ScopeName) {
        'global' {
            @{
                Name        = 'global'
                ClaudeDir   = Join-Path $env:USERPROFILE '.claude\skills'
                CodexDir    = Join-Path $env:USERPROFILE '.codex\skills'
                SharedDir   = Join-Path $env:USERPROFILE 'skills-shared'
                ReservedNames = @('.system')  # Codex 内置位，永不动
            }
        }
        'project' {
            $repo = (Get-Location).Path
            @{
                Name        = 'project'
                ClaudeDir   = Join-Path $repo '.claude\skills'
                CodexDir    = Join-Path $repo '.codex\skills'
                SharedDir   = Join-Path $repo '.skills-shared'
                ReservedNames = @()
            }
        }
    }
}

# ---------- junction 检测 / 创建 / 安全删除 ----------

function Test-IsJunction {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { return $false }
    $item = Get-Item -LiteralPath $Path -Force
    # NTFS junction 在 PS 5.1 / 7 上 LinkType = 'Junction'
    return $item.LinkType -eq 'Junction'
}

function Get-JunctionTarget {
    param([string]$Path)
    if (-not (Test-IsJunction $Path)) { return $null }
    return (Get-Item -LiteralPath $Path -Force).Target | Select-Object -First 1
}

function Remove-JunctionSafe {
    param(
        [string]$Path,
        [switch]$DryRun
    )
    if (-not (Test-Path -LiteralPath $Path)) { return }
    if (-not (Test-IsJunction $Path)) {
        throw "Refuse to Remove-JunctionSafe '$Path' — not a junction (would risk real-data deletion)."
    }
    if ($DryRun) {
        Write-Host "  [dry-run] rmdir junction: $Path" -ForegroundColor DarkGray
        return
    }
    # `cmd /c rmdir` 是 junction-safe，只解除 link，不递归到 target
    $result = & cmd /c rmdir """$Path""" 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "rmdir failed for '$Path': $result"
    }
}

function New-JunctionLink {
    param(
        [string]$LinkPath,
        [string]$TargetPath,
        [switch]$DryRun
    )
    if ($DryRun) {
        Write-Host "  [dry-run] junction: $LinkPath → $TargetPath" -ForegroundColor DarkGray
        return
    }
    $parent = Split-Path -Parent $LinkPath
    if (-not (Test-Path -LiteralPath $parent)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    New-Item -ItemType Junction -Path $LinkPath -Target $TargetPath | Out-Null
}

# ---------- 备份（仅在首次手术时做一次）----------

function Backup-Once {
    param(
        [string]$ClaudeDir,
        [string]$CodexDir,
        [switch]$DryRun
    )
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $targets = @()
    foreach ($dir in @($ClaudeDir, $CodexDir)) {
        if (Test-Path -LiteralPath $dir) {
            $bak = "$dir.bak.$stamp"
            $targets += [PSCustomObject]@{ Src = $dir; Dst = $bak }
        }
    }
    if (-not $targets) { return }
    foreach ($t in $targets) {
        if ($DryRun) {
            Write-Host "  [dry-run] backup: $($t.Src) → $($t.Dst)" -ForegroundColor DarkGray
        } else {
            # 用 robocopy 处理含 junction 的源目录：/XJ 跳过 junction 不递归进去
            # /MIR 镜像、/NJH /NJS /NFL /NDL 静默
            $null = & robocopy $t.Src $t.Dst /MIR /XJ /NJH /NJS /NFL /NDL /NP 2>&1
            # robocopy exit code 0-7 都算成功（>=8 才是错误）
            if ($LASTEXITCODE -ge 8) {
                throw "robocopy backup failed: $($t.Src) → $($t.Dst) (exit=$LASTEXITCODE)"
            }
            $LASTEXITCODE = 0  # 重置以免污染后续判断
            Write-Host "  ✓ backed up: $($t.Dst)" -ForegroundColor DarkGreen
        }
    }
}

# ---------- 单 skill 状态机：决定该 skill 当前处于哪种状态 + 该做什么 ----------
#
# 状态枚举（per skill name）：
#   migrated        — shared 存在，两侧都是 junction 指向 shared。无操作。
#   need-link-claude — shared 存在，Claude 侧缺 junction。补 junction。
#   need-link-codex  — shared 存在，Codex 侧缺 junction。补 junction。
#   need-link-both   — shared 存在，两侧都缺。补两条 junction。
#   migrate-claude   — shared 不存在；Claude 侧是真目录（Codex 侧无所谓）。
#                      搬 Claude 真目录 → shared，建两侧 junction。
#                      Codex 侧若是真目录（content drift），冲突报错让用户决定。
#   migrate-codex    — shared 不存在；Claude 侧无；Codex 侧是真目录。
#                      搬 Codex 真目录 → shared，建两侧 junction。
#   conflict         — 两侧都是真目录且 content 不一致。停下让用户决定。
#   unknown          — 两侧都不存在该 skill 名。脚本不应该看到这种状态。
#
function Get-SkillState {
    param(
        [string]$SkillName,
        [string]$ClaudeDir,
        [string]$CodexDir,
        [string]$SharedDir
    )
    $cl = Join-Path $ClaudeDir $SkillName
    $cx = Join-Path $CodexDir $SkillName
    $sh = Join-Path $SharedDir $SkillName

    $clExists = Test-Path -LiteralPath $cl
    $cxExists = Test-Path -LiteralPath $cx
    $shExists = Test-Path -LiteralPath $sh

    $clIsJunction = $clExists -and (Test-IsJunction $cl)
    $cxIsJunction = $cxExists -and (Test-IsJunction $cx)
    $clIsRealDir  = $clExists -and -not $clIsJunction
    $cxIsRealDir  = $cxExists -and -not $cxIsJunction

    $state = [PSCustomObject]@{
        Name           = $SkillName
        ClaudePath     = $cl
        CodexPath      = $cx
        SharedPath     = $sh
        ClaudeExists   = $clExists
        CodexExists    = $cxExists
        SharedExists   = $shExists
        ClaudeIsJunction = $clIsJunction
        CodexIsJunction  = $cxIsJunction
        ClaudeIsRealDir  = $clIsRealDir
        CodexIsRealDir   = $cxIsRealDir
        Verdict        = 'unknown'
    }

    if ($shExists) {
        # 已迁移路径：检查两侧 junction 是否对齐
        $clOk = $clIsJunction -and ((Get-JunctionTarget $cl) -eq $sh)
        $cxOk = $cxIsJunction -and ((Get-JunctionTarget $cx) -eq $sh)
        if ($clOk -and $cxOk) { $state.Verdict = 'migrated' }
        elseif (-not $clOk -and -not $cxOk) { $state.Verdict = 'need-link-both' }
        elseif (-not $clOk) { $state.Verdict = 'need-link-claude' }
        else { $state.Verdict = 'need-link-codex' }
        return $state
    }

    # shared 不存在：根据两侧真目录情况判定
    if ($clIsRealDir -and $cxIsRealDir) {
        # 双方都有真目录 — 检查内容是否一致决定 conflict 还是 migrate-claude
        $clHash = Get-DirHash $cl
        $cxHash = Get-DirHash $cx
        if ($clHash -eq $cxHash) {
            $state.Verdict = 'migrate-claude'  # 两边一样，以 Claude 为源
        } else {
            $state.Verdict = 'conflict'
        }
    } elseif ($clIsRealDir) {
        $state.Verdict = 'migrate-claude'
    } elseif ($cxIsRealDir) {
        $state.Verdict = 'migrate-codex'
    } elseif ($clIsJunction -or $cxIsJunction) {
        # 有 junction 但 shared 不存在 — broken link，归 conflict 让用户处理
        $state.Verdict = 'conflict'
    }

    return $state
}

# ---------- 简易"目录内容指纹"（用于 conflict 判定）----------
#
# 仅比较 SKILL.md 这一份关键文件的 hash；其他文件 drift 不视为冲突
# （pipeline skill 大量 README / 子文件，全 hash 太敏感会误报）。
function Get-DirHash {
    param([string]$Dir)
    $skillMd = Join-Path $Dir 'SKILL.md'
    if (-not (Test-Path -LiteralPath $skillMd)) { return '' }
    return (Get-FileHash -LiteralPath $skillMd -Algorithm SHA256).Hash
}

# ---------- skill 名收集 + 处理主循环 ----------

function Get-AllSkillNames {
    param(
        [string]$ClaudeDir,
        [string]$CodexDir,
        [string]$SharedDir,
        [string[]]$ReservedNames
    )
    $names = New-Object System.Collections.Generic.HashSet[string]
    foreach ($d in @($ClaudeDir, $CodexDir, $SharedDir)) {
        if (Test-Path -LiteralPath $d) {
            Get-ChildItem -LiteralPath $d -Directory -Force | ForEach-Object {
                if ($_.Name -in $ReservedNames) { return }
                [void]$names.Add($_.Name)
            }
        }
    }
    return $names | Sort-Object
}

function Invoke-SkillAction {
    param(
        $State,
        [switch]$DryRun
    )
    switch ($State.Verdict) {
        'migrated' {
            Write-Host "  • $($State.Name): already mirrored, skip" -ForegroundColor DarkGray
        }
        'need-link-claude' {
            Write-Host "  • $($State.Name): claude-side junction missing, fixing" -ForegroundColor Yellow
            if ($State.ClaudeExists) { Remove-JunctionSafe -Path $State.ClaudePath -DryRun:$DryRun }
            New-JunctionLink -LinkPath $State.ClaudePath -TargetPath $State.SharedPath -DryRun:$DryRun
        }
        'need-link-codex' {
            Write-Host "  • $($State.Name): codex-side junction missing, fixing" -ForegroundColor Yellow
            if ($State.CodexExists) { Remove-JunctionSafe -Path $State.CodexPath -DryRun:$DryRun }
            New-JunctionLink -LinkPath $State.CodexPath -TargetPath $State.SharedPath -DryRun:$DryRun
        }
        'need-link-both' {
            Write-Host "  • $($State.Name): both junctions missing, fixing" -ForegroundColor Yellow
            if ($State.ClaudeExists) { Remove-JunctionSafe -Path $State.ClaudePath -DryRun:$DryRun }
            if ($State.CodexExists)  { Remove-JunctionSafe -Path $State.CodexPath  -DryRun:$DryRun }
            New-JunctionLink -LinkPath $State.ClaudePath -TargetPath $State.SharedPath -DryRun:$DryRun
            New-JunctionLink -LinkPath $State.CodexPath  -TargetPath $State.SharedPath -DryRun:$DryRun
        }
        'migrate-claude' {
            Write-Host "  • $($State.Name): migrating from claude-side real dir" -ForegroundColor Cyan
            Move-RealDirToShared -Source $State.ClaudePath -Shared $State.SharedPath -DryRun:$DryRun
            # Codex 侧若也是真目录（且 content 一致），删除真目录后建 junction
            if ($State.CodexIsRealDir) {
                if ($DryRun) {
                    Write-Host "  [dry-run] remove duplicate codex real dir: $($State.CodexPath)" -ForegroundColor DarkGray
                } else {
                    Remove-Item -LiteralPath $State.CodexPath -Recurse -Force
                }
            } elseif ($State.CodexIsJunction) {
                Remove-JunctionSafe -Path $State.CodexPath -DryRun:$DryRun
            }
            New-JunctionLink -LinkPath $State.ClaudePath -TargetPath $State.SharedPath -DryRun:$DryRun
            New-JunctionLink -LinkPath $State.CodexPath  -TargetPath $State.SharedPath -DryRun:$DryRun
        }
        'migrate-codex' {
            Write-Host "  • $($State.Name): migrating from codex-side real dir" -ForegroundColor Cyan
            Move-RealDirToShared -Source $State.CodexPath -Shared $State.SharedPath -DryRun:$DryRun
            New-JunctionLink -LinkPath $State.ClaudePath -TargetPath $State.SharedPath -DryRun:$DryRun
            New-JunctionLink -LinkPath $State.CodexPath  -TargetPath $State.SharedPath -DryRun:$DryRun
        }
        'conflict' {
            Write-Host "  ✗ $($State.Name): CONFLICT — needs manual resolution" -ForegroundColor Red
            Write-Host "      claude=$($State.ClaudePath) (real=$($State.ClaudeIsRealDir), junction=$($State.ClaudeIsJunction))" -ForegroundColor Red
            Write-Host "      codex=$($State.CodexPath) (real=$($State.CodexIsRealDir), junction=$($State.CodexIsJunction))" -ForegroundColor Red
            Write-Host "      shared=$($State.SharedPath) (exists=$($State.SharedExists))" -ForegroundColor Red
            Write-Host "      action: 手动决定保留哪边版本，把它移到 shared，再重跑本脚本" -ForegroundColor Red
            $script:HadConflict = $true
        }
        default {
            Write-Host "  ? $($State.Name): unhandled state '$($State.Verdict)'" -ForegroundColor Magenta
        }
    }
}

function Move-RealDirToShared {
    param(
        [string]$Source,
        [string]$Shared,
        [switch]$DryRun
    )
    if ($DryRun) {
        Write-Host "  [dry-run] move: $Source → $Shared" -ForegroundColor DarkGray
        return
    }
    $sharedParent = Split-Path -Parent $Shared
    if (-not (Test-Path -LiteralPath $sharedParent)) {
        New-Item -ItemType Directory -Path $sharedParent -Force | Out-Null
    }
    Move-Item -LiteralPath $Source -Destination $Shared
}

# ---------- 主流程 ----------

function Invoke-MirrorScope {
    param(
        [string]$ScopeName,
        [switch]$DryRun,
        [switch]$NoBackup
    )
    $roots = Get-ScopeRoots -ScopeName $ScopeName

    Write-Host ""
    Write-Host "==[ scope: $($roots.Name) ]=="
    Write-Host "  claude:  $($roots.ClaudeDir)"
    Write-Host "  codex:   $($roots.CodexDir)"
    Write-Host "  shared:  $($roots.SharedDir)"
    if ($DryRun) { Write-Host "  mode:    DRY-RUN (no changes will be made)" -ForegroundColor Yellow }

    $names = Get-AllSkillNames -ClaudeDir $roots.ClaudeDir -CodexDir $roots.CodexDir `
                                -SharedDir $roots.SharedDir -ReservedNames $roots.ReservedNames
    if (-not $names) {
        Write-Host "  (no skills found in this scope)" -ForegroundColor DarkGray
        return
    }

    # 判断是否需要首次备份：shared 不存在 + 至少一个 skill 处于 migrate-* 状态
    $states = $names | ForEach-Object {
        Get-SkillState -SkillName $_ -ClaudeDir $roots.ClaudeDir `
                       -CodexDir $roots.CodexDir -SharedDir $roots.SharedDir
    }

    $needsMigration = $states | Where-Object { $_.Verdict -in @('migrate-claude', 'migrate-codex') }
    if ($needsMigration -and -not $NoBackup) {
        Write-Host "  → first-time migration detected, taking backup..." -ForegroundColor Cyan
        Backup-Once -ClaudeDir $roots.ClaudeDir -CodexDir $roots.CodexDir -DryRun:$DryRun
    }

    foreach ($s in $states) {
        Invoke-SkillAction -State $s -DryRun:$DryRun
    }
}

# ---------- 入口 ----------

$script:HadConflict = $false

if ($Scope -in @('global', 'all')) {
    Invoke-MirrorScope -ScopeName 'global' -DryRun:$DryRun -NoBackup:$NoBackup
}
if ($Scope -in @('project', 'all')) {
    Invoke-MirrorScope -ScopeName 'project' -DryRun:$DryRun -NoBackup:$NoBackup
}

Write-Host ""
if ($script:HadConflict) {
    Write-Host "⚠ One or more skills had CONFLICTS — see above. Resolve manually then re-run." -ForegroundColor Red
    exit 2
} else {
    if ($DryRun) {
        Write-Host "✓ Dry-run complete. Re-run without -DryRun to apply." -ForegroundColor Green
    } else {
        Write-Host "✓ Mirror state reconciled." -ForegroundColor Green
    }
    exit 0
}
