import 'package:flutter/material.dart';

/// A top-level navigation destination in the desktop shell.
class DesktopDestination {
  const DesktopDestination({
    required this.path,
    required this.label,
    required this.icon,
    required this.selectedIcon,
  });

  final String path;
  final String label;
  final IconData icon;
  final IconData selectedIcon;
}

/// All primary destinations of the desktop `NavigationRail`.
const List<DesktopDestination> desktopDestinations = [
  DesktopDestination(
    path: '/dashboard',
    label: 'Dashboard',
    icon: Icons.dashboard_outlined,
    selectedIcon: Icons.dashboard,
  ),
  DesktopDestination(
    path: '/contas',
    label: 'Contas',
    icon: Icons.account_balance_wallet_outlined,
    selectedIcon: Icons.account_balance_wallet,
  ),
  DesktopDestination(
    path: '/mesa',
    label: 'Mesa',
    icon: Icons.space_dashboard_outlined,
    selectedIcon: Icons.space_dashboard,
  ),
  DesktopDestination(
    path: '/day-trade',
    label: 'Day Trade',
    icon: Icons.candlestick_chart_outlined,
    selectedIcon: Icons.candlestick_chart,
  ),
  DesktopDestination(
    path: '/inteligencia',
    label: 'Inteligência',
    icon: Icons.insights_outlined,
    selectedIcon: Icons.insights,
  ),
  DesktopDestination(
    path: '/noticias',
    label: 'Notícias',
    icon: Icons.newspaper_outlined,
    selectedIcon: Icons.newspaper,
  ),
  DesktopDestination(
    path: '/ordens',
    label: 'Ordens',
    icon: Icons.receipt_long_outlined,
    selectedIcon: Icons.receipt_long,
  ),
  DesktopDestination(
    path: '/config',
    label: 'Configurações',
    icon: Icons.settings_outlined,
    selectedIcon: Icons.settings,
  ),
];
