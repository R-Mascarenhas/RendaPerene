param([Parameter(Mandatory = $true)][string] $Installer)

$ErrorActionPreference = "Stop"
. "$PSScriptRoot/windows_compiler.ps1"
if ($env:CI -ne "true") {
    throw "Run installer lifecycle tests only on a disposable CI Windows runner."
}
$installer = (Resolve-Path $Installer).Path
$compiler = Get-InnoSetupCompiler
$temporary = Join-Path $env:RUNNER_TEMP ([guid]::NewGuid().ToString())
New-Item -ItemType Directory -Path $temporary | Out-Null
$defaultDirectory = Join-Path $env:LOCALAPPDATA "Programs/RendaPerene"
$customDirectory = Join-Path $temporary "Custom destination/RendaPerene"
$desktopShortcut = Join-Path ([Environment]::GetFolderPath("Desktop")) "RendaPerene.lnk"
$menuShortcut = Join-Path ([Environment]::GetFolderPath("Programs")) "RendaPerene.lnk"
$dataMarker = Join-Path $env:LOCALAPPDATA "RendaPerene/installer-test-$([guid]::NewGuid()).txt"
$profilePath = ([Environment]::GetFolderPath("LocalApplicationData")).ToLowerInvariant()
$profileHash = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData([Text.Encoding]::Unicode.GetBytes($profilePath))).ToLowerInvariant()
$mutexName = "Global\RendaPerene.$profileHash"
New-Item -ItemType Directory -Force (Split-Path $dataMarker) | Out-Null
Set-Content $dataMarker "synthetic portfolio data"

function Invoke-Setup {
    param([string] $Path, [string[]] $ExtraArguments = @(), [switch] $ExpectFailure)
    $arguments = @("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-") + $ExtraArguments
    $quotedArguments = $arguments | ForEach-Object { '"' + $_ + '"' }
    $process = Start-Process -FilePath $Path -ArgumentList $quotedArguments -Wait -PassThru
    if ($ExpectFailure) {
        if ($process.ExitCode -eq 0) { throw "Installer unexpectedly succeeded" }
    } elseif ($process.ExitCode -ne 0) {
        throw "Installer exited with $($process.ExitCode)"
    }
}

function Assert-Shortcut {
    param([string] $Path, [string] $Target)
    if (-not (Test-Path $Path)) { throw "Missing shortcut: $Path" }
    $shell = New-Object -ComObject WScript.Shell
    if ($shell.CreateShortcut($Path).TargetPath -ne $Target) {
        throw "Shortcut target changed: $Path"
    }
}

# Build a genuinely older installer with an obsolete private runtime resource.
$obsoleteSource = Join-Path (Resolve-Path "dist/RendaPerene/_internal").Path "obsolete-installer-test.txt"
$obsoleteMetadata = Join-Path (Resolve-Path "dist/RendaPerene/_internal").Path "obsolete_dependency-0.0.0.dist-info"
$manifest = (Resolve-Path "dist/RendaPerene/runtime-manifest.txt").Path
$originalManifest = [IO.File]::ReadAllBytes($manifest)
try {
    Set-Content $obsoleteSource "obsolete runtime dependency"
    New-Item -ItemType Directory $obsoleteMetadata | Out-Null
    [IO.File]::WriteAllText("$obsoleteMetadata/METADATA", "Metadata-Version: 2.1`nName: obsolete-dependency`nVersion: 0.0.0`n")
    [IO.File]::AppendAllText($manifest, "_internal\obsolete-installer-test.txt`r`n", [Text.UTF8Encoding]::new($false))
    [IO.File]::AppendAllText($manifest, "_internal\obsolete_dependency-0.0.0.dist-info\METADATA`r`n", [Text.UTF8Encoding]::new($false))
    & $compiler "/DAppVersion=0.0.0" "/DBundleDir=$((Resolve-Path dist/RendaPerene).Path)" "/DOutputDir=$temporary" "scripts/windows_installer.iss"
    if ($LASTEXITCODE -ne 0) { throw "Previous installer fixture compilation failed" }
} finally {
    Remove-Item $obsoleteSource -ErrorAction SilentlyContinue
    Remove-Item $obsoleteMetadata -Recurse -Force -ErrorAction SilentlyContinue
    [IO.File]::WriteAllBytes($manifest, $originalManifest)
}
$previousInstaller = Join-Path $temporary "RendaPerene-v0.0.0-windows-x64-setup.exe"

