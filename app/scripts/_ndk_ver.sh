#!/usr/bin/env bash
echo "=== flutter gradle_utils ndkVersion ==="
grep -n "ndkVersion" /home/<USER>/sdk/flutter/packages/flutter_tools/lib/src/android/gradle_utils.dart 2>/dev/null | head -5
echo "=== resolved flutter.ndkVersion (via flutter tool constant) ==="
grep -rn "templateAndroidNdkVersion\|ndkVersion =" /home/<USER>/sdk/flutter/packages/flutter_tools/lib/src/android/gradle_utils.dart 2>/dev/null | head -5
