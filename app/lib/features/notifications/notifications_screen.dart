import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'package:provider/provider.dart';

import '../../core/notification_center.dart';
import '../desktop/master_detail.dart';

/// In-app notification center: recent suggestion/exit/execution events with an
/// unread badge, mark-all-read and clear actions. Tapping an item marks it read
/// and (when it carries an account + suggestion) opens the suggestion detail.
class NotificationsScreen extends StatelessWidget {
  const NotificationsScreen({super.key, required this.onOpenSuggestion});

  final void Function({
    required String accountId,
    required String suggestionId,
  }) onOpenSuggestion;

  static final _time = DateFormat('dd/MM HH:mm');

  @override
  Widget build(BuildContext context) {
    final center = context.watch<NotificationCenter>();
    return Scaffold(
      appBar: AppBar(
        title: const Text('Notificações'),
        actions: [
          if (center.unreadCount > 0)
            IconButton(
              tooltip: 'Marcar todas como lidas',
              onPressed: center.markAllRead,
              icon: const Icon(Icons.done_all),
            ),
          IconButton(
            tooltip: 'Limpar tudo',
            onPressed: center.clear,
            icon: const Icon(Icons.delete_outline),
          ),
        ],
      ),
      body: !center.loaded
          ? const PaneLoading()
          : center.items.isEmpty
              ? const PaneEmpty(
                  message: 'Nenhuma notificação por aqui ainda.',
                  icon: Icons.notifications_none,
                )
              : ListView.separated(
                  itemCount: center.items.length,
                  separatorBuilder: (_, __) => const Divider(height: 1),
                  itemBuilder: (context, i) => _NotificationTile(
                    notification: center.items[i],
                    onTap: () => _handleTap(context, center.items[i]),
                  ),
                ),
    );
  }

  void _handleTap(BuildContext context, AppNotification n) {
    context.read<NotificationCenter>().markRead(n.id);
    final accountId = n.accountId;
    final suggestionId = n.suggestionId;
    if (accountId != null && suggestionId != null) {
      onOpenSuggestion(accountId: accountId, suggestionId: suggestionId);
    }
  }
}

class _NotificationTile extends StatelessWidget {
  const _NotificationTile({required this.notification, required this.onTap});

  final AppNotification notification;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final n = notification;
    final scheme = Theme.of(context).colorScheme;
    return ListTile(
      leading: Icon(_iconFor(n.kind), color: _colorFor(n.kind)),
      title: Text(
        n.title,
        maxLines: 1,
        overflow: TextOverflow.ellipsis,
        style: TextStyle(
          fontWeight: n.read ? FontWeight.w500 : FontWeight.w700,
        ),
      ),
      subtitle: Text(
        n.body,
        maxLines: 2,
        overflow: TextOverflow.ellipsis,
      ),
      trailing: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        crossAxisAlignment: CrossAxisAlignment.end,
        children: [
          Text(
            NotificationsScreen._time.format(n.at.toLocal()),
            style: Theme.of(context).textTheme.labelSmall?.copyWith(
                  color: scheme.onSurfaceVariant,
                ),
          ),
          if (!n.read) ...[
            const SizedBox(height: 4),
            Container(
              width: 8,
              height: 8,
              decoration: BoxDecoration(
                color: scheme.primary,
                shape: BoxShape.circle,
              ),
            ),
          ],
        ],
      ),
      onTap: onTap,
    );
  }

  IconData _iconFor(AppNotificationKind kind) {
    switch (kind) {
      case AppNotificationKind.suggestion:
        return Icons.lightbulb_outline;
      case AppNotificationKind.exitAlert:
        return Icons.exit_to_app_outlined;
      case AppNotificationKind.execution:
        return Icons.check_circle_outline;
      case AppNotificationKind.info:
        return Icons.info_outline;
    }
  }

  Color _colorFor(AppNotificationKind kind) {
    switch (kind) {
      case AppNotificationKind.suggestion:
        return Colors.blue.shade700;
      case AppNotificationKind.exitAlert:
        return Colors.orange.shade800;
      case AppNotificationKind.execution:
        return Colors.green.shade700;
      case AppNotificationKind.info:
        return Colors.blueGrey.shade600;
    }
  }
}
