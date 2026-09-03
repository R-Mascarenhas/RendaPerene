$ErrorActionPreference = "Stop"

$appVersion = (Get-Content version.txt -Raw).Trim()
if ([string]::IsNullOrWhiteSpace($appVersion)) { throw "version.txt is empty" }
if ($env:GITHUB_REF_TYPE -eq "tag" -and $env:GITHUB_REF_NAME.TrimStart("v") -ne $appVersion) {
    throw "Release tag does not match version.txt"
}

python -m pip install --upgrade pip
python -m pip install ".[packaging]"
python -m PyInstaller --clean --noconfirm --distpath dist --workpath build RendaPerene.spec

$archive = "dist/RendaPerene-v$appVersion-windows-x64.zip"
if (Test-Path $archive) { Remove-Item $archive -Force }
Compress-Archive -Path "dist/RendaPerene-v$appVersion" -DestinationPath $archive
python scripts/validate_bundle.py "dist/RendaPerene-v$appVersion" $appVersion
python scripts/smoke_bundle.py "dist/RendaPerene-v$appVersion/RendaPerene-v$appVersion.exe"
