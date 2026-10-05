import 'dart:async';
import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:window_manager/window_manager.dart';

import 'app/desktop_app.dart';
import 'core/api_client.dart';
import 'core/app_navigator.dart';
import 'core/auth_state.dart';
import 'core/fcm_service.dart';
import 'core/local_notifications.dart';
import 'core/position_poller.dart';
import 'core/suggestion_poller.dart';
import 'core/theme_controller.dart';
import 'features/accounts/accounts_page.dart';
import 'features/auth/login_page.dart';
import 'features/dashboard/dashboard_page.dart';
import 'features/intelligence/studies_page.dart';
import 'features/suggestions/suggestion_detail_page.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await _initWindowManager();
  final isDesktop = defaultTargetPlatform == TargetPlatform.windows ||
      defaultTargetPlatform == TargetPlatform.macOS ||
      defaultTargetPlatform == TargetPlatform.linux;
  runApp(isDesktop ? const DesktopApp() : const FiiDeskApp());
  unawaited(_initNotificationsSafe());
}

/// Configures the native desktop window (Windows/macOS/Linux only). No-op on
/// Android/web so the mobile build is unaffected.
Future<void> _initWindowManager() async {
  if (defaultTargetPlatform != TargetPlatform.windows &&
      defaultTargetPlatform != TargetPlatform.macOS &&
      defaultTargetPlatform != TargetPlatform.linux) {
    return;
  }
  await windowManager.ensureInitialized();
  const options = WindowOptions(
    size: Size(1280, 800),
    minimumSize: Size(1100, 720),
    center: true,
    title: 'NM Finance',
  );
  windowManager.waitUntilReadyToShow(options, () async {
    await windowManager.show();
    await windowManager.focus();
  });
}

Future<void> _initNotificationsSafe() async {
  try {
    await LocalNotifications.instance.init();
  } catch (_) {}
}

class FiiDeskApp extends StatelessWidget {
  const FiiDeskApp({super.key});

  static const _seed = Color(0xFF1B4D3E);

  @override
  Widget build(BuildContext context) {
    return MultiProvider(
      providers: [
        Provider(create: (_) => ApiClient()),
        ChangeNotifierProvider(
          create: (ctx) => AuthState(ctx.read<ApiClient>())..bootstrap(),
        ),
        ChangeNotifierProvider(create: (_) => ThemeController()),
      ],
      child: Consumer<ThemeController>(
        builder: (context, themeCtrl, _) {
          return MaterialApp(
            navigatorKey: appNavigatorKey,
            title: 'NM Finance',
            debugShowCheckedModeBanner: false,
            themeMode: themeCtrl.mode,
            theme: ThemeData(
              colorScheme: ColorScheme.fromSeed(
                seedColor: _seed,
                brightness: Brightness.light,
              ),
              useMaterial3: true,
            ),
            darkTheme: ThemeData(
              colorScheme: ColorScheme.fromSeed(
                seedColor: _seed,
                brightness: Brightness.dark,
              ),
              useMaterial3: true,
            ),
            home: const _Root(),
          );
        },
      ),
    );
  }
}

class _Root extends StatelessWidget {
  const _Root();

  @override
  Widget build(BuildContext context) {
    final auth = context.watch<AuthState>();
    if (auth.loading) {
      return const Scaffold(body: Center(child: CircularProgressIndicator()));
    }
    if (!auth.isAuthenticated) {
      return const LoginPage();
    }
    return const _AuthenticatedShell();
  }
}

class _AuthenticatedShell extends StatefulWidget {
  const _AuthenticatedShell();

  @override
  State<_AuthenticatedShell> createState() => _AuthenticatedShellState();
}

class _AuthenticatedShellState extends State<_AuthenticatedShell> {
  SuggestionPoller? _poller;
  PositionPoller? _positionPoller;
  int _tabIndex = 0;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      final api = context.read<ApiClient>();
      LocalNotifications.instance.persistApiBaseUrl(api.baseUrl);
      unawaited(FcmService.instance.init(api: api));
      LocalNotifications.instance.onDesktopPending = (count) {
        if (!mounted) return;
        final msg = count == 1
            ? '1 nova sugestão pendente'
            : '$count sugestões pendentes';
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(msg)));
      };
      LocalNotifications.instance.onActionMessage = (msg) {
        final nav = appNavigatorKey.currentContext;
        if (nav == null) return;
        ScaffoldMessenger.of(nav).showSnackBar(SnackBar(content: Text(msg)));
      };
      LocalNotifications.instance.onOpenSuggestion = _openSuggestion;
      _poller = SuggestionPoller(api);
      _poller!.onPendingChanged = LocalNotifications.instance.onPendingChanged;
      _poller!.onNewSuggestions = LocalNotifications.instance.onNewSuggestions;
      _poller!.start();
      _positionPoller = PositionPoller(api);
      _positionPoller!.onExitAlerts = LocalNotifications.instance.onExitAlerts;
      _positionPoller!.start();
      unawaited(_consumePendingOpen());
    });
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
    if (accountId.trim().isEmpty || suggestionId.trim().isEmpty) {
      debugPrint('[notif] _openSuggestion skipped: accountId="$accountId" suggestionId="$suggestionId"');
      return;
    }
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

  @override
  void dispose() {
    LocalNotifications.instance.onDesktopPending = null;
    LocalNotifications.instance.onOpenSuggestion = null;
    LocalNotifications.instance.onActionMessage = null;
    _poller?.stop();
    _positionPoller?.stop();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: IndexedStack(
        index: _tabIndex,
        children: const [
          DashboardPage(),
          AccountsPage(),
          StudiesPage(),
        ],
      ),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _tabIndex,
        onDestinationSelected: (i) => setState(() => _tabIndex = i),
        destinations: const [
          NavigationDestination(
            icon: Icon(Icons.dashboard_outlined),
            selectedIcon: Icon(Icons.dashboard),
            label: 'Dashboard',
          ),
          NavigationDestination(
            icon: Icon(Icons.account_balance_wallet_outlined),
            selectedIcon: Icon(Icons.account_balance_wallet),
            label: 'Contas',
          ),
          NavigationDestination(
            icon: Icon(Icons.query_stats_outlined),
            selectedIcon: Icon(Icons.query_stats),
            label: 'Estudos',
          ),
        ],
      ),
    );
  }
}
