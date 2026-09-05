$ErrorActionPreference = "Stop"
$buildVenv = "venv_dist"
if (-not (Test-Path "$buildVenv\Scripts\python.exe")) {
    & python -m venv $buildVenv
    if ($LASTEXITCODE -ne 0) { throw "Python command failed with exit code $LASTEXITCODE" }
}
$buildPython = Join-Path $buildVenv "Scripts\python.exe"

function Invoke-Python {
    param([string[]] $Arguments)
    & $buildPython @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Python command failed with exit code $LASTEXITCODE"
    }
}

$appVersion = (Get-Content version.txt -Raw).Trim()
if ([string]::IsNullOrWhiteSpace($appVersion)) { throw "version.txt is empty" }
if ($env:GITHUB_REF_TYPE -eq "tag" -and $env:GITHUB_REF_NAME.TrimStart("v") -ne $appVersion) {
    throw "Release tag does not match version.txt"
}

Invoke-Python @("-m", "pip", "install", "--upgrade", "pip")
Invoke-Python @("-m", "pip", "install", ".[packaging]")
Invoke-Python @("-m", "PyInstaller", "--clean", "--noconfirm", "--distpath", "dist", "--workpath", "build", "RendaPerene.spec")

$archive = "dist/RendaPerene-v$appVersion-windows-x64.zip"
if (Test-Path $archive) { Remove-Item $archive -Force }
Invoke-Python @("scripts/validate_bundle.py", "dist/RendaPerene-v$appVersion", $appVersion)
Invoke-Python @("scripts/smoke_bundle.py", "dist/RendaPerene-v$appVersion/RendaPerene-v$appVersion.exe")
Compress-Archive -Path "dist/RendaPerene-v$appVersion" -DestinationPath $archive
