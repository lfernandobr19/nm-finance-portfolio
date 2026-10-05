import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../../core/api_client.dart';
import '../../core/app_navigator.dart';
import '../../core/auth_state.dart';
import '../../core/desktop_notifier.dart';
import '../../core/fcm_service.dart';
import '../../core/local_notifications.dart';
import '../../core/notification_center.dart';
import '../../core/notification_copy.dart';
import '../../core/position_poller.dart';
import '../../core/suggestion_poller.dart';
import '../notifications/notifications_screen.dart';
import '../suggestions/suggestion_detail_page.dart';
import 'desktop_destination.dart';

/// Desktop-first shell: left `NavigationRail` + content area, preserving tab
/// state via `StatefulShellRoute.indexedStack`. Owns the global pollers and
/// notification wiring (once per app lifecycle).
class DesktopShell extends StatefulWidget {
  const DesktopShell({super.key, required this.shell});

  final StatefulNavigationShell shell;

  @override
  State<DesktopShell> createState() => _DesktopShellState();
}

class _DesktopShellState extends State<DesktopShell> {
  SuggestionPoller? _poller;
  PositionPoller? _positionPoller;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _bootstrapServices());
  }

  void _bootstrapServices() {
    final api = context.read<ApiClient>();
    final center = context.read<NotificationCenter>();
    LocalNotifications.instance.persistApiBaseUrl(api.baseUrl);
    unawaited(FcmService.instance.init(api: api));
    unawaited(DesktopNotifier.instance.setup());
    LocalNotifications.instance.onDesktopPending = (count) {
      if (!mounted) return;
      final msg = count == 1
          ? '1 nova sugestão pendente'
          : '$count sugestões pendentes';
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(msg)));
    };
    LocalNotifications.instance.onActionMessage = (msg) {
      final nav = appNavigatorKey.currentContext;
      if (nav == null) return;
      ScaffoldMessenger.of(nav).showSnackBar(SnackBar(content: Text(msg)));
    };
    LocalNotifications.instance.onOpenSuggestion = _openSuggestion;
    _poller = SuggestionPoller(api);
    _poller!.onPendingChanged = LocalNotifications.instance.onPendingChanged;
    _poller!.onNewSuggestions = (events) {
      for (final e in events) {
        final copy = buildSuggestionNotificationCopy(e);
        center.push(
          title: copy.title,
          body: copy.summary,
          kind: AppNotificationKind.suggestion,
          accountId: e.accountId,
          suggestionId: e.id,
        );
        DesktopNotifier.instance.show(
          title: copy.title,
          body: copy.summary,
          onClick: () =>
              _openSuggestion(accountId: e.accountId, suggestionId: e.id),
        );
      }
    };
    _poller!.start();
    _positionPoller = PositionPoller(api);
    _positionPoller!.onExitAlerts = (events) {
      for (final e in events) {
        final title =
            'NM Finance · ${PositionPoller.alertTitle(e.alert, e.ticker)}';
        final body = PositionPoller.alertBody(e);
        center.push(
          title: title,
          body: body,
          kind: AppNotificationKind.exitAlert,
          accountId: e.accountId,
          suggestionId: e.suggestionId,
          positionId: e.positionId,
        );
        DesktopNotifier.instance.show(title: title, body: body);
      }
    };
    _positionPoller!.start();
    unawaited(_consumePendingOpen());
  }

  Future<void> _consumePendingOpen() async {
    final prefs = await SharedPreferences.getInstance();
    final raw = prefs.getString('pending_open_suggestion');
    if (raw == null) return;
    await prefs.remove('pending_open_suggestion');
    try {
      final map = jsonDecode(raw) as Map<String, dynamic>;
      final accountId = map['accountId'] as String?;
      final suggestionId = map['suggestionId'] as String?;
      if (accountId != null && suggestionId != null) {
        _openSuggestion(accountId: accountId, suggestionId: suggestionId);
      }
    } catch (_) {}
  }

  void _openSuggestion({
    required String accountId,
    required String suggestionId,
  }) {
    final nav = appNavigatorKey.currentState;
    if (nav == null) return;
    nav.push(
      MaterialPageRoute(
        builder: (_) => SuggestionDetailPage(
          accountId: accountId,
          suggestionId: suggestionId,
          myRole: 'operator',
        ),
      ),
    );
  }

  void _openNotifications() {
    final nav = appNavigatorKey.currentState;
    if (nav == null) return;
    nav.push(
      MaterialPageRoute(
        builder: (_) => NotificationsScreen(
          onOpenSuggestion: _openSuggestion,
        ),
      ),
    );
  }

  @override
  void dispose() {
    LocalNotifications.instance.onDesktopPending = null;
    LocalNotifications.instance.onOpenSuggestion = null;
    LocalNotifications.instance.onActionMessage = null;
    _poller?.stop();
    _positionPoller?.stop();
    super.dispose();
  }

  void _logout() {
    final auth = context.read<AuthState>();
    auth.logout(); // router redirect handles the login screen.
  }

  @override
  Widget build(BuildContext context) {
    final unread = context.watch<NotificationCenter>().unreadCount;
    return Scaffold(
      body: Row(
        children: [
          NavigationRail(
            selectedIndex: widget.shell.currentIndex,
            onDestinationSelected: (index) => _onSelect(index),
            labelType: NavigationRailLabelType.all,
            leading: Padding(
              padding: const EdgeInsets.symmetric(vertical: 12),
              child: Column(
                children: [
                  Icon(
                    Icons.candlestick_chart,
                    size: 28,
                    color: Theme.of(context).colorScheme.primary,
                  ),
                  const SizedBox(height: 4),
                  Text(
                    'NM Finance',
                    style: Theme.of(context).textTheme.labelSmall,
                    textAlign: TextAlign.center,
                  ),
                ],
              ),
            ),
            trailing: Expanded(
              child: Align(
                alignment: Alignment.bottomCenter,
                child: Padding(
                  padding: const EdgeInsets.only(bottom: 12),
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      IconButton(
                        tooltip: 'Notificações',
                        icon: Badge(
                          isLabelVisible: unread > 0,
                          label: Text('$unread'),
                          child: const Icon(Icons.notifications_outlined),
                        ),
                        onPressed: _openNotifications,
                      ),
                      IconButton(
                        tooltip: 'Sair',
                        icon: const Icon(Icons.logout),
                        onPressed: _logout,
                      ),
                    ],
                  ),
                ),
              ),
            ),
            destinations: [
              for (final d in desktopDestinations)
                NavigationRailDestination(
                  icon: Icon(d.icon),
                  selectedIcon: Icon(d.selectedIcon),
                  label: Text(d.label),
                ),
            ],
          ),
          const VerticalDivider(thickness: 1, width: 1),
          Expanded(child: widget.shell),
        ],
      ),
    );
  }

  void _onSelect(int index) {
    widget.shell.goBranch(
      index,
      initialLocation: index == widget.shell.currentIndex,
    );
  }
}
