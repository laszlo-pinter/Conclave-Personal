$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSCommandPath))
$StartupDir = [Environment]::GetFolderPath("Startup")
$ShortcutPath = Join-Path $StartupDir "Conclave Personal.lnk"
$Target = Join-Path $ProjectRoot "scripts\windows\start_desktop.ps1"

$Shell = New-Object -ComObject WScript.Shell
$Shortcut = $Shell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = "powershell.exe"
$Shortcut.Arguments = "-ExecutionPolicy Bypass -File `"$Target`""
$Shortcut.WorkingDirectory = $ProjectRoot
$Shortcut.Save()

Write-Host "Autostart eingerichtet: $ShortcutPath"
