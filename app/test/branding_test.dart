// Regression guard: the visible product name must stay "NM Finance".
// A server-side reconcile once reverted these files to the Flutter scaffold names.
import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

const _brand = 'NM Finance';

void main() {
  test('AndroidManifest android:label is NM Finance', () {
    final xml = File('android/app/src/main/AndroidManifest.xml').readAsStringSync();
    final label = RegExp(r'android:label="([^"]*)"').firstMatch(xml)?.group(1);
    expect(label, _brand);
  });

  test('web/manifest.json name and short_name are NM Finance', () {
    final json = jsonDecode(File('web/manifest.json').readAsStringSync()) as Map<String, dynamic>;
    expect(json['name'], _brand);
    expect(json['short_name'], _brand);
  });

  test('web/index.html title is NM Finance', () {
    final html = File('web/index.html').readAsStringSync();
    expect(RegExp(r'<title>([^<]*)</title>').firstMatch(html)?.group(1), _brand);
    expect(html.contains('apple-mobile-web-app-title" content="$_brand"'), isTrue);
  });
}
