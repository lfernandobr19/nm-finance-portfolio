#!/usr/bin/env bash
SDK=/home/<USER>/learning-agent/data/cache/android-sdk
echo "=== SDK root ==="
ls "$SDK"
echo "=== platforms ==="
ls "$SDK/platforms" 2>/dev/null
echo "=== build-tools ==="
ls "$SDK/build-tools" 2>/dev/null
echo "=== cmdline-tools ==="
ls "$SDK/cmdline-tools" 2>/dev/null
