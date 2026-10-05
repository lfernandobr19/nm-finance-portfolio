import 'dart:async';

import 'package:flutter/foundation.dart';

import 'api_client.dart';
import 'token_store.dart';

class AuthState extends ChangeNotifier {
  AuthState(this._api, {TokenStore? store}) : _store = store ?? TokenStore() {
    _api.onAuthFailure = logout;
    _api.onTokensChanged = _persistFromCallback;
  }

  final ApiClient _api;
  final TokenStore _store;
  bool loading = true;
  bool isAuthenticated = false;
  Map<String, dynamic>? user;
  String? refreshToken;

  Future<void> bootstrap() async {
    await _api.resolveBaseUrl();
    await _store.migrateFromPrefs();
    final access = await _store.readAccess();
    refreshToken = await _store.readRefresh();
    _api.refreshToken = refreshToken;
    if (access != null && access.isNotEmpty) {
      _api.accessToken = access;
      try {
        user = await _api.getMap('/auth/me');
        isAuthenticated = true;
      } catch (_) {
        await logout();
      }
    }
    loading = false;
    notifyListeners();
  }

  Future<void> register(String email, String password, String fullName) async {
    await _api.post('/auth/register', {
      'email': email,
      'password': password,
      'full_name': fullName,
    });
    await login(email, password);
  }

  Future<void> login(String email, String password) async {
    final tokens = await _api.post('/auth/login', {
      'email': email,
      'password': password,
    });
    await _persistTokens(
        tokens['access_token'] as String, tokens['refresh_token'] as String);
    user = await _api.getMap('/auth/me');
    isAuthenticated = true;
    notifyListeners();
  }

  Future<void> _persistTokens(String access, String refresh) async {
    _api.accessToken = access;
    _api.refreshToken = refresh;
    refreshToken = refresh;
    await _store.write(access, refresh);
  }

  void _persistFromCallback(String access, String refresh) {
    refreshToken = refresh;
    unawaited(_store.write(access, refresh));
  }

  Future<void> logout() async {
    _api.accessToken = null;
    _api.refreshToken = null;
    refreshToken = null;
    user = null;
    isAuthenticated = false;
    await _store.clear();
    notifyListeners();
  }
}
