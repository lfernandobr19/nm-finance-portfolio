import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

class ApiException implements Exception {
  ApiException(this.statusCode, this.message);
  final int statusCode;
  final String message;

  @override
  String toString() => 'ApiException($statusCode): $message';
}

class ApiClient {
  ApiClient({String? baseUrl, http.Client? httpClient})
      : baseUrl = baseUrl ?? _compileTimeDefault(),
        _http = httpClient ?? http.Client();

  static const prefsKey = 'api_base_url';
  static const ravennaDefault = 'http://<RAVENNA_TAILSCALE_IP>:8010/api/v1';

  final http.Client _http;
  String baseUrl;
  String? accessToken;
  String? refreshToken;

  /// Called when a request is still unauthorized after a refresh attempt
  /// (e.g. refresh token expired). The auth layer uses this to log out.
  void Function()? onAuthFailure;

  /// Called after tokens change (login/refresh) so the auth layer can persist
  /// them securely. Keeps [ApiClient] free of any storage dependency.
  void Function(String access, String refresh)? onTokensChanged;

  Future<bool>? _refreshInFlight;

  static String _compileTimeDefault() {
    const fromEnv = String.fromEnvironment('API_BASE_URL');
    if (fromEnv.isNotEmpty) return fromEnv;
    // Web: same-origin so serve_web.py proxies /api → Ravenna (avoids CORS/PNA).
    if (kIsWeb) {
      final origin = Uri.base.origin;
      if (origin.isNotEmpty && origin != 'null') {
        return '$origin/api/v1';
      }
      return 'http://127.0.0.1:4173/api/v1';
    }
    return ravennaDefault;
  }

  static bool _isStaleLocalBackend(String url) {
    final u = url.toLowerCase();
    return u.contains('127.0.0.1:8000') ||
        u.contains('localhost:8000') ||
        u.contains('127.0.0.1:8001') ||
        u.contains('localhost:8001');
  }

  /// Load persisted URL; migrate old localhost backends to the working default.
  Future<void> resolveBaseUrl() async {
    final prefs = await SharedPreferences.getInstance();
    final saved = prefs.getString(prefsKey);
    if (saved == null || saved.isEmpty || _isStaleLocalBackend(saved)) {
      baseUrl = _compileTimeDefault();
      await prefs.setString(prefsKey, baseUrl);
      return;
    }
    baseUrl = saved;
  }

  /// Renew the session using the stored refresh token. Returns true on success.
  /// Concurrent callers share a single in-flight refresh to avoid stampedes.
  Future<bool> tryRefresh() {
    final inFlight = _refreshInFlight;
    if (inFlight != null) return inFlight;
    final future = _doRefresh();
    _refreshInFlight = future;
    future.whenComplete(() => _refreshInFlight = null);
    return future;
  }

  Future<bool> _doRefresh() async {
    final rt = refreshToken;
    if (rt == null || rt.isEmpty) return false;
    try {
      final resp = await _http
          .post(
            _uri('/auth/refresh'),
            headers: {'Content-Type': 'application/json'},
            body: jsonEncode({'refresh_token': rt}),
          )
          .timeout(const Duration(seconds: 20));
      if (resp.statusCode >= 400) return false;
      final data = jsonDecode(resp.body) as Map<String, dynamic>;
      final access = data['access_token'] as String?;
      final refresh = data['refresh_token'] as String?;
      if (access == null) return false;
      accessToken = access;
      if (refresh != null && refresh.isNotEmpty) refreshToken = refresh;
      onTokensChanged?.call(access, refreshToken ?? '');
      return true;
    } catch (_) {
      return false;
    }
  }

  /// Runs [request]; on 401 it transparently refreshes the session and retries
  /// once. If still unauthorized, notifies [onAuthFailure].
  Future<http.Response> _send(Future<http.Response> Function() request) async {
    var resp = await request();
    if (resp.statusCode == 401 && await tryRefresh()) {
      resp = await request();
    }
    if (resp.statusCode == 401) {
      onAuthFailure?.call();
    }
    return resp;
  }

  Map<String, String> get _headers => {
        'Content-Type': 'application/json',
        if (accessToken != null) 'Authorization': 'Bearer $accessToken',
      };

  Uri _uri(String path, [Map<String, String>? query]) {
    final base = baseUrl.endsWith('/') ? baseUrl.substring(0, baseUrl.length - 1) : baseUrl;
    return Uri.parse('$base$path').replace(queryParameters: query);
  }

  Future<Map<String, dynamic>> post(
    String path,
    Map<String, dynamic> body, {
    Map<String, String>? query,
    Duration timeout = const Duration(seconds: 20),
  }) async {
    final resp = await _send(() => _http
        .post(_uri(path, query), headers: _headers, body: jsonEncode(body))
        .timeout(timeout));
    return _decodeMap(resp);
  }

  Future<Map<String, dynamic>> put(String path, Map<String, dynamic> body) async {
    final resp = await _send(() => _http
        .put(_uri(path), headers: _headers, body: jsonEncode(body))
        .timeout(const Duration(seconds: 20)));
    return _decodeMap(resp);
  }

  Future<Map<String, dynamic>> patch(String path, Map<String, dynamic> body) async {
    final resp = await _send(() => _http
        .patch(_uri(path), headers: _headers, body: jsonEncode(body))
        .timeout(const Duration(seconds: 20)));
    return _decodeMap(resp);
  }

  Future<Map<String, dynamic>> getMap(String path, [Map<String, String>? query]) async {
    final resp = await _send(() => _http
        .get(_uri(path, query), headers: _headers)
        .timeout(const Duration(seconds: 20)));
    return _decodeMap(resp);
  }

  Future<List<dynamic>> getList(String path, [Map<String, String>? query]) async {
    final resp = await _send(() => _http
        .get(_uri(path, query), headers: _headers)
        .timeout(const Duration(seconds: 20)));
    return _decodeList(resp);
  }

  Future<void> delete(String path) async {
    final resp = await _send(() => _http
        .delete(_uri(path), headers: _headers)
        .timeout(const Duration(seconds: 20)));
    if (resp.statusCode >= 400) {
      throw ApiException(resp.statusCode, resp.body);
    }
  }

  Map<String, dynamic> _decodeMap(http.Response resp) {
    if (resp.statusCode >= 400) {
      throw ApiException(resp.statusCode, resp.body);
    }
    if (resp.body.isEmpty) return {};
    return jsonDecode(resp.body) as Map<String, dynamic>;
  }

  List<dynamic> _decodeList(http.Response resp) {
    if (resp.statusCode >= 400) {
      throw ApiException(resp.statusCode, resp.body);
    }
    return jsonDecode(resp.body) as List<dynamic>;
  }
}

/// User-facing message for network / server errors (login, etc.).
String formatApiError(Object error) {
  final text = error.toString();
  if (text.contains('Connection refused') ||
      text.contains('Connection timed out') ||
      text.contains('Failed host lookup') ||
      text.contains('Network is unreachable')) {
    return 'Servidor Ravenna indisponível (<RAVENNA_TAILSCALE_IP>:8010). '
        'Aguarde alguns segundos e tente de novo.';
  }
  if (text.contains('ApiException')) {
    return text.replaceFirst('ApiException(', '').replaceAll(RegExp(r'\)$'), '');
  }
  return text.length > 200 ? '${text.substring(0, 200)}…' : text;
}
