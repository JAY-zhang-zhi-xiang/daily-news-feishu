param(
    [switch]$SkipNetwork,
    [switch]$SendFeishuProbe,
    [switch]$RequireGitClean
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $venvPython)) {
    throw "Python virtual environment not found: $venvPython"
}

if ($SkipNetwork -and $SendFeishuProbe) {
    throw "SendFeishuProbe cannot be used with SkipNetwork."
}

function Invoke-CheckedCommand {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath,
        [Parameter(ValueFromRemainingArguments = $true)]
        [string[]]$Arguments
    )

    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code $LASTEXITCODE`: $FilePath $($Arguments -join ' ')"
    }
}

function Test-PowerShellSyntax {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    [scriptblock]::Create((Get-Content -Raw $Path)) | Out-Null
}

function Test-GitMetadata {
    if (-not (Test-Path (Join-Path $projectRoot ".git"))) {
        return
    }

    & git -C $projectRoot rev-parse --is-inside-work-tree | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Git metadata is present but invalid. Reinitialize or restore the repository before release."
    }

    if ($RequireGitClean) {
        $gitStatus = & git -C $projectRoot status --porcelain --untracked-files=all
        if ($LASTEXITCODE -ne 0) {
            throw "Could not inspect Git working tree status."
        }
        if ($gitStatus) {
            $gitStatus
            throw "Git working tree is not clean. Commit or intentionally exclude changes before release."
        }
    }
}

function Test-LockedRequirementsInstalled {
    $lockPath = Join-Path $projectRoot "requirements.lock.txt"
    if (-not (Test-Path $lockPath)) {
        throw "Lock file not found: $lockPath"
    }

    $lockedRequirements = Get-Content $lockPath |
        Where-Object { $_.Trim() -and -not $_.Trim().StartsWith("#") } |
        ForEach-Object { $_.Trim().ToLowerInvariant() }

    if (-not $lockedRequirements) {
        throw "Lock file is empty: $lockPath"
    }

    $installed = & $venvPython -m pip freeze |
        ForEach-Object { $_.Trim().ToLowerInvariant() }
    if ($LASTEXITCODE -ne 0) {
        throw "Could not inspect installed Python packages."
    }

    $installedSet = @{}
    foreach ($package in $installed) {
        $installedSet[$package] = $true
    }

    $missing = @()
    foreach ($requirement in $lockedRequirements) {
        if (-not $installedSet.ContainsKey($requirement)) {
            $missing += $requirement
        }
    }

    if ($missing.Count -gt 0) {
        throw "Installed packages do not match requirements.lock.txt: $($missing -join ', ')"
    }
}

Push-Location $projectRoot
try {
    Test-GitMetadata
    Test-PowerShellSyntax "setup.ps1"
    Test-PowerShellSyntax "run_daily_news.ps1"
    Test-PowerShellSyntax "register_task.ps1"
    Test-PowerShellSyntax "check_release.ps1"
    Invoke-CheckedCommand $venvPython -m py_compile "src\main.py" "tests\test_main.py"
    Invoke-CheckedCommand $venvPython -m unittest discover -s tests
    Invoke-CheckedCommand $venvPython -m pip check
    Test-LockedRequirementsInstalled
    Invoke-CheckedCommand $venvPython "src\main.py" --check-config

    $secretPattern = "sk-[A-Za-z0-9]{20,}|open-apis/bot/v2/hook/[0-9a-fA-F-]{20,}|FEISHU_WEBHOOK_URL=https://open.feishu.cn/open-apis/bot/v2/hook/[0-9a-fA-F-]{20,}"
    $secretMatches = & rg --hidden -n `
        --glob "!.env" `
        --glob "!.env.local" `
        --glob "!.env.*.local" `
        --glob "!.git/**" `
        --glob "!.venv/**" `
        --glob "!**/__pycache__/**" `
        --glob "!*.pyc" `
        --glob "!*.log" `
        $secretPattern
    if ($LASTEXITCODE -eq 0) {
        $secretMatches
        throw "Sensitive value scan found possible committed secrets."
    }
    if ($LASTEXITCODE -ne 1) {
        throw "Sensitive value scan failed."
    }

    if (-not $SkipNetwork) {
        Invoke-CheckedCommand $venvPython "src\main.py" --check-feeds
        Invoke-CheckedCommand $venvPython "src\main.py" --check-deepseek
        if ($SendFeishuProbe) {
            Invoke-CheckedCommand $venvPython "src\main.py" --check-feishu
        }
        Invoke-CheckedCommand $venvPython "src\main.py" --dry-run
    }

    Write-Host "Release checks passed."
}
finally {
    Pop-Location
}
