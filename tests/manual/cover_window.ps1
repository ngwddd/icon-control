param(
    [Parameter(Mandatory = $true)][int]$X,
    [Parameter(Mandatory = $true)][int]$Y,
    [Parameter(Mandatory = $true)][int]$W,
    [Parameter(Mandatory = $true)][int]$H,
    [int]$Seconds = 90
)
# A small, clearly-labelled cover used by S5 case B22: the target must not be
# clicked through an occluding window. It used to be a plain black rectangle the
# size of the whole fixture, which looked to the user like the screen going black.
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$form = New-Object System.Windows.Forms.Form
$form.Text = 'Icon Control cover'
$form.FormBorderStyle = 'None'
$form.StartPosition = 'Manual'
$form.Bounds = New-Object System.Drawing.Rectangle($X, $Y, $W, $H)
$form.TopMost = $true
$form.BackColor = [System.Drawing.Color]::FromArgb(255, 40, 44, 52)
$form.ShowInTaskbar = $false
$form.Add_Paint({
    param($sender, $event)
    $font = New-Object System.Drawing.Font('Segoe UI', 11, [System.Drawing.FontStyle]::Bold)
    try {
        $event.Graphics.DrawString('S5-B22 遮挡测试', $font,
            [System.Drawing.Brushes]::Gainsboro, 8, 6)
    } finally { $font.Dispose() }
})
$timer = New-Object System.Windows.Forms.Timer
$timer.Interval = [Math]::Max(1000, $Seconds * 1000)
$timer.Add_Tick({ $form.Close() })
$timer.Start()
[System.Windows.Forms.Application]::Run($form)
$timer.Dispose()
