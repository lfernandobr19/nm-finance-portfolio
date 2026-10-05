import 'package:fiidesk/core/notification_center.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

Future<void> _flush() => Future<void>.delayed(const Duration(milliseconds: 1));

void main() {
  setUp(() {
    SharedPreferences.setMockInitialValues({});
  });

  group('NotificationCenter', () {
    test('starts empty', () async {
      final center = NotificationCenter();
      await center.load();
      expect(center.loaded, isTrue);
      expect(center.items, isEmpty);
      expect(center.unreadCount, 0);
    });

    test('push inserts newest first and counts unread', () async {
      final center = NotificationCenter();
      await center.load();

      center.push(title: 'A', body: 'a', kind: AppNotificationKind.suggestion);
      center.push(title: 'B', body: 'b', kind: AppNotificationKind.exitAlert);

      expect(center.items, hasLength(2));
      expect(center.items.first.title, 'B');
      expect(center.unreadCount, 2);
    });

    test('markRead and markAllRead update unread count', () async {
      final center = NotificationCenter();
      await center.load();
      center.push(title: 'A', body: 'a');
      center.push(title: 'B', body: 'b');
      final firstId = center.items.first.id;

      center.markRead(firstId);
      expect(center.unreadCount, 1);
      expect(center.items.first.read, isTrue);

      center.markAllRead();
      expect(center.unreadCount, 0);
    });

    test('clear removes everything', () async {
      final center = NotificationCenter();
      await center.load();
      center.push(title: 'A', body: 'a');
      center.clear();
      expect(center.items, isEmpty);
      expect(center.unreadCount, 0);
    });

    test('caps the list at 50 entries', () async {
      final center = NotificationCenter();
      await center.load();
      for (var i = 0; i < 60; i++) {
        center.push(title: 'T$i', body: 'b$i');
      }
      expect(center.items, hasLength(50));
      expect(center.items.first.title, 'T59');
    });

    test('persists and restores across instances', () async {
      final center = NotificationCenter();
      await center.load();
      center.push(
        title: 'Sugestão',
        body: 'PETR4',
        kind: AppNotificationKind.suggestion,
        accountId: 'acc1',
        suggestionId: 'sug1',
      );
      center.push(title: 'Alerta', body: 'STOP', kind: AppNotificationKind.exitAlert);
      // Newest first: [Alerta, Sugestão]. Mark the suggestion as read.
      center.markRead(center.items.last.id);
      await _flush();

      final reloaded = NotificationCenter();
      await reloaded.load();
      expect(reloaded.items, hasLength(2));
      expect(reloaded.items.first.title, 'Alerta');
      final suggestion = reloaded.items.last;
      expect(suggestion.title, 'Sugestão');
      expect(suggestion.accountId, 'acc1');
      expect(suggestion.suggestionId, 'sug1');
      expect(suggestion.read, isTrue);
      expect(reloaded.unreadCount, 1);
    });

    test('tolerates corrupt stored JSON', () async {
      SharedPreferences.setMockInitialValues({
        'inapp_notifications_v1': 'not-json',
      });
      final center = NotificationCenter();
      await center.load();
      expect(center.loaded, isTrue);
      expect(center.items, isEmpty);
    });
  });

  group('AppNotification.fromJson', () {
    test('round-trips fields', () {
      final n = AppNotification(
        id: '1',
        title: 't',
        body: 'b',
        kind: AppNotificationKind.execution,
        at: DateTime(2026, 8, 31, 10),
        accountId: 'a',
        suggestionId: 's',
        positionId: 'p',
      );
      final restored = AppNotification.fromJson(n.toJson());
      expect(restored.id, '1');
      expect(restored.title, 't');
      expect(restored.kind, AppNotificationKind.execution);
      expect(restored.accountId, 'a');
      expect(restored.positionId, 'p');
    });
  });
}
