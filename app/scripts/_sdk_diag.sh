#!/usr/bin/env bash
SDK=/home/<USER>/learning-agent/data/cache/android-sdk
echo "=== ndk dirs ==="
ls "$SDK/ndk" 2>/dev/null || echo "(no ndk dir)"
echo "=== owner ==="
ls -ld "$SDK" "$SDK/cmdline-tools/latest" 2>/dev/null
echo "=== licenses ==="
ls "$SDK/licenses" 2>/dev/null
echo "=== whoami ==="
whoami
echo "=== flutter ndkVersion ==="
grep -r "ndkVersion\|ndk" /home/<USER>/sdk/flutter/packages/flutter_tools/gradle/src/main/groovy/flutter.groovy 2>/dev/null | grep -i "ndkVersion" | head -3
