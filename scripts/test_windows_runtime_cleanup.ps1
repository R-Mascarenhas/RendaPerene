param([string] $WorkDirectory = "out/runtime-cleanup-tests")

$ErrorActionPreference = "Stop"
. "$PSScriptRoot/windows_compiler.ps1"
$compiler = Get-InnoSetupCompiler
$work = Join-Path ([IO.Path]::GetFullPath($WorkDirectory)) ([guid]::NewGuid().ToString())
$bundle = Join-Path $work "bundle"
$destination = Join-Path $work "installation"
$outside = Join-Path $work "outside-runtime"
$oldMetadata = Join-Path $destination "_internal/streamlit-0.0.1.dist-info"
$orphanMetadata = Join-Path $destination "_internal/streamlit-0.0.0.dist-info"
$currentMetadata = Join-Path $bundle "_internal/streamlit-9.9.9.dist-info"
$keptDirectory = Join-Path $destination "_internal/preserved"
$junction = Join-Path $destination "_internal/external-link"

foreach ($directory in @($oldMetadata, $orphanMetadata, $currentMetadata, $keptDirectory, "$outside/empty-child")) {
    New-Item -ItemType Directory -Force $directory | Out-Null
}
[IO.File]::WriteAllText("$oldMetadata/METADATA", "Metadata-Version: 2.1`nName: streamlit`nVersion: 0.0.1`n")
[IO.File]::WriteAllText("$currentMetadata/METADATA", "Metadata-Version: 2.1`nName: streamlit`nVersion: 9.9.9`n")
[IO.File]::WriteAllText("$destination/runtime-manifest.txt", "_internal\streamlit-0.0.1.dist-info\METADATA`r`n")
[IO.File]::WriteAllText("$bundle/runtime-manifest.txt", "_internal\streamlit-9.9.9.dist-info\METADATA`r`n")
[IO.File]::WriteAllText("$keptDirectory/user-file.txt", "preserved synthetic content")
New-Item -ItemType Junction -Path $junction -Target $outside | Out-Null

# Compile the production cleanup code in a registry-free, shortcut-free installer.
$production = Get-Content (Join-Path $PSScriptRoot "windows_installer.iss") -Raw
$code = $production.Substring($production.IndexOf("[Code]"))
$fixture = @"
[Setup]
AppId=RendaPereneRuntimeCleanupProbe
AppName=RendaPerene runtime cleanup probe
AppVersion=1.0.0
DefaultDirName=$destination
UsePreviousAppDir=no
PrivilegesRequired=lowest
Uninstallable=no
CreateUninstallRegKey=no
DisableDirPage=yes
DisableProgramGroupPage=yes
OutputDir=$work
OutputBaseFilename=cleanup-probe
Compression=none
SetupLogging=yes
[Files]
Source: "$bundle\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
$code
"@
$fixturePath = Join-Path $work "cleanup-probe.iss"
[IO.File]::WriteAllText($fixturePath, $fixture, [Text.UTF8Encoding]::new($true))
& $compiler "/Q" $fixturePath
if ($LASTEXITCODE -ne 0) { throw "Cleanup probe compilation failed; artifacts: $work" }
$setup = Join-Path $work "cleanup-probe.exe"
$arguments = @("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-", "/DIR=$destination", "/LOG=$work/setup.log")
$quoted = $arguments | ForEach-Object { '"' + $_ + '"' }
$process = Start-Process -FilePath $setup -ArgumentList $quoted -Wait -PassThru
if ($process.ExitCode -ne 0) { throw "Cleanup probe installation failed; artifacts: $work" }

if ((Test-Path $oldMetadata) -or (Test-Path $orphanMetadata)) {
    throw "Upgrade left obsolete distribution metadata directories; artifacts: $work"
}
if (-not (Test-Path "$destination/_internal/streamlit-9.9.9.dist-info/METADATA")) {
    throw "Upgrade removed current distribution metadata"
}
if ((Get-Content "$keptDirectory/user-file.txt") -ne "preserved synthetic content") {
    throw "Cleanup changed a nonempty runtime directory"
}
if (-not (Test-Path $junction) -or -not (Test-Path "$outside/empty-child")) {
    throw "Cleanup followed a junction outside the private runtime"
}
Write-Output "PASS: obsolete metadata removed; current metadata, nonempty directories and junction targets preserved."
Write-Output "Probe artifacts: $work"
