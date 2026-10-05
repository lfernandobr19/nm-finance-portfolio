#!/usr/bin/env bash
echo "=== disk ==="
df -h /home/lfernando | tail -1
echo "=== network to dl.google.com ==="
curl -sI --max-time 10 https://dl.google.com/android/repository/android-ndk-r29-linux.zip 2>&1 | head -5
echo "=== unzip available ==="
which unzip 2>/dev/null || echo "no unzip"
echo "=== existing ndk home ==="
ls -d /home/<USER>/ndk 2>/dev/null || echo "(no ~/ndk)"
