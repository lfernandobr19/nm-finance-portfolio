import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:fiidesk/main.dart';

void main() {
  testWidgets('NM Finance shows login brand', (WidgetTester tester) async {
    SharedPreferences.setMockInitialValues({});
    // Without this, TokenStore's platform channel never answers, AuthState
    // stays in `loading`, and the root keeps spinning forever.
    FlutterSecureStorage.setMockInitialValues({});
    await tester.pumpWidget(const FiiDeskApp());
    await tester.pumpAndSettle();
    expect(find.text('NM Finance'), findsOneWidget);
  });
}
