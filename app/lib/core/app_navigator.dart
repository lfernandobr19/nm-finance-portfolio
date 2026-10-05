import 'package:flutter/material.dart';

/// Global navigator key shared by both the mobile `MaterialApp` and the desktop
/// `MaterialApp.router` (GoRouter). Lets non-widget services (notifications,
/// pollers) push routes without a BuildContext.
final GlobalKey<NavigatorState> appNavigatorKey = GlobalKey<NavigatorState>();
