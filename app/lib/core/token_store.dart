import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Secure token persistence (Android Keystore / Windows DPAPI / iOS Keychain)
/// with a one-time migration from the legacy `SharedPreferences` store.
class TokenStore {
  TokenStore({FlutterSecureStorage? storage})
      : _storage = storage ?? const FlutterSecureStorage();

  static const _accessKey = 'access_token';
  static const _refreshKey = 'refresh_token';

  final FlutterSecureStorage _storage;

  Future<String?> readAccess() => _storage.read(key: _accessKey);
  Future<String?> readRefresh() => _storage.read(key: _refreshKey);

  Future<void> write(String access, String refresh) async {
    await _storage.write(key: _accessKey, value: access);
    await _storage.write(key: _refreshKey, value: refresh);
  }

  Future<void> clear() async {
    await _storage.delete(key: _accessKey);
    await _storage.delete(key: _refreshKey);
  }

  /// One-time migration: copy legacy tokens from SharedPreferences into secure
  /// storage, then delete the plaintext copies. No-op once secure storage has a
  /// value (prevents overwriting fresh credentials with stale ones).
  Future<void> migrateFromPrefs() async {
    final existing = await readAccess();
    if (existing != null && existing.isNotEmpty) return;

    final prefs = await SharedPreferences.getInstance();
    final legacyAccess = prefs.getString('access_token');
    final legacyRefresh = prefs.getString('refresh_token');
    if (legacyAccess == null && legacyRefresh == null) return;

    await write(legacyAccess ?? '', legacyRefresh ?? '');
    await prefs.remove('access_token');
    await prefs.remove('refresh_token');
  }
}
