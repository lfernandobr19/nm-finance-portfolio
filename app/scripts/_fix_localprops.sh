#!/usr/bin/env bash
set -euo pipefail
LP=/home/<USER>/Projects/fiidesk/app/android/local.properties

grep -q '^flutter.sdk=' "$LP" || echo "flutter.sdk=/home/<USER>/sdk/flutter" >> "$LP"
sed -i 's#^flutter.sdk=.*#flutter.sdk=/home/<USER>/sdk/flutter#' "$LP"

grep -q '^sdk.dir=' "$LP" || echo "sdk.dir=/home/<USER>/android-sdk" >> "$LP"
sed -i 's#^sdk.dir=.*#sdk.dir=/home/<USER>/android-sdk#' "$LP"

echo "=== local.properties (final) ==="
cat "$LP"
