#!/usr/bin/env bash
echo "=== learning-agent tree (top 2) ==="
ls -la /home/<USER>/learning-agent 2>/dev/null
echo "=== learning-agent/data ==="
ls -la /home/<USER>/learning-agent/data 2>/dev/null
echo "=== learning-agent/data/cache ==="
ls -la /home/<USER>/learning-agent/data/cache 2>/dev/null
echo "=== any flutter in learning-agent ==="
ls -d /home/<USER>/learning-agent/*/flutter /home/<USER>/learning-agent/flutter 2>/dev/null
echo "=== shell history hints (apk build) ==="
grep -riE "flutter build|build apk|NDK" /home/<USER>/.bash_history 2>/dev/null | tail -20
