# verify_v139_silent_start.ps1
#
# Desktop check for the v1.3.9-alpha consent start intent.
#
# Usage:
#   $env:IC139_PYTHON = "<path to a python.exe that has the alpha build>"
#   powershell -ExecutionPolicy Bypass -File tests/manual/verify_v139_silent_start.ps1
#
# It stops the live consent host (so the single-instance mutex is free), starts
# the host with --intent=background against an isolated ICON_CONTROL_HOME, and
# proves that:
#   * the host window exists but is not visible;
#   * the foreground window never changes;
#   * consent-host.json records intent=background / last_sync_ok=false while the
#     bridge is unreachable, with no modal dialog;
#   * a second background start neither wakes the window nor steals focus.

Add-Type -TypeDefinition @'
using System;
using System.Text;
using System.Collections.Generic;
using System.Runtime.InteropServices;
public class W {
  public delegate bool P(IntPtr h, IntPtr l);
  [DllImport("user32.dll")] public static extern bool EnumWindows(P cb, IntPtr l);
  [DllImport("user32.dll")] public static extern int GetWindowThreadProcessId(IntPtr h, out int pid);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetClassNameW(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  public static List<string> Scan() {
    var list = new List<string>();
    EnumWindows((h, l) => {
      int pid; GetWindowThreadProcessId(h, out pid);
      var sb = new StringBuilder(256); GetClassNameW(h, sb, 256);
      list.Add(h.ToInt64() + "|" + pid + "|" + IsWindowVisible(h) + "|" + sb.ToString());
      return true;
    }, IntPtr.Zero);
    return list;
  }
}
'@ -Language CSharp

function Show-IconControl {
  param([string]$tag)
  $ic = @([W]::Scan() | Where-Object { $_ -match 'IconControl' })
  $text = if ($ic.Count -gt 0) { $ic -join ' ; ' } else { 'none' }
  "  [$tag] IconControl windows: $text"
  "  [$tag] foreground hwnd: " + ([W]::GetForegroundWindow()).ToInt64()
}

function Get-ConsentHosts {
  Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match 'computer_mcp\.consent' -and $_.CommandLine -notmatch 'Get-CimInstance' }
}

$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$vpy = $env:IC139_PYTHON
if (-not $vpy) { $vpy = Join-Path $repo '.runtime\venv\Scripts\python.exe' }
if (-not (Test-Path $vpy)) {
  throw "Set IC139_PYTHON to a python.exe with the alpha build (looked at $vpy)"
}
$home2 = Join-Path $repo '.runtime\home-silent'

"=== A. baseline ==="
Show-IconControl 'before'
"  consent hosts alive: " + (@(Get-ConsentHosts).Count)

"`n=== B. stop the live host so the mutex is free ==="
foreach ($proc in @(Get-ConsentHosts)) {
  Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue
  "  killed consent pid=$($proc.ProcessId)"
}
Start-Sleep -Milliseconds 800
if (Test-Path $home2) { Remove-Item $home2 -Recurse -Force -ErrorAction SilentlyContinue }
New-Item -ItemType Directory $home2 -Force | Out-Null

"`n=== C. background intent start (isolated home, no bridge) ==="
$env:PYTHONPATH = "$repo\.runtime"
$env:ICON_CONTROL_HOME = $home2
$env:PYTHONIOENCODING = "utf-8"
& $vpy -B -c "from computer_mcp import consent_ipc; print(consent_ipc.open_native('background'))" 2>&1 |
  ForEach-Object { "  py: $_" }
Start-Sleep -Seconds 3

"`n=== D. observe ==="
Get-ConsentHosts | ForEach-Object { "  host pid=$($_.ProcessId) parent=$($_.ParentProcessId)" }
Show-IconControl 'after'
$status = Join-Path $home2 'state\consent-host.json'
if (Test-Path $status) {
  "  consent-host.json: " + (Get-Content $status -Raw -Encoding UTF8).Trim()
} else { "  !! consent-host.json missing" }

"`n=== E. a second start must not wake the window ==="
$fg1 = ([W]::GetForegroundWindow()).ToInt64()
& $vpy -B -c "from computer_mcp import consent_ipc; print(consent_ipc.open_native('background'))" 2>&1 |
  ForEach-Object { "  py: $_" }
Start-Sleep -Seconds 2
$fg2 = ([W]::GetForegroundWindow()).ToInt64()
"  foreground before=$fg1 after=$fg2  unchanged=$($fg1 -eq $fg2)"
Show-IconControl 'second'

"`n=== F. cleanup test host ==="
foreach ($t in @(Get-ConsentHosts)) {
  Stop-Process -Id $t.ProcessId -Force -ErrorAction SilentlyContinue
  "  killed test host pid=$($t.ProcessId)"
}
Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
Remove-Item Env:ICON_CONTROL_HOME -ErrorAction SilentlyContinue
