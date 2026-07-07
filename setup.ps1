param(
    [switch]$UseLock
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$venvPath = Join-Path $projectRoot ".venv"
$envExamplePath = Join-Path $projectRoot ".env.example"
$envPath = Join-Path $projectRoot ".env"
$requirementsPath = Join-Path $projectRoot "requirements.txt"

if ($UseLock) {
    $lockPath = Join-Path $projectRoot "requirements.lock.txt"
    if (-not (Test-Path $lockPath)) {
        throw "Lock file not found: $lockPath"
    }
    $requirementsPath = $lockPath
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

if (-not (Test-Path $venvPath)) {
    Invoke-CheckedCommand "python" -m venv $venvPath
}

$venvPython = Join-Path $venvPath "Scripts\\python.exe"
Invoke-CheckedCommand $venvPython -m pip install --upgrade pip
Invoke-CheckedCommand $venvPython -m pip install -r $requirementsPath

if (-not (Test-Path $envPath)) {
    Copy-Item $envExamplePath $envPath
    Write-Host "Created .env from .env.example"
} else {
    Write-Host ".env already exists, skipped copy"
}

Write-Host "Setup completed."
