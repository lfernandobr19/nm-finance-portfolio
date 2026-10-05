import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

import 'notification_copy.dart';
import 'suggestion_poller.dart';
import 'position_poller.dart';
import 'token_store.dart';
import 'web_notify.dart';

typedef PendingCallback = void Function(int count);
typedef NotificationNavCallback = void Function({
  required String accountId,
  required String suggestionId,
});
typedef NotificationMessageCallback = void Function(String message);

/// Top-level background handler for notification action buttons.
@pragma('vm:entry-point')
void notificationBackgroundHandler(NotificationResponse response) {
  // Fire-and-forget; isolate has no Flutter UI.
  LocalNotifications.handleActionResponse(response, fromBackground: true);
}

/// Notifications from the NM Finance app itself (Android system tray + browser on Windows web).
class LocalNotifications {
  LocalNotifications._();
  static final instance = LocalNotifications._();

  static const _channelId = 'fiidesk_suggestions';
  static const _exitChannelId = 'fiidesk_exit_alerts';
  static const _execChannelId = 'fiidesk_executions';
  static const pendingCountKey = 'pending_notify_count';

  final _plugin = FlutterLocalNotificationsPlugin();
  bool _ready = false;
  int _notifSeq = 2000;
  PendingCallback? onDesktopPending;
  NotificationNavCallback? onOpenSuggestion;
  NotificationMessageCallback? onActionMessage;

  Future<void> init() async {
    if (_ready) return;
    try {
      if (kIsWeb) {
        await requestWebNotifyPermission();
        _ready = true;
        return;
      }
      const android = AndroidInitializationSettings('@mipmap/ic_launcher');
      const initSettings = InitializationSettings(android: android);
      await _plugin.initialize(
        initSettings,
        onDidReceiveNotificationResponse: (r) => handleActionResponse(r),
        onDidReceiveBackgroundNotificationResponse: notificationBackgroundHandler,
      );
      final androidPlugin = _plugin
          .resolvePlatformSpecificImplementation<AndroidFlutterLocalNotificationsPlugin>();
      await androidPlugin?.createNotificationChannel(
        const AndroidNotificationChannel(
          _channelId,
          'Sugestões',
          description: 'Novas sugestões NM Finance',
          importance: Importance.high,
        ),
      );
      await androidPlugin?.createNotificationChannel(
        const AndroidNotificationChannel(
          _exitChannelId,
          'Alertas de saída',
          description: 'Stop, alvo, recuperação e trailing em posições abertas',
          importance: Importance.high,
        ),
      );
      await androidPlugin?.createNotificationChannel(
        const AndroidNotificationChannel(
          _execChannelId,
          'Execuções',
          description: 'Compra automática efetuada',
          importance: Importance.high,
        ),
      );
      await androidPlugin?.requestNotificationsPermission();
      _ready = true;

      final launch = await _plugin.getNotificationAppLaunchDetails();
      if (launch?.didNotificationLaunchApp == true &&
          launch!.notificationResponse != null) {
        await handleActionResponse(launch.notificationResponse!);
      }
    } catch (_) {
      _ready = false;
    }
  }