try {
    foreach ($directory in @($defaultDirectory, $customDirectory)) {
        $initialArguments = @("/TASKS=desktopicon")
        if ($directory -eq $customDirectory) { $initialArguments += "/DIR=$directory" }
        Invoke-Setup $previousInstaller $initialArguments
        $executable = Join-Path $directory "RendaPerene.exe"
        if (-not (Test-Path $executable)) { throw "Incorrect installation destination" }
        Assert-Shortcut $desktopShortcut $executable
        Assert-Shortcut $menuShortcut $executable
        $rootMarker = Join-Path $directory "user-file.txt"
        Set-Content $rootMarker "user file outside private runtime"
        if (-not (Test-Path "$directory/_internal/obsolete-installer-test.txt")) {
            throw "Previous installer fixture is missing obsolete resource"
        }
        $installedMetadata = Join-Path $directory "_internal/obsolete_dependency-0.0.0.dist-info"
        $orphanMetadata = Join-Path $directory "_internal/streamlit-0.0.0.dist-info"
        New-Item -ItemType Directory $orphanMetadata | Out-Null

        # Trigger a real extraction failure: Windows refuses replacement of this locked file.
        # /SUPPRESSMSGBOXES chooses Abort on the installer's Abort/Retry error prompt.
        $manifestLock = [IO.File]::Open((Join-Path $directory "runtime-manifest.txt"), [IO.FileMode]::Open, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
        try {
            Invoke-Setup $installer -ExpectFailure
        } finally {
            $manifestLock.Dispose()
        }
        if (-not (Test-Path "$directory/_internal/obsolete-installer-test.txt")) {
            throw "Failed upgrade removed the previous runtime"
        }
        if (-not (Test-Path "$installedMetadata/METADATA") -or -not (Test-Path $orphanMetadata)) {
            throw "Failed upgrade removed previous runtime metadata directories"
        }
        & "venv_dist/Scripts/python.exe" scripts/smoke_bundle.py $executable
        if ($LASTEXITCODE -ne 0) { throw "Application failed to start after interrupted extraction" }

        # No /DIR or /TASKS: upgrades must remember both previous choices.
        Invoke-Setup $installer
        if (Test-Path "$directory/_internal/obsolete-installer-test.txt") {
            throw "Upgrade left an obsolete runtime resource"
        }
        if ((Test-Path $installedMetadata) -or (Test-Path $orphanMetadata)) {
            throw "Upgrade left empty distribution metadata directories"
        }
        Assert-Shortcut $desktopShortcut $executable
        Assert-Shortcut $menuShortcut $executable
        if ((Get-Content $rootMarker) -ne "user file outside private runtime") {
            throw "Upgrade changed a user file"
        }
        if ((Get-Content $dataMarker) -ne "synthetic portfolio data") {
            throw "Upgrade changed persistent data"
        }
        & "venv_dist/Scripts/python.exe" scripts/smoke_bundle.py $executable
        if ($LASTEXITCODE -ne 0) { throw "Installed application smoke test failed" }
        $browserOutput = if ($directory -eq $defaultDirectory) { "test-results/windows-native-default" } else { "test-results/windows-native-custom" }
        & "venv_dist/Scripts/python.exe" -m pytest e2e/test_navigation.py --e2e-executable $executable --browser chromium --browser-channel msedge --tracing retain-on-failure --screenshot only-on-failure --output $browserOutput
        if ($LASTEXITCODE -ne 0) { throw "Upgraded application retained content from another screen" }

        $env:RENDAPERENE_HEADLESS = "true"
        $application = Start-Process $executable -PassThru
        $mutex = $null
        try {
            $deadline = (Get-Date).AddSeconds(30)
            while ((Get-Date) -lt $deadline) {
                try {
                    $mutex = [Threading.Mutex]::OpenExisting($mutexName)
                    break
                } catch [Threading.WaitHandleCannotBeOpenedException] {
                    Start-Sleep -Milliseconds 250
                }
            }
            if ($null -eq $mutex) { throw "Running application did not publish installer mutex" }
            Invoke-Setup $installer -ExpectFailure
            Invoke-Setup (Join-Path $directory "unins000.exe") -ExpectFailure
            if (-not (Test-Path $executable)) { throw "Running installation was modified" }
        } finally {
            if ($null -ne $mutex) { $mutex.Dispose() }
            if (-not $application.HasExited) { $application.Kill(); $application.WaitForExit() }
            Remove-Item Env:RENDAPERENE_HEADLESS -ErrorAction SilentlyContinue
        }

        Invoke-Setup (Join-Path $directory "unins000.exe")
        if ((Test-Path $executable) -or (Test-Path $desktopShortcut) -or (Test-Path $menuShortcut)) {
            throw "Uninstall left the application or its shortcuts"
        }
        if (-not (Test-Path $rootMarker) -or -not (Test-Path $dataMarker)) {
            throw "Uninstall removed user data"
        }
        Remove-Item $rootMarker
    }
} finally {
    Remove-Item $dataMarker -ErrorAction SilentlyContinue
    Remove-Item $temporary -Recurse -Force
}
