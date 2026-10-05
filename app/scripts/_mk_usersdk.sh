#!/usr/bin/env bash
set -euo pipefail
SRC=/home/<USER>/learning-agent/data/cache/android-sdk
DST=/home/<USER>/android-sdk

mkdir -p "$DST"
for d in platforms build-tools platform-tools cmdline-tools licenses; do
  if [ -e "$SRC/$d" ] && [ ! -e "$DST/$d" ]; then
    ln -s "$SRC/$d" "$DST/$d"
  fi
done

# NDK at the exact version AGP expects (flutter.ndkVersion = 28.2.13676358).
mkdir -p "$DST/ndk"
if [ ! -e "$DST/ndk/28.2.13676358" ]; then
  ln -s /home/<USER>/ndk/android-ndk-r28c "$DST/ndk/28.2.13676358"
fi

echo "=== user SDK layout ==="
ls -la "$DST"
echo "=== ndk version link ==="
ls -la "$DST/ndk/"
