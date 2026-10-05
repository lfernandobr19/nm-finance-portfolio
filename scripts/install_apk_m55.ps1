#Requires -Version 5.1
param(
  [string]$ApkName = "NM-Finance-0.1.38.apk",
  [string]$ArtifactBase = "http://<RAVENNA_TAILSCALE_IP>:8100/artifacts/fiidesk",
  [string]$AgentBase = "http://<ANDROID_TAILSCALE_IP>:8781",
  [string]$Token = "ravenna-android-agent-2026",
  [int]$AdbPort = 35181,
  [int]$ScanMin = 30000,
  [int]$ScanMax = 50000,
  [int]$WaitSeconds = 0
)

$ErrorActionPreference = "Stop"
$hdr = @{
  Authorization = "Bearer $Token"
  "Content-Type" = "application/json"
}
$url = "$ArtifactBase/$ApkName"

function Test-Agent {
  try {
    $null = Invoke-RestMethod -Uri "$AgentBase/health" -TimeoutSec 5
    return $true
  } catch {
    return $false
  }
}

function Agent-Post([string]$Path, $Body, [int]$TimeoutSec = 60) {
  $json = $Body | ConvertTo-Json -Compress -Depth 8
  return Invoke-RestMethod -Method POST -Uri "$AgentBase$Path" -Headers $hdr -Body $json -TimeoutSec $TimeoutSec
}

function Agent-Exec([string]$Command, [int]$TimeoutSec = 60) {
  return Agent-Post "/exec" @{ command = $Command; timeout = $TimeoutSec } $TimeoutSec
}

function Get-AdbStatus {
  return Agent-Post "/adb/status" @{} 30
}

# A device is ready only when `connected` is true and the devices list shows a
# transport in the "device" state (not stuck "offline").
function Test-AdbReady([object]$st) {
  if (-not $st -or -not $st.connected) { return $false }
  $devices = [string]$st.devices
  return ($devices -match '\bdevice\b') -and ($devices -notmatch '\boffline\b')
}

function Connect-And-Check([int]$Port) {
  try {
    $r = Agent-Post "/adb/connect" @{ host = "127.0.0.1"; port = $Port } 30
    $msg = if ($r -and $r.output) { [string]$r.output } else { "" }
    Write-Host "  connect $Port : $msg"
  } catch {
    Write-Host "  connect $Port : $($_.Exception.Message)"
  }
  Start-Sleep -Milliseconds 900
  $st = Get-AdbStatus
  if (Test-AdbReady $st) {
    return $true
  }
  # Drop any offline/stale transport so it doesn't mask later attempts.
  try { Agent-Exec "adb disconnect 127.0.0.1:$Port" 10 | Out-Null } catch {}
  return $false
}

function Discover-AdbPort([int]$Preferred, [int]$Min, [int]$Max) {
  # 1. Fast path: an already-connected device.
  $st = Get-AdbStatus
  if (Test-AdbReady $st) {
    Write-Host "ADB already connected."
    return -1
  }

  # 2. Preferred port hint (last known good port).
  if ($Preferred -gt 0) {
    Write-Host "Trying preferred port $Preferred ..."
    if (Connect-And-Check $Preferred) { return $Preferred }
  }

  # 3. Scan the phone's localhost for open TCP ports in the wireless-ADB range.
  Write-Host "Scanning phone localhost ($Min-$Max) ..."
  $scanPy = @"
import socket
open_ports=[]
for p in range($Min,$Max):
    s=socket.socket(); s.settimeout(0.008)
    try:
        if s.connect_ex(("127.0.0.1",p))==0: open_ports.append(p)
    except Exception: pass
    finally: s.close()
print("OPEN", " ".join(map(str, open_ports)))
"@
  Agent-Post "/write-file" @{ path = "/data/data/com.termux/files/home/scan_adb.py"; content = $scanPy; encoding = "utf8" } | Out-Null
  $scan = Agent-Exec "python /data/data/com.termux/files/home/scan_adb.py" 120
  $out = [string]$scan.output
  $ports = @()
  if ($out -match 'OPEN (.+)') {
    $ports = ($Matches[1] -split '\s+') | Where-Object { $_ -match '^\d+$' } | ForEach-Object { [int]$_ }
  }
  if (-not $ports) {
    Write-Host "No open ports found."
  } else {
    Write-Host "Open ports: $($ports -join ', ')"
    foreach ($p in $ports) {
      if (Connect-And-Check $p) { return $p }
    }
  }

  # 4. Last resort: mDNS service discovery.
  Write-Host "Trying mDNS discovery ..."
  try {
    $mdns = Agent-Exec "adb mdns services" 20
    Write-Host ([string]$mdns.output)
  } catch {
    Write-Host "mdns failed: $($_.Exception.Message)"
  }

  return 0
}

$deadline = (Get-Date).AddSeconds([Math]::Max(0, $WaitSeconds))
while (-not (Test-Agent)) {
  if ((Get-Date) -ge $deadline) {
    throw "Android agent offline at $AgentBase. Open Termux and run start.sh, then retry."
  }
  Write-Host "Waiting for agent on $AgentBase ..."
  Start-Sleep -Seconds 5
}

Write-Host "=== adb connect ==="
$foundPort = Discover-AdbPort -Preferred $AdbPort -Min $ScanMin -Max $ScanMax
$st = Get-AdbStatus
$st | ConvertTo-Json -Depth 5 -Compress
if (-not (Test-AdbReady $st)) {
  throw "Could not connect ADB to the device. Open Termux, verify Wireless Debugging is enabled, then retry."
}

Write-Host "=== download $url ==="
$dest = "/data/data/com.termux/files/home/storage/shared/Download/$ApkName"
Agent-Post "/download" @{ url = $url; dest = $dest; timeout = 300 } 320 | ConvertTo-Json -Depth 4

Write-Host "=== install ==="
$installPath = "/storage/emulated/0/Download/$ApkName"
$inst = Agent-Post "/adb/install" @{ path = $installPath } 180
$inst | ConvertTo-Json -Depth 6
if (-not $inst.ok) {
  Write-Host "adb/install failed; trying open-file"
  Agent-Post "/open-file" @{ path = $installPath } 60 | ConvertTo-Json -Depth 4
  throw "Install failed for $ApkName"
}

Write-Host "=== launch ==="
try {
  Agent-Post "/exec" @{
    command = "adb shell am force-stop com.fiidesk.fiidesk; adb shell monkey -p com.fiidesk.fiidesk -c android.intent.category.LAUNCHER 1"
    timeout = 30
  } 40 | ConvertTo-Json -Depth 4
} catch {
  Write-Host "launch skipped: $($_.Exception.Message)"
}

Write-Host "OK: installed $ApkName"
