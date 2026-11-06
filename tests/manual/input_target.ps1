param(
    [Parameter(Mandatory = $true)][string]$StatePath
)
# Minimal input target for the v1.4.0 MCP acceptance: a textbox, a button and a
# state file. Nothing here touches the user's data or windows.
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$form = New-Object System.Windows.Forms.Form
$form.Text = 'Icon Control v1.4 input target'
$form.ClientSize = New-Object System.Drawing.Size(420, 200)
$form.StartPosition = 'Manual'
$form.Location = New-Object System.Drawing.Point(300, 200)
$form.TopMost = $true

$box = New-Object System.Windows.Forms.TextBox
$box.Name = 'Box'
$box.Location = New-Object System.Drawing.Point(30, 40)
$box.Size = New-Object System.Drawing.Size(340, 30)

$button = New-Object System.Windows.Forms.Button
$button.Name = 'Commit'
$button.Text = 'Commit'
$button.Location = New-Object System.Drawing.Point(30, 100)
$button.Size = New-Object System.Drawing.Size(140, 40)

$label = New-Object System.Windows.Forms.Label
$label.Name = 'Status'
$label.Text = 'idle'
$label.Location = New-Object System.Drawing.Point(190, 108)
$label.Size = New-Object System.Drawing.Size(200, 30)

$button.Add_Click({
    $payload = @{ text = $script:box.Text; at = (Get-Date -Format 'o') } | ConvertTo-Json -Compress
    [System.IO.File]::WriteAllText($StatePath, $payload)
    $label.Text = 'committed'
})

$form.Controls.Add($box)
$form.Controls.Add($button)
$form.Controls.Add($label)
$form.Add_Shown({ $form.Activate(); $box.Focus() })
[System.Windows.Forms.Application]::Run($form)
