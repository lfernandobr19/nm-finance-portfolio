// ignore_for_file: avoid_web_libraries_in_flutter, deprecated_member_use
import 'dart:html' as html;

Future<void> requestWebNotifyPermission() async {
  try {
    if (html.Notification.supported) {
      await html.Notification.requestPermission();
    }
  } catch (_) {}
}

Future<void> showWebNotification(String title, String body) async {
  try {
    if (!html.Notification.supported) return;
    if (html.Notification.permission != 'granted') {
      await html.Notification.requestPermission();
    }
    if (html.Notification.permission == 'granted') {
      html.Notification(title, body: body, icon: 'icons/Icon-192.png');
    }
  } catch (_) {}
}
