param([Parameter(Mandatory=$true)][string]$StatePath)
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type 'public static class FixtureDpi { [System.Runtime.InteropServices.DllImport("user32.dll")] public static extern bool SetProcessDpiAwarenessContext(System.IntPtr value); }'
[void][FixtureDpi]::SetProcessDpiAwarenessContext([IntPtr](-4))
$script:counts = @{Confirm1=0;Confirm2=0;Counter=0}
$script:dragging=$false
$script:dragMoves=0
$form=New-Object System.Windows.Forms.Form
$form.Text='Icon Control rc2 acceptance'
$form.Size=New-Object System.Drawing.Size(800,650)
$form.StartPosition='Manual'
$form.Location=New-Object System.Drawing.Point(80,80)
$form.AutoScaleMode='Dpi'
$status=New-Object System.Windows.Forms.Label
$status.Text='RC2 TEST FIXTURE - waiting for instructions'
$status.Location=New-Object System.Drawing.Point(20,12)
$status.Size=New-Object System.Drawing.Size(740,55)
$status.Font=New-Object System.Drawing.Font('Segoe UI',14,[System.Drawing.FontStyle]::Bold)
$form.Controls.Add($status)
function Add-Button($text,$name,$x,$handler) {
  $button=New-Object System.Windows.Forms.Button
  $button.Text=$text;$button.Name=$name;$button.AccessibleName=$text
  $button.Location=New-Object System.Drawing.Point($x,75)
  $button.Size=New-Object System.Drawing.Size(130,42)
  $button.Add_Click($handler);$form.Controls.Add($button)
}
Add-Button 'Confirm' 'Confirm1' 20 {$script:counts.Confirm1++}
Add-Button 'Confirm' 'Confirm2' 170 {$script:counts.Confirm2++}
Add-Button 'Counter' 'Counter' 320 {$script:counts.Counter++}
$script:input=New-Object System.Windows.Forms.TextBox
$script:input.Multiline=$true;$script:input.Name='Input';$script:input.AccessibleName='Input'
$script:input.Location=New-Object System.Drawing.Point(20,130)
$script:input.Size=New-Object System.Drawing.Size(720,90)
$form.Controls.Add($script:input)
$script:list=New-Object System.Windows.Forms.ListBox
$script:list.Name='Scroll';$script:list.AccessibleName='Scroll'
$script:list.Location=New-Object System.Drawing.Point(20,240)
$script:list.Size=New-Object System.Drawing.Size(720,150)
0..79 | ForEach-Object {[void]$script:list.Items.Add(('item-{0:D3}' -f $_))}
$form.Controls.Add($script:list)
$pad=New-Object System.Windows.Forms.Panel
$pad.Name='Drag';$pad.AccessibleName='Drag'
$pad.Location=New-Object System.Drawing.Point(20,415)
$pad.Size=New-Object System.Drawing.Size(720,100)
$pad.BackColor=[System.Drawing.Color]::LightBlue
$pad.Add_MouseDown({$script:dragging=$true;$pad.Capture=$true})
$pad.Add_MouseMove({if($script:dragging){$script:dragMoves++}})
$pad.Add_MouseUp({$script:dragging=$false;$pad.Capture=$false})
$form.Controls.Add($pad)
Add-Button 'Reset' 'Reset' 490 {$script:counts=@{Confirm1=0;Confirm2=0;Counter=0};$script:input.Clear();$script:list.TopIndex=0;$script:dragMoves=0}
$timer=New-Object System.Windows.Forms.Timer
$timer.Interval=100
$timer.Add_Tick({
  # A hidden PowerShell host can pass SW_HIDE through STARTUPINFO. Keep the
  # terminal hidden while explicitly showing the interactive fixture controls.
  $form.Visible=$true
  foreach($child in $form.Controls) {$child.Visible=$true}
  $commandPath=$StatePath+'.command'
  if(Test-Path -LiteralPath $commandPath) {$status.Text=[IO.File]::ReadAllText($commandPath)}
  $data=@{counts=$script:counts;text=$script:input.Text;scroll=$script:list.TopIndex;
    dragging=$script:dragging;drag_moves=$script:dragMoves;dpi=$form.DeviceDpi;
    client_width=$form.ClientSize.Width;client_height=$form.ClientSize.Height}
  [IO.File]::WriteAllText($StatePath,($data|ConvertTo-Json -Depth 5),(New-Object Text.UTF8Encoding($false)))
})
$timer.Start()
[void]$form.ShowDialog()
$timer.Dispose()
