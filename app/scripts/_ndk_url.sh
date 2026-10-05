#!/usr/bin/env bash
for v in r28 r28b r28c; do
  url="https://dl.google.com/android/repository/android-ndk-${v}-linux.zip"
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 -I "$url")
  echo "$v -> $code ($url)"
done
