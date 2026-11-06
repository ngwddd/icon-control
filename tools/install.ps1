param(
    [string]$InstallRoot = (Join-Path $env:LOCALAPPDATA 'IconControl'),
    [string]$Python = 'python',
    [string]$Wheel = '',
    [string]$Constraints = (Join-Path $PSScriptRoot '..\constraints-windows-py312.txt'),
    [int]$BridgePort = 0,
    [switch]$RegisterUi,
    [switch]$Rollback
)
$ErrorActionPreference = 'Stop'
$root = [IO.Path]::GetFullPath($InstallRoot).TrimEnd('\')
if ($root -eq [IO.Path]::GetPathRoot($root).TrimEnd('\') -or $root -eq $env:USERPROFILE) {
    throw 'Use a dedicated installation directory'
}
New-Item -ItemType Directory -Path $root -Force | Out-Null
function Assert-Managed([string]$Candidate) {
    $absolute = [IO.Path]::GetFullPath($Candidate)
    if (-not $absolute.StartsWith($root + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Path outside installation root' }
    return $absolute
}
$current = Assert-Managed (Join-Path $root 'current')
$env:ICON_CONTROL_HOME = $root
function Revoke-CurrentAuthority {
    $currentPython = Join-Path $current 'Scripts\python.exe'
    if (Test-Path -LiteralPath $currentPython) {
        # v1.4.0: the local policy has no approval to revoke. Latching an
        # emergency stop here would freeze the freshly installed agent, so the
        # installer only revokes authority for the human-approval policy.
        # The probe tolerates an older installed build that has no `policy`.
        & $currentPython -c "try:`n    from computer_mcp import policy`nexcept Exception:`n    policy = None`nif policy is not None and policy.is_local():`n    print('headless policy: nothing to revoke'); policy.resume()`nelse:`n    from computer_mcp import security, permission_bridge; security.latch_stop(); permission_bridge.write_state(False, client='installer', event='action')"
        if ($LASTEXITCODE -ne 0) { throw 'Cannot confirm revoked authority; activation/rollback refused' }
    }
}
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss-ffff'
if ($Rollback) {
    Revoke-CurrentAuthority
    $backup = Get-ChildItem -LiteralPath $root -Directory -Filter 'backup-*' | Sort-Object Name -Descending | Select-Object -First 1
    if (-not $backup) { throw 'No rollback version exists' }
    $previous = Assert-Managed $backup.FullName
    if (Test-Path -LiteralPath $current) {
        $failed = Assert-Managed (Join-Path $root ('candidate-' + $stamp))
        Move-Item -LiteralPath $current -Destination $failed
    }
    Move-Item -LiteralPath $previous -Destination $current
    Write-Output 'Previous version restored; restart the host manually.'
    exit 0
}
if (-not $Wheel) {
    $Wheel = (Get-ChildItem -LiteralPath (Join-Path $PSScriptRoot '..\dist') -Filter '*.whl' | Sort-Object LastWriteTime -Descending | Select-Object -First 1).FullName
}
if (-not $Wheel -or -not (Test-Path -LiteralPath $Wheel)) { throw 'Build a wheel first or pass -Wheel' }
$versions = Assert-Managed (Join-Path $root 'versions')
New-Item -ItemType Directory -Path $versions -Force | Out-Null
$staging = Assert-Managed (Join-Path $versions ('candidate-' + $stamp))
& $Python -m venv $staging
if ($LASTEXITCODE -ne 0) { throw 'Creating isolated environment failed' }
$interpreter = Join-Path $staging 'Scripts\python.exe'
if (-not (Test-Path -LiteralPath $Constraints)) { throw 'Validated dependency constraints missing' }
& $interpreter -m pip install -c $Constraints $Wheel
if ($LASTEXITCODE -ne 0) { throw 'Installation failed; current version preserved' }
& $interpreter -c "import computer_mcp,tkinter,sys; from pathlib import Path; from computer_mcp.tool_manifest import validate_registry; validate_registry(); tkinter.Tcl().eval('info patchlevel'); assert Path(sys.executable).with_name('pythonw.exe').is_file()"
if ($LASTEXITCODE -ne 0) { throw 'Import validation failed; current version preserved' }
$backupTarget = Assert-Managed (Join-Path $root ('backup-' + $stamp))
Revoke-CurrentAuthority
$moved = $false
try {
    if (Test-Path -LiteralPath $current) { Move-Item -LiteralPath $current -Destination $backupTarget; $moved=$true }
    # Keep venv paths stable: console launchers embed their absolute prefix.
    # Activation switches a junction; it never relocates an installed venv.
    New-Item -ItemType Junction -Path $current -Target $staging | Out-Null
    $env:ICON_CONTROL_HOME = $root
    $initArguments = @('-m', 'computer_mcp.launcher', 'init')
    if ($RegisterUi) { $initArguments += '--register-ui' }
    if ($BridgePort) {
        $initArguments += @('--bridge-port', "$BridgePort")
        & (Join-Path $current 'Scripts\python.exe') @initArguments
    } else {
        & (Join-Path $current 'Scripts\python.exe') @initArguments
    }
    if ($LASTEXITCODE -ne 0) { throw 'Provisioning failed' }
    # v1.4.0 headless: the previous build may have latched an emergency stop
    # during Revoke-CurrentAuthority. The local policy starts authorised at
    # activation, so an upgrade must not leave the fresh install frozen.
    & (Join-Path $current 'Scripts\python.exe') -c "try:`n    from computer_mcp import policy`n    if policy.is_local(): policy.resume()`nexcept Exception:`n    pass"
} catch {
    if (Test-Path -LiteralPath $current) {
        $failed = Assert-Managed (Join-Path $root ('candidate-' + $stamp))
        Move-Item -LiteralPath $current -Destination $failed
    }
    if ($moved) { Move-Item -LiteralPath $backupTarget -Destination $current }
    throw
}
Write-Output ('Installed candidate: ' + $current)
Write-Output 'Use current\Scripts\python.exe -m computer_mcp.launcher stdio in your MCP client.'
Write-Output 'For a custom InstallRoot, also set ICON_CONTROL_HOME to the same directory.'
Write-Output 'v1.4.0 runs headless: no approval window, no tray, no hotkey. Set ICON_CONTROL_POLICY=human to restore the approval flow.'
