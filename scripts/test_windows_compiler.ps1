$ErrorActionPreference = "Stop"
. "$PSScriptRoot/windows_compiler.ps1"

$temporary = Join-Path ([IO.Path]::GetTempPath()) ("rendaperene-compiler-test-" + [guid]::NewGuid())
$environmentNames = @("INNO_SETUP_COMPILER", "PATH", "ProgramFiles(x86)", "ProgramFiles", "ProgramW6432", "LOCALAPPDATA")
$previousEnvironment = @{}
foreach ($name in $environmentNames) {
    $previousEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
}
$script:registryFixture = @{}
# Isolate registry discovery without modifying the host's installation records.
function Get-ItemProperty {
    [CmdletBinding()]
    param([string] $LiteralPath, [string] $Name)
    if ($script:registryFixture.ContainsKey($LiteralPath)) {
        return [pscustomobject] @{ InstallLocation = $script:registryFixture[$LiteralPath] }
    }
}

function Assert-Compiler {
    param([string] $Expected)
    $actual = Get-InnoSetupCompiler
    if ($actual -ne $Expected) { throw "Incorrect compiler discovery: expected $Expected, got $actual" }
}

function Assert-MissingCompiler {
    param([string] $ExpectedMessage)
    try {
        Get-InnoSetupCompiler | Out-Null
    } catch {
        if ($_.Exception.Message -notlike "*$ExpectedMessage*") { throw }
        return
    }
    throw "Missing compiler was not reported"
}

function New-CompilerFixture {
    param([string] $Directory)
    New-Item -ItemType Directory -Force $Directory | Out-Null
    $compiler = Join-Path $Directory "ISCC.exe"
    [IO.File]::WriteAllText($compiler, "synthetic compiler fixture; never execute")
    return $compiler
}

try {
    New-Item -ItemType Directory $temporary | Out-Null
    $env:INNO_SETUP_COMPILER = ""
    $env:PATH = ""
    ${env:ProgramFiles(x86)} = Join-Path $temporary "programs-x86"
    $env:ProgramFiles = Join-Path $temporary "programs-native"
    $env:ProgramW6432 = Join-Path $temporary "programs-64"
    $env:LOCALAPPDATA = Join-Path $temporary "profile"
    Assert-MissingCompiler "INNO_SETUP_COMPILER"

    # Regression: per-user installations must work without Program Files (x86).
    $perUser = New-CompilerFixture (Join-Path $env:LOCALAPPDATA "Programs/Inno Setup 6")
    Assert-Compiler $perUser
    Remove-Item $perUser

    foreach ($root in @($env:ProgramFiles, ${env:ProgramFiles(x86)}, $env:ProgramW6432)) {
        $compiler = New-CompilerFixture (Join-Path $root "Inno Setup 6")
        Assert-Compiler $compiler
        Remove-Item $compiler
    }

    $custom = New-CompilerFixture (Join-Path $temporary "custom destination")
    $registryKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\Inno Setup 6_is1"
    $script:registryFixture[$registryKey] = Split-Path $custom
    Assert-Compiler $custom
    $script:registryFixture.Clear()

    $env:PATH = Split-Path $custom
    Assert-Compiler $custom
    $env:PATH = ""

    $env:INNO_SETUP_COMPILER = $custom
    Assert-Compiler $custom
    $env:INNO_SETUP_COMPILER = Join-Path $temporary "missing/ISCC.exe"
    Assert-MissingCompiler "INNO_SETUP_COMPILER"
    Write-Output "All compiler discovery checks passed."
} finally {
    foreach ($name in $environmentNames) {
        [Environment]::SetEnvironmentVariable($name, $previousEnvironment[$name], "Process")
    }
    Remove-Item $temporary -Recurse -Force -ErrorAction SilentlyContinue
}
