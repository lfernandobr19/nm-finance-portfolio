import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';

class ThemeController extends ChangeNotifier {
  ThemeController() {
    _load();
  }

  static const _key = 'theme_mode';
  ThemeMode mode = ThemeMode.system;
  bool loading = true;

  Future<void> _load() async {
    final prefs = await SharedPreferences.getInstance();
    final raw = prefs.getString(_key) ?? 'system';
    mode = switch (raw) {
      'light' => ThemeMode.light,
      'dark' => ThemeMode.dark,
      _ => ThemeMode.system,
    };
    loading = false;
    notifyListeners();
  }

  Future<void> setMode(ThemeMode next) async {
    mode = next;
    notifyListeners();
    final prefs = await SharedPreferences.getInstance();
    final raw = switch (next) {
      ThemeMode.light => 'light',
      ThemeMode.dark => 'dark',
      _ => 'system',
    };
    await prefs.setString(_key, raw);
  }

  String get label => switch (mode) {
        ThemeMode.light => 'Claro',
        ThemeMode.dark => 'Escuro',
        _ => 'Sistema',
      };
}
