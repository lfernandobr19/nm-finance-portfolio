import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'api_client.dart';
import 'local_notifications.dart';

/// Background isolate handler. With a `notification` payload present the FCM
/// SDK auto-displays the tray notification in background/terminated states, so
/// this handler only initializes Firebase and stays minimal (no duplicate UI).
@pragma('vm:entry-point')
Future<void> firebaseMessagingBackgroundHandler(RemoteMessage message) async {
  await Firebase.initializeApp();
}

/// Firebase Cloud Messaging push: token registration + foreground display.
class FcmService {
  FcmService._();

  static final instance = FcmService._();

  bool _ready = false;
  ApiClient? _api;

  Future<void> init({ApiClient? api}) async {
    if (_ready) return;
    _api = api;
    try {
      if (kIsWeb) {
        return; // FCM push is Android-only here (web uses polling + web notifications).
      }
      if (!Platform.isAndroid) {
        return; // No FCM on desktop — polling + local toasts instead.
      }

      await Firebase.initializeApp();
      final messaging = FirebaseMessaging.instance;
      await messaging.requestPermission(alert: true, badge: true, sound: true);

      FirebaseMessaging.onMessage.listen(_onMessage);
      FirebaseMessaging.onMessageOpenedApp.listen(_onOpened);
      FirebaseMessaging.onBackgroundMessage(firebaseMessagingBackgroundHandler);
      messaging.onTokenRefresh.listen((_) => registerToken());

      await registerToken();
      await _handleInitialMessage();
      _ready = true;
    } catch (_) {
      // Firebase may be absent (no google-services.json) — degrade to polling.
      _ready = false;
    }
  }

  Future<void> registerToken() async {
    if (kIsWeb) return;
    final api = _api;
    if (api == null || api.accessToken == null) return;
    try {
      final token = await FirebaseMessaging.instance.getToken();
      if (token == null || token.isEmpty) return;
      await api.post('/devices', {'token': token, 'platform': _platform()});
    } catch (_) {
      // Best-effort: polling still covers foreground notifications.
    }
  }

  static String _platform() {
    if (kIsWeb) return 'web';
    if (Platform.isIOS) return 'ios';
    return 'android';
  }

  void _onMessage(RemoteMessage message) {
    debugPrint(
      '[fcm] onMessage notification=${message.notification?.title ?? 'null'} / '
      '${message.notification?.body ?? 'null'} data=${message.data}',
    );
    var body = message.notification?.body ?? '';
    if (body.trim().isEmpty) {
      body = _fallbackBody(message.data);
    }
    LocalNotifications.instance.showFcmNotification(
      title: message.notification?.title ?? 'NM Finance',
      body: body,
      payload: payloadFromData(message.data),
      isExecution: message.data['kind'] == 'order_filled',
    );
  }

  static String _fallbackBody(Map<String, dynamic> data) {
    final ticker = (data['ticker'] ?? '').toString();
    final kind = (data['kind'] ?? '').toString();
    final alert = (data['alert'] ?? '').toString();
    final parts = <String>[
      if (ticker.isNotEmpty) ticker,
      if (kind.isNotEmpty) kind,
      if (alert.isNotEmpty) alert,
    ];
    if (parts.isEmpty) {
      return 'Nova notificação — abra o app para ver os detalhes.';
    }
    return parts.join(' · ');
  }

  void _onOpened(RemoteMessage message) {
    debugPrint('[fcm] onMessageOpenedApp data=${message.data}');
    unawaited(_storePendingOpen(message.data));
  }

  Future<void> _handleInitialMessage() async {
    final initial = await FirebaseMessaging.instance.getInitialMessage();
    if (initial != null) {
      await _storePendingOpen(initial.data);
    }
  }

  static Future<void> _storePendingOpen(Map<String, dynamic> data) async {
    final accountId = data['account_id'];
    final suggestionId = data['suggestion_id'];
    debugPrint('[fcm] _storePendingOpen accountId=$accountId suggestionId=$suggestionId');
    if (accountId == null || suggestionId == null) return;
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(
      'pending_open_suggestion',
      jsonEncode({'accountId': accountId, 'suggestionId': suggestionId}),
    );
  }

  /// Navigation payload compatible with [LocalNotifications.handleActionResponse].
  static String payloadFromData(Map<String, dynamic> data) {
    final accountId = (data['account_id'] ?? '').toString();
    final suggestionId = (data['suggestion_id'] ?? '').toString();
    final status = (data['status'] ?? '').toString();
    final kind = (data['kind'] ?? '').toString();
    final positionId = (data['position_id'] ?? '').toString();
    final alert = (data['alert'] ?? '').toString();
    final review = status == 'review_required' ? '1' : '0';
    final String payload;
    if (kind == 'order_filled' && positionId.isNotEmpty) {
      payload = '$accountId|$suggestionId|$positionId|filled';
    } else if (kind == 'rotation' && positionId.isNotEmpty) {
      payload = '$accountId|$suggestionId|$positionId|rotation';
    } else if (positionId.isNotEmpty && alert.isNotEmpty) {
      payload = '$accountId|$suggestionId|$positionId|$alert';
    } else {
      payload = '$accountId|$suggestionId|$review';
    }
    debugPrint('[fcm] payloadFromData kind="$kind" alert="$alert" -> "$payload"');
    return payload;
  }
}
