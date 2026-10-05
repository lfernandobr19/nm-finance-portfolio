import 'package:flutter/foundation.dart';
import 'package:local_notifier/local_notifier.dart';

/// Native desktop toast notifications via `local_notifier` (Windows/macOS/
/// Linux). Android/web keep their own channels (FCM + flutter_local_notifications
/// + web notifications), so this service is a no-op outside desktop.
class DesktopNotifier {
  DesktopNotifier._();

  static final DesktopNotifier instance = DesktopNotifier._();

  bool _ready = false;
  bool _isDesktop = false;

  Future<void> setup() async {
    if (_ready) return;
    if (kIsWeb) return;
    _isDesktop = defaultTargetPlatform == TargetPlatform.windows ||
        defaultTargetPlatform == TargetPlatform.macOS ||
        defaultTargetPlatform == TargetPlatform.linux;
    if (!_isDesktop) return;
    try {
      await localNotifier.setup(appName: 'NM Finance');
      _ready = true;
    } catch (_) {
      _ready = false;
    }
  }

  Future<void> show({
    required String title,
    required String body,
    VoidCallback? onClick,
  }) async {
    await setup();
    if (!_ready) return;
    final notification = LocalNotification(title: title, body: body);
    if (onClick != null) notification.onClick = onClick;
    try {
      await notification.show();
    } catch (_) {
      // Native toast failure never blocks the in-app center.
    }
  }
}