  Future<void> persistApiBaseUrl(String baseUrl) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('api_base_url', baseUrl);
  }

  static Future<void> handleActionResponse(
    NotificationResponse response, {
    bool fromBackground = false,
  }) async {
    final payload = response.payload;
    if (payload == null || payload.isEmpty) return;
    final parts = payload.split('|');
    if (parts.length < 3) return;
    final accountId = parts[0];
    final suggestionId = parts[1];
    final action = response.actionId;
    debugPrint(
      '[notif] handleActionResponse payload="$payload" accountId="$accountId" '
      'suggestionId="$suggestionId" action="$action" fromBackground=$fromBackground',
    );

    // Exit alert: accountId|suggestionId|positionId|alert|extra
    if (parts.length >= 4 && parts[2] != '0' && parts[2] != '1') {
      final positionId = parts[2];

      if (action == 'close_market') {
        final ok = await _postCloseMarket(accountId, positionId);
        if (!fromBackground) {
          instance.onActionMessage?.call(
            ok ? 'Posição fechada' : 'Falha ao fechar',
          );
        }
        return;
      }
      if (action == 'extend_review') {
        final ok = await _postExtendReview(accountId, positionId);
        if (!fromBackground) {
          instance.onActionMessage?.call(
            ok ? 'Review estendido +3 dias' : 'Falha ao estender',
          );
        }
        return;
      }
      if (action == 'rotation_keep') {
        final newSug = parts.length >= 5 ? parts[4] : '';
        if (newSug.isNotEmpty) {
          await _postRotationDismiss(accountId, positionId, newSug);
        }
        if (!fromBackground) {
          instance.onActionMessage?.call('Rotação ignorada');
        }
        return;
      }
      if (action == 'rotation_swap') {
        final newSug = parts.length >= 5 ? parts[4] : suggestionId;
        final closed = await _postCloseMarket(accountId, positionId);
        if (!fromBackground) {
          instance.onActionMessage?.call(
            closed ? 'Fechado — abra a nova sugestão' : 'Falha ao fechar',
          );
          if (closed && newSug.isNotEmpty) {
            instance.onOpenSuggestion?.call(
              accountId: accountId,
              suggestionId: newSug,
            );
          }
        } else {
          final prefs = await SharedPreferences.getInstance();
          await prefs.setString(
            'pending_open_suggestion',
            jsonEncode({'accountId': accountId, 'suggestionId': newSug}),
          );
        }
        return;
      }

      if (!fromBackground) {
        instance.onOpenSuggestion?.call(
          accountId: accountId,
          suggestionId: suggestionId,
        );
      } else {
        final prefs = await SharedPreferences.getInstance();
        await prefs.setString(
          'pending_open_suggestion',
          jsonEncode({'accountId': accountId, 'suggestionId': suggestionId}),
        );
      }
      return;
    }

    final review = parts[2] == '1';

    if (action == 'approve' && !review) {
      final ok = await _postSuggestionAction(accountId, suggestionId, approve: true);
      if (!fromBackground) {
        instance.onActionMessage?.call(
          ok ? 'Sugestão aprovada' : 'Falha ao aprovar',
        );
      }
      return;
    }
    if (action == 'reject') {
      final ok = await _postSuggestionAction(accountId, suggestionId, approve: false);
      if (!fromBackground) {
        instance.onActionMessage?.call(
          ok ? 'Sugestão rejeitada' : 'Falha ao rejeitar',
        );
      }
      return;
    }
    // tap, approve+review, or unknown → open detail
    if (accountId.trim().isEmpty || suggestionId.trim().isEmpty) {
      debugPrint('[notif] skip open: empty accountId/suggestionId');
      return;
    }
    if (!fromBackground) {
      instance.onOpenSuggestion?.call(
        accountId: accountId,
        suggestionId: suggestionId,
      );
    } else {
      final prefs = await SharedPreferences.getInstance();
      await prefs.setString(
        'pending_open_suggestion',
        jsonEncode({'accountId': accountId, 'suggestionId': suggestionId}),
      );
    }
  }

  static Future<bool> _postJson(
    String path, {
    Map<String, dynamic> body = const {},
  }) async {
    try {
      final token = await TokenStore().readAccess();
      final prefs = await SharedPreferences.getInstance();
      var base = prefs.getString('api_base_url') ??
          'http://<RAVENNA_TAILSCALE_IP>:8010/api/v1';
      if (base.endsWith('/')) base = base.substring(0, base.length - 1);
      if (token == null || token.isEmpty) return false;
      final uri = Uri.parse('$base$path');
      final resp = await http
          .post(
            uri,
            headers: {
              'Content-Type': 'application/json',
              'Authorization': 'Bearer $token',
            },
            body: jsonEncode(body),
          )
          .timeout(const Duration(seconds: 20));
      return resp.statusCode < 300;
    } catch (_) {
      return false;
    }
  }

  static Future<bool> _postCloseMarket(String accountId, String positionId) =>
      _postJson(
        '/accounts/$accountId/positions/$positionId/close',
        body: {'reason': 'market'},
      );

  static Future<bool> _postExtendReview(String accountId, String positionId) =>
      _postJson('/accounts/$accountId/positions/$positionId/extend-review');

  static Future<bool> _postRotationDismiss(
    String accountId,
    String positionId,
    String suggestionId,
  ) =>
      _postJson(
        '/accounts/$accountId/positions/$positionId/rotation/dismiss',
        body: {'suggestion_id': suggestionId},
      );

  static Future<bool> _postSuggestionAction(
    String accountId,
    String suggestionId, {
    required bool approve,
  }) async {
    try {
      final token = await TokenStore().readAccess();
      final prefs = await SharedPreferences.getInstance();
      var base = prefs.getString('api_base_url') ??
          'http://<RAVENNA_TAILSCALE_IP>:8010/api/v1';
      if (base.endsWith('/')) base = base.substring(0, base.length - 1);
      if (token == null || token.isEmpty) return false;
      final path = approve ? 'approve' : 'reject';
      final uri = Uri.parse('$base/accounts/$accountId/suggestions/$suggestionId/$path');
      final resp = await http
          .post(
            uri,
            headers: {
              'Content-Type': 'application/json',
              'Authorization': 'Bearer $token',
            },
            body: '{}',
          )
          .timeout(const Duration(seconds: 20));
      return resp.statusCode < 300;
    } catch (_) {
      return false;
    }
  }

  Future<void> onNewSuggestions(List<NewSuggestionEvent> events) async {
    if (!_ready) await init();
    for (final e in events) {
      final copy = buildSuggestionNotificationCopy(e);
      await _show(
        copy.title,
        copy.summary,
        bigBody: copy.bigBody,
        id: _notifSeq++,
        payload: e.toPayload(),
      );
    }
  }

  Future<void> showFcmNotification({
    required String title,
    required String body,
    required String payload,
    bool isExecution = false,
  }) async {
    if (!_ready) await init();
    if (!kIsWeb) {
      await _plugin.show(
        _notifSeq++,
        title,
        body,
        NotificationDetails(
          android: AndroidNotificationDetails(
            isExecution ? _execChannelId : _channelId,
            isExecution ? 'Execuções' : 'Sugestões',
            channelDescription: isExecution
                ? 'Compra automática efetuada'
                : 'Novas sugestões NM Finance',
            importance: Importance.high,
            priority: Priority.high,
            icon: '@mipmap/ic_launcher',
            styleInformation: BigTextStyleInformation(
              body,
              contentTitle: title,
            ),
          ),
        ),
        payload: payload,
      );
    }
    await showWebNotification(title, body);
  }

  Future<void> onExitAlerts(List<ExitAlertEvent> events) async {
    if (!_ready) await init();
    for (final e in events) {
      final title = 'NM Finance · ${PositionPoller.alertTitle(e.alert, e.ticker)}';
      final body = PositionPoller.alertBody(e);
      await _showExit(
        title,
        body,
        alert: e.alert,
        id: _notifSeq++,
        payload: e.toPayload(),
      );
    }
  }

  List<AndroidNotificationAction> _exitActions(String alert) {
    switch (alert) {
      case 'time_review':
        return const [
          AndroidNotificationAction(
            'close_market',
            'Fechar agora',
            showsUserInterface: true,
            cancelNotification: true,
          ),
          AndroidNotificationAction(
            'extend_review',
            'Manter +3d',
            showsUserInterface: false,
            cancelNotification: true,
          ),
          AndroidNotificationAction(
            'view',
            'Ver posição',
            showsUserInterface: true,
            cancelNotification: true,
          ),
        ];
      case 'rotation':
        return const [
          AndroidNotificationAction(
            'rotation_swap',
            'Trocar',
            showsUserInterface: true,
            cancelNotification: true,
          ),
          AndroidNotificationAction(
            'rotation_keep',
            'Manter',
            showsUserInterface: false,
            cancelNotification: true,
          ),
          AndroidNotificationAction(
            'view',
            'Ver ficha',
            showsUserInterface: true,
            cancelNotification: true,
          ),
        ];
      default:
        return const [
          AndroidNotificationAction(
            'view',
            'Ver posição',
            showsUserInterface: true,
            cancelNotification: true,
          ),
        ];
    }
  }

  Future<void> _showExit(
    String title,
    String body, {
    required String alert,
    required int id,
    required String payload,
  }) async {
    if (!kIsWeb) {
      await _plugin.show(
        id,
        title,
        body,
        NotificationDetails(
          android: AndroidNotificationDetails(
            _exitChannelId,
            'Alertas de saída',
            channelDescription: 'Stop, alvo, observação, proteção e dia 14',
            importance: Importance.high,
            priority: Priority.high,
            icon: '@mipmap/ic_launcher',
            styleInformation: BigTextStyleInformation(
              body,
              contentTitle: title,
            ),
            actions: _exitActions(alert),
          ),
        ),
        payload: payload,
      );
    }
    await showWebNotification(title, body);
  }

  Future<void> onPendingChanged(int count) async {
    if (!_ready) await init();
    final prefs = await SharedPreferences.getInstance();
    await prefs.setInt(pendingCountKey, count);
    onDesktopPending?.call(count);
  }

  Future<void> _show(
    String title,
    String summary, {
    required String bigBody,
    required int id,
    required String payload,
  }) async {
    if (!kIsWeb) {
      await _plugin.show(
        id,
        title,
        summary,
        NotificationDetails(
          android: AndroidNotificationDetails(
            _channelId,
            'Sugestões',
            channelDescription: 'Novas sugestões NM Finance',
            importance: Importance.high,
            priority: Priority.high,
            icon: '@mipmap/ic_launcher',
            styleInformation: BigTextStyleInformation(
              bigBody,
              contentTitle: title,
              summaryText: summary,
            ),
            actions: const [
              AndroidNotificationAction(
                'approve',
                'Aprovar',
                showsUserInterface: true,
                cancelNotification: true,
              ),
              AndroidNotificationAction(
                'reject',
                'Rejeitar',
                showsUserInterface: true,
                cancelNotification: true,
              ),
            ],
          ),
        ),
        payload: payload,
      );
    }
    await showWebNotification(title, bigBody);
  }
}
