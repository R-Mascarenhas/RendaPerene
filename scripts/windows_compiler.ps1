function Get-InnoSetupCompiler {
    if (-not [string]::IsNullOrWhiteSpace($env:INNO_SETUP_COMPILER)) {
        if (-not (Test-Path -LiteralPath $env:INNO_SETUP_COMPILER -PathType Leaf)) {
            throw "INNO_SETUP_COMPILER must point to an existing ISCC.exe file."
        }
        return (Resolve-Path -LiteralPath $env:INNO_SETUP_COMPILER).ProviderPath
    }

    $command = Get-Command ISCC.exe -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -ne $command) { return $command.Source }

    $registryKeys = @(
        "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\Inno Setup 6_is1",
        "HKCU:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\Inno Setup 6_is1",
        "HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\Inno Setup 6_is1",
        "HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\Inno Setup 6_is1"
    )
    $roots = @(${env:ProgramFiles(x86)}, $env:ProgramFiles, $env:ProgramW6432)
    if (-not [string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
        $roots += Join-Path $env:LOCALAPPDATA "Programs"
    }
    $candidates = @()
    foreach ($key in $registryKeys) {
        $installation = Get-ItemProperty -LiteralPath $key -Name InstallLocation -ErrorAction SilentlyContinue
        if ($null -ne $installation -and -not [string]::IsNullOrWhiteSpace($installation.InstallLocation)) {
            $candidates += Join-Path $installation.InstallLocation "ISCC.exe"
        }
    }
    foreach ($root in $roots) {
        if (-not [string]::IsNullOrWhiteSpace($root)) {
            $candidates += Join-Path $root "Inno Setup 6/ISCC.exe"
        }
    }
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            return (Resolve-Path -LiteralPath $candidate).ProviderPath
        }
    }
    throw "Inno Setup 6 compiler (ISCC.exe) was not found. Install Inno Setup 6 or set INNO_SETUP_COMPILER to its full path."
}
