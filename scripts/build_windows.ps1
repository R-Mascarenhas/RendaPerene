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

$bundle = (Resolve-Path "dist/RendaPerene").Path
Invoke-Python @("scripts/validate_bundle.py", $bundle, $appVersion)
Invoke-Python @("scripts/smoke_bundle.py", "$bundle/RendaPerene.exe")
$runtimeFiles = Get-ChildItem "$bundle/_internal" -Recurse -File | ForEach-Object {
    $_.FullName.Substring($bundle.Length + 1)
}
[IO.File]::WriteAllLines((Join-Path $bundle "runtime-manifest.txt"), [string[]] $runtimeFiles, [Text.UTF8Encoding]::new($true))

$compiler = Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6/ISCC.exe"
if (-not (Test-Path $compiler)) {
    throw "Install Inno Setup 6 before building the Windows installer."
}
& $compiler "/DAppVersion=$appVersion" "/DBundleDir=$bundle" "/DOutputDir=$((Resolve-Path dist).Path)" "scripts/windows_installer.iss"
if ($LASTEXITCODE -ne 0) { throw "Inno Setup compilation failed" }
