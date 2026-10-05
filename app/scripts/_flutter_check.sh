#!/usr/bin/env bash
export PATH="/home/<USER>/sdk/flutter/bin:$PATH"
cd /home/<USER>/Projects/fiidesk/app || exit 1

echo "=== pub get ==="
flutter pub get 2>&1 | tail -20

echo "=== analyze ==="
flutter analyze 2>&1 | tail -50

echo "=== test ==="
flutter test 2>&1 | tail -50

echo "=== done ==="
