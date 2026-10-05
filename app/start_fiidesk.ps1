# Launches the native NM Finance desktop app (Flutter Windows).
$ErrorActionPreference = 'Stop'
$appDir = Split-Path -Parent $MyInvocation.MyCommand.Path

$candidates = @(
    (Join-Path $appDir 'build\windows\x64\runner\Release\fiidesk.exe'),
    (Join-Path $appDir 'build\windows\x64\runner\Debug\fiidesk.exe')
)
$exe = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1

if (-not $exe) {
    throw 'fiidesk.exe not found. Run `flutter build windows --release` first.'
}

Start-Process -FilePath $exe -WorkingDirectory (Split-Path -Parent $exe)
