#!/usr/bin/env python3
"""Sync Flutter app files to Windows and rebuild the desktop binary.

The Windows box pulls from ravenna via scp (Linux cannot reliably push through
the agent). Transport is POST /api/windows/exec on the local ravenna-home API.

Lessons already paid for, encoded here so they are not rediscovered:

- Use urllib, never curl: the base64 blob overflows ARG_MAX.
- PowerShell must be UTF-16LE via -EncodedCommand.
- timeout max is 600 (schema ge=5, le=600). 900 returns HTTP 422.
- Windows paths in Python strings use forward slashes.
  A raw string ending in a backslash is a SyntaxError.
"""

from __future__ import annotations

import argparse
import base64
import json
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

API_DEFAULT = "http://127.0.0.1:8100/api/windows/exec"
REMOTE_USER_HOST = "owner@ravenna"
LINUX_APP = "/home/<USER>/Projects/fiidesk/app"
WIN_APP = "C:/Users/lfern/Projects/fiidesk/app"
REPO = Path(__file__).resolve().parents[1]


def _ps_str(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def _windows_exec(script: str, *, api: str, timeout: int) -> dict:
    timeout = max(5, min(600, int(timeout)))
    enc = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    payload = json.dumps(
        {"command": f"powershell -NoProfile -EncodedCommand {enc}", "timeout": timeout}
    ).encode("utf-8")
    req = urllib.request.Request(
        api, data=payload, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=timeout + 20) as resp:
        raw = resp.read().decode("utf-8", "replace")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"output": raw, "exit_code": None}


def _changed_app_files() -> list[str]:
    proc = subprocess.run(
        ["git", "diff", "--name-only", "HEAD"],
        cwd=REPO,
        check=False,
        capture_output=True,
        text=True,
    )
    files: list[str] = []
    for line in (proc.stdout or "").splitlines():
        line = line.strip()
        if line.startswith("app/"):
            files.append(line[len("app/") :])
    extra = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard", "app"],
        cwd=REPO,
        check=False,
        capture_output=True,
        text=True,
    )
    for line in (extra.stdout or "").splitlines():
        line = line.strip()
        if line.startswith("app/"):
            files.append(line[len("app/") :])
    return sorted(set(files))


def _sync_script(files: list[str]) -> str:
    lines = ['$ErrorActionPreference = "Continue"', "$all_ok = $true"]
    for rel in files:
        src = f"{REMOTE_USER_HOST}:{LINUX_APP}/{rel}"
        dst = f"{WIN_APP}/{rel}"
        parent = str(Path(dst).parent).replace("\\", "/")
        lines.append(f"New-Item -ItemType Directory -Force -Path {_ps_str(parent)} | Out-Null")
        lines.append(
            "scp -o BatchMode=yes -o StrictHostKeyChecking=accept-new "
            f"{_ps_str(src)} {_ps_str(dst)}"
        )
        lines.append(
            f"if ($LASTEXITCODE -eq 0) {{ Write-Output ('OK: ' + {_ps_str(rel)}) }} "
            f"else {{ Write-Output ('FAIL: ' + {_ps_str(rel)}); $all_ok = $false }}"
        )
    lines.append(
        "if ($all_ok) { Write-Output 'ALL_TRANSFERS_OK' } else { Write-Output 'SOME_FAILED' }"
    )
    return "\n".join(lines)


def _build_script() -> str:
    return "\n".join(
        [
            '$ErrorActionPreference = "Continue"',
            "Stop-Process -Name fiidesk -Force -ErrorAction SilentlyContinue",
            f"Set-Location {WIN_APP}",
            'Write-Output "=== pub get ==="',
            "flutter pub get",
            'if ($LASTEXITCODE -ne 0) { Write-Output "PUB_GET_FAILED"; exit 1 }',
            'Write-Output "=== build windows release ==="',
            "flutter build windows --release",
            "if ($LASTEXITCODE -eq 0) { Write-Output 'BUILD_OK' } "
            "else { Write-Output ('BUILD_FAILED exit=' + $LASTEXITCODE); exit $LASTEXITCODE }",
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default=API_DEFAULT)
    parser.add_argument("--skip-build", action="store_true")
    parser.add_argument("--timeout", type=int, default=600)
    args = parser.parse_args()

    files = _changed_app_files()
    if not files:
        print("No app/ changes vs HEAD; syncing nothing. Pass files by committing or editing.")
    else:
        print(f"Syncing {len(files)} app file(s)")
        result = _windows_exec(_sync_script(files), api=args.api, timeout=min(args.timeout, 300))
        print(result.get("output") or result)
        if "SOME_FAILED" in str(result.get("output") or ""):
            return 1

    if args.skip_build:
        return 0
    result = _windows_exec(_build_script(), api=args.api, timeout=args.timeout)
    print(result.get("output") or result)
    code = result.get("exit_code")
    return 0 if code in (0, None) and "BUILD_OK" in str(result.get("output") or "") else 1


if __name__ == "__main__":
    sys.exit(main())
