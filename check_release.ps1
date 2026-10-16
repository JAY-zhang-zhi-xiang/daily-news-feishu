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

function Get-SecretScanExclusions {
    return @(
        ".env", ".env.local", ".env.*.local",
        ".git", ".venv", "data",
        "__pycache__", "*.pyc", "*.log"
    )
}

function Invoke-RipgrepSecretScan {
    param([string]$Pattern)

    if (-not (Get-Command rg -ErrorAction SilentlyContinue)) {
        return $null
    }

    $rgArgs = @("--hidden", "-n")
    foreach ($glob in (Get-SecretScanExclusions)) {
        $rgArgs += "--glob"
        $rgArgs += "!$glob"
    }
    $rgArgs += $Pattern

    $matches = & rg @rgArgs
    $exitCode = $LASTEXITCODE
    if ($exitCode -eq 0) {
        return @($matches)
    }
    if ($exitCode -eq 1) {
        return @()
    }
    throw "Sensitive value scan failed (rg exited with code $exitCode)."
}

function Invoke-NativeSecretScan {
    param([string]$Pattern)

    # Fallback when ripgrep is not installed: scan tracked project files with
    # PowerShell's own regex engine so the release check still completes.
    $excludedDirs = @(".git", ".venv", "data", "__pycache__")
    $excludedFiles = @(".env", ".env.local")
    $excludedExtensions = @(".pyc", ".log")

    $files = Get-ChildItem -Path $script:projectRoot -Recurse -File -ErrorAction SilentlyContinue |
        Where-Object {
            $relative = $_.FullName.Substring($script:projectRoot.Length).TrimStart('\', '/')
            $segments = $relative -split '[\\/]'
            $inExcludedDir = $false
            foreach ($segment in $segments) {
                if ($excludedDirs -contains $segment) { $inExcludedDir = $true; break }
            }
            if ($inExcludedDir) { return $false }
            if ($excludedFiles -contains $_.Name) { return $false }
            if ($excludedExtensions -contains $_.Extension) { return $false }
            return $true
        }

    $hits = @()
    foreach ($file in $files) {
        $lineNumber = 0
        foreach ($line in (Get-Content -LiteralPath $file.FullName -ErrorAction SilentlyContinue)) {
            $lineNumber++
            if ($line -match $Pattern) {
                $relative = $file.FullName.Substring($script:projectRoot.Length).TrimStart('\', '/')
                $hits += "${relative}:${lineNumber}:$line"
            }
        }
    }
    return $hits
}

function Find-CommittedSecrets {
    param([string]$Pattern)

    # Prefer ripgrep when available (faster, honours .gitignore-style globs);
    # otherwise degrade to a native scan instead of failing the whole check.
    if (Get-Command rg -ErrorAction SilentlyContinue) {
        return @(Invoke-RipgrepSecretScan -Pattern $Pattern)
    }

    Write-Host "Note: ripgrep (rg) not found. Falling back to the built-in secret scan."
    return @(Invoke-NativeSecretScan -Pattern $Pattern)
}

Push-Location $projectRoot
try {
    Test-GitMetadata
    Invoke-CheckedCommand $venvPython -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)"
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
    $secretMatches = Find-CommittedSecrets -Pattern $secretPattern
    if ($secretMatches.Count -gt 0) {
        $secretMatches | ForEach-Object { Write-Host $_ }
        throw "Sensitive value scan found possible committed secrets."
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
