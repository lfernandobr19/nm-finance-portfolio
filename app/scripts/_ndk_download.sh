#!/usr/bin/env bash
set -uo pipefail
NDK_DIR=/home/<USER>/ndk
mkdir -p "$NDK_DIR"
cd "$NDK_DIR" || exit 1

ZIP=android-ndk-r28c-linux.zip
if [ ! -d "android-ndk-r28c" ]; then
  echo "=== downloading $ZIP ==="
  curl -L --fail --retry 3 -o "$ZIP" "https://dl.google.com/android/repository/$ZIP"
  echo "=== extracting ==="
  unzip -q "$ZIP"
  rm -f "$ZIP"
fi

echo "=== version ==="
cat android-ndk-r28c/source.properties 2>/dev/null | grep -i "Pkg.Revision"
echo "NDK_READY /home/<USER>/ndk/android-ndk-r28c"
