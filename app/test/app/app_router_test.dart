import 'package:flutter_test/flutter_test.dart';

import 'package:fiidesk/app/app_router.dart';

void main() {
  group('AppRouter.redirectFor', () {
    test('loading always goes to splash', () {
      expect(
        AppRouter.redirectFor(
            loading: true, isAuthenticated: false, location: '/contas'),
        '/splash',
      );
    });

    test('unauthenticated is sent to login', () {
      expect(
        AppRouter.redirectFor(
            loading: false, isAuthenticated: false, location: '/contas'),
        '/login',
      );
      expect(
        AppRouter.redirectFor(
            loading: false, isAuthenticated: false, location: '/inteligencia'),
        '/login',
      );
    });

    test('unauthenticated at login stays', () {
      expect(
        AppRouter.redirectFor(
            loading: false, isAuthenticated: false, location: '/login'),
        isNull,
      );
    });

    test('authenticated at login/splash is sent to dashboard', () {
      expect(
        AppRouter.redirectFor(
            loading: false, isAuthenticated: true, location: '/login'),
        '/dashboard',
      );
      expect(
        AppRouter.redirectFor(
            loading: false, isAuthenticated: true, location: '/splash'),
        '/dashboard',
      );
    });

    test('authenticated in-app stays on current tab', () {
      for (final loc in [
        '/dashboard',
        '/contas',
        '/mesa',
        '/day-trade',
        '/noticias',
        '/ordens',
        '/config'
      ]) {
        expect(
          AppRouter.redirectFor(
              loading: false, isAuthenticated: true, location: loc),
          isNull,
          reason: 'should not redirect away from $loc',
        );
      }
    });
  });
}
