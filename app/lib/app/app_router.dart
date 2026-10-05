import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../core/app_navigator.dart';
import '../../core/auth_state.dart';
import '../../features/auth/login_page.dart';
import '../../features/dashboard/dashboard_screen.dart';
import '../../features/desktop/accounts_screen.dart';
import '../../features/desktop/day_trade_screen.dart';
import '../../features/desktop/desk_screen.dart';
import '../../features/intelligence/intelligence_dashboard.dart';
import '../../features/desktop/news_screen.dart';
import '../../features/desktop/orders_screen.dart';
import '../../features/desktop/rules_screen.dart';
import '../../features/shell/desktop_shell.dart';

/// Declarative router for the desktop app.
///
/// The auth guard uses [AuthState] both as the redirect source of truth and as
/// the [GoRouter.refreshListenable], so any auth change (bootstrap/login/logout)
/// re-runs the guard and re-syncs the visible route.
class AppRouter {
  AppRouter(this._auth);

  final AuthState _auth;

  late final GoRouter router = GoRouter(
    navigatorKey: appNavigatorKey,
    initialLocation: '/splash',
    refreshListenable: _auth,
    redirect: _redirect,
    routes: [
      GoRoute(
        path: '/splash',
        builder: (context, state) => const _BootScreen(),
      ),
      GoRoute(
        path: '/login',
        builder: (context, state) => const LoginPage(),
      ),
      StatefulShellRoute.indexedStack(
        builder: (context, state, shell) => DesktopShell(shell: shell),
        branches: [
          _branch('/dashboard', const DashboardScreen()),
          _branch('/contas', const AccountsScreen()),
          _branch('/mesa', const DeskScreen()),
          _branch('/day-trade', const DayTradeScreen()),
          _branch('/inteligencia', const IntelligenceDashboard()),
          _branch('/noticias', const NewsScreen()),
          _branch('/ordens', const OrdersScreen()),
          _branch('/config', const RulesScreen()),
        ],
      ),
    ],
  );

  StatefulShellBranch _branch(String path, Widget screen) {
    return StatefulShellBranch(routes: [
      GoRoute(
        path: path,
        builder: (context, state) => screen,
      ),
    ]);
  }

  String? _redirect(BuildContext context, GoRouterState state) {
    return redirectFor(
      loading: _auth.loading,
      isAuthenticated: _auth.isAuthenticated,
      location: state.matchedLocation,
    );
  }

  /// Pure auth-guard decision (unit-testable without a running router).
  static String? redirectFor({
    required bool loading,
    required bool isAuthenticated,
    required String location,
  }) {
    if (loading) return '/splash';
    if (!isAuthenticated) return location == '/login' ? null : '/login';
    if (location == '/login' || location == '/splash') return '/dashboard';
    return null;
  }
}

class _BootScreen extends StatelessWidget {
  const _BootScreen();

  @override
  Widget build(BuildContext context) {
    return const Scaffold(
      body: Center(child: CircularProgressIndicator()),
    );
  }
}
