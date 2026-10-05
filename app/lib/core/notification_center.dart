import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Category of an in-app notification, used for the leading icon.
enum AppNotificationKind {
  suggestion,
  exitAlert,
  execution,
  info,
}

/// A single in-app notification entry (also mirrored to native toasts on
/// desktop). Persisted as JSON so the center survives app restarts.
class AppNotification {
  AppNotification({
    required this.id,
    required this.title,
    required this.body,
    required this.kind,
    required this.at,
    this.accountId,
    this.suggestionId,
    this.positionId,
    this.read = false,
  });

  final String id;
  final String title;
  final String body;
  final AppNotificationKind kind;
  final DateTime at;
  final String? accountId;
  final String? suggestionId;
  final String? positionId;
  bool read;

  Map<String, dynamic> toJson() => {
        'id': id,
        'title': title,
        'body': body,
        'kind': kind.name,
        'at': at.toIso8601String(),
        'account_id': accountId,
        'suggestion_id': suggestionId,
        'position_id': positionId,
        'read': read,
      };

  factory AppNotification.fromJson(Map<String, dynamic> json) =>
      AppNotification(
        id: json['id'] as String? ?? '',
        title: json['title'] as String? ?? '',
        body: json['body'] as String? ?? '',
        kind: AppNotificationKind.values.firstWhere(
          (k) => k.name == json['kind'],
          orElse: () => AppNotificationKind.info,
        ),
        at: DateTime.tryParse(json['at'] as String? ?? '') ?? DateTime.now(),
        accountId: json['account_id'] as String?,
        suggestionId: json['suggestion_id'] as String?,
        positionId: json['position_id'] as String?,
        read: json['read'] as bool? ?? false,
      );
}

/// In-app notification store (unread count, list, mark-read/clear) backed by
/// [SharedPreferences]. Provided app-wide so the shell can push and the
/// notifications screen can render.
class NotificationCenter extends ChangeNotifier {
  static const _prefsKey = 'inapp_notifications_v1';
  static const _maxItems = 50;

  static int _idSeq = 0;

  final List<AppNotification> _items = [];
  bool _loaded = false;

  bool get loaded => _loaded;

  List<AppNotification> get items => List.unmodifiable(_items);

  int get unreadCount => _items.where((n) => !n.read).length;

  Future<void> load() async {
    _items.clear();
    try {
      final prefs = await SharedPreferences.getInstance();
      final raw = prefs.getString(_prefsKey);
      if (raw != null) {
        final list = jsonDecode(raw) as List;
        for (final e in list) {
          _items.add(
              AppNotification.fromJson((e as Map).cast<String, dynamic>()));
        }
      }
    } catch (_) {
      // Corrupt/absent storage falls back to an empty center.
    }
    _loaded = true;
    notifyListeners();
  }

  void push({
    required String title,
    required String body,
    AppNotificationKind kind = AppNotificationKind.info,
    String? accountId,
    String? suggestionId,
    String? positionId,
  }) {
    _items.insert(
      0,
      AppNotification(
        id: '${DateTime.now().microsecondsSinceEpoch}-${_idSeq++}',
        title: title,
        body: body,
        kind: kind,
        at: DateTime.now(),
        accountId: accountId,
        suggestionId: suggestionId,
        positionId: positionId,
      ),
    );
    if (_items.length > _maxItems) {
      _items.removeRange(_maxItems, _items.length);
    }
    notifyListeners();
    _save();
  }

  void markRead(String id) {
    for (final n in _items) {
      if (n.id == id && !n.read) {
        n.read = true;
        notifyListeners();
        _save();
        break;
      }
    }
  }

  void markAllRead() {
    var changed = false;
    for (final n in _items) {
      if (!n.read) {
        n.read = true;
        changed = true;
      }
    }
    if (changed) {
      notifyListeners();
      _save();
    }
  }

  void clear() {
    if (_items.isEmpty) return;
    _items.clear();
    notifyListeners();
    _save();
  }

  Future<void> _save() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      await prefs.setString(
        _prefsKey,
        jsonEncode(_items.map((n) => n.toJson()).toList()),
      );
    } catch (_) {
      // Best-effort persistence.
    }
  }
}
