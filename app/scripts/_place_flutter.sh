#!/usr/bin/env bash
set -euo pipefail
SRC=/tmp/flutter_sync
APP=/home/<USER>/Projects/fiidesk/app

cp "$SRC/pubspec.yaml"                       "$APP/pubspec.yaml"
cp "$SRC/settings.gradle.kts"                "$APP/android/settings.gradle.kts"
cp "$SRC/build.gradle.kts"                   "$APP/android/app/build.gradle.kts"
cp "$SRC/fcm_service.dart"                   "$APP/lib/core/fcm_service.dart"
cp "$SRC/local_notifications.dart"           "$APP/lib/core/local_notifications.dart"
cp "$SRC/market_hours.dart"                  "$APP/lib/core/market_hours.dart"
cp "$SRC/notification_copy.dart"             "$APP/lib/core/notification_copy.dart"
cp "$SRC/suggestion_event_factory.dart"      "$APP/lib/core/suggestion_event_factory.dart"
cp "$SRC/suggestion_poller.dart"             "$APP/lib/core/suggestion_poller.dart"
cp "$SRC/main.dart"                          "$APP/lib/main.dart"
cp "$SRC/fcm_service_test.dart"              "$APP/test/fcm_service_test.dart"
cp "$SRC/notification_copy_test.dart"        "$APP/test/notification_copy_test.dart"
cp "$SRC/suggestion_event_factory_test.dart" "$APP/test/suggestion_event_factory_test.dart"

echo "flutter files placed OK"
