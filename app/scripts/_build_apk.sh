#!/usr/bin/env bash
export PATH="/home/<USER>/sdk/flutter/bin:$PATH"
export ANDROID_HOME="/home/<USER>/android-sdk"
export ANDROID_SDK_ROOT="$ANDROID_HOME"
export ANDROID_NDK_HOME="/home/<USER>/ndk/android-ndk-r28c"
cd /home/<USER>/Projects/fiidesk/app || exit 1

echo "=== flutter pub get ==="
flutter pub get 2>&1 | tail -3

echo "=== build apk release ==="
flutter build apk --release 2>&1 | tail -60

echo "=== artifact ==="
APK=build/app/outputs/flutter-apk/app-release.apk
if [ -f "$APK" ]; then
  VERSION=$(grep '^version:' pubspec.yaml | sed 's/version: *//')
  DEST="/home/<USER>/ravenna-artifacts/fiidesk/NM-Finance-${VERSION%%+*}.apk"
  cp "$APK" "$DEST"
  ls -la "$DEST"
  echo "APK_OK $DEST"
else
  echo "APK_MISSING"
  exit 1
fi
