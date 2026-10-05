import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../core/api_client.dart';
import '../core/auth_state.dart';
import '../core/notification_center.dart';
import '../core/theme_controller.dart';
import 'app_router.dart';
import 'selected_account.dart';

/// Desktop root widget: wires DI (Provider) + declarative routing (GoRouter).
///
/// The [AuthState] is instantiated once here and shared between the router
/// (auth guard + refreshListenable) and the widget tree.
class DesktopApp extends StatefulWidget {
  const DesktopApp({super.key});

  static const _seed = Color(0xFF1B4D3E);

  @override
  State<DesktopApp> createState() => _DesktopAppState();
}

class _DesktopAppState extends State<DesktopApp> {
  late final ApiClient _api = ApiClient();
  late final AuthState _auth = AuthState(_api)..bootstrap();
  late final AppRouter _appRouter = AppRouter(_auth);

  @override
  void dispose() {
    _auth.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return MultiProvider(
      providers: [
        Provider<ApiClient>.value(value: _api),
        ChangeNotifierProvider<AuthState>.value(value: _auth),
        ChangeNotifierProvider(create: (_) => ThemeController()),
        ChangeNotifierProvider(create: (_) => SelectedAccount()),
        ChangeNotifierProvider(create: (_) => NotificationCenter()..load()),
      ],
      child: Consumer<ThemeController>(
        builder: (context, themeCtrl, _) {
          return MaterialApp.router(
            routerConfig: _appRouter.router,
            title: 'NM Finance',
            debugShowCheckedModeBanner: false,
            themeMode: themeCtrl.mode,
            theme: ThemeData(
              colorScheme: ColorScheme.fromSeed(
                seedColor: DesktopApp._seed,
                brightness: Brightness.light,
              ),
              useMaterial3: true,
            ),
            darkTheme: ThemeData(
              colorScheme: ColorScheme.fromSeed(
                seedColor: DesktopApp._seed,
                brightness: Brightness.dark,
              ),
              useMaterial3: true,
            ),
          );
        },
      ),
    );
  }
}
