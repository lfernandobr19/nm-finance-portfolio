import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:fiidesk/core/api_client.dart';

void main() {
  setUp(() {
    SharedPreferences.setMockInitialValues({});
  });

  group('ApiClient automatic token refresh', () {
    test('retries a 401 request after refreshing the token', () async {
      var refreshCalls = 0;
      var accountsCalls = 0;
      final client = MockClient((request) async {
        if (request.url.path.endsWith('/auth/refresh')) {
          refreshCalls++;
          return http.Response(
            jsonEncode({
              'access_token': 'new-access',
              'refresh_token': 'new-refresh',
            }),
            200,
            headers: {'content-type': 'application/json'},
          );
        }
        if (request.url.path.endsWith('/accounts')) {
          accountsCalls++;
          // First call: expired token -> 401. After refresh, succeed.
          final auth = request.headers['Authorization'];
          if (auth == 'Bearer new-access') {
            return http.Response(
              jsonEncode({'items': []}),
              200,
              headers: {'content-type': 'application/json'},
            );
          }
          return http.Response('{"detail":"Invalid token"}', 401);
        }
        return http.Response('{}', 200);
      });

      final api = ApiClient(baseUrl: 'http://test/api/v1', httpClient: client);
      api.accessToken = 'expired-access';
      api.refreshToken = 'old-refresh';

      final result = await api.getMap('/accounts');

      expect(result, {'items': []});
      expect(refreshCalls, 1);
      expect(accountsCalls, 2);
      expect(api.accessToken, 'new-access');
      expect(api.refreshToken, 'new-refresh');
    });

    test('calls onAuthFailure when refresh also fails', () async {
      final client = MockClient((request) async {
        if (request.url.path.endsWith('/auth/refresh')) {
          return http.Response('{"detail":"Invalid refresh token"}', 401);
        }
        return http.Response('{"detail":"Invalid token"}', 401);
      });

      final api = ApiClient(baseUrl: 'http://test/api/v1', httpClient: client);
      api.accessToken = 'expired-access';
      api.refreshToken = 'stale-refresh';

      var authFailed = false;
      api.onAuthFailure = () => authFailed = true;

      await expectLater(
        api.getMap('/accounts'),
        throwsA(isA<ApiException>()),
      );
      expect(authFailed, true);
    });

    test('does not attempt refresh without a refresh token', () async {
      var refreshCalls = 0;
      final client = MockClient((request) async {
        if (request.url.path.endsWith('/auth/refresh')) {
          refreshCalls++;
          return http.Response('{}', 200);
        }
        return http.Response('{"detail":"Invalid token"}', 401);
      });

      final api = ApiClient(baseUrl: 'http://test/api/v1', httpClient: client);
      api.accessToken = 'expired-access';
      api.refreshToken = null;

      await expectLater(
        api.getMap('/accounts'),
        throwsA(isA<ApiException>()),
      );
      expect(refreshCalls, 0);
    });
  });
}
