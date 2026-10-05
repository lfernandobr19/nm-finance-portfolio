import 'package:shared_preferences/shared_preferences.dart';

/// Persistência do mercado ativo no app (Brasil | EUA).
class MarketPrefs {
  static const key = 'raven_market'; // br | us

  static Future<String> load() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getString(key) ?? 'br';
  }

  static Future<void> save(String market) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(key, market);
  }
}
