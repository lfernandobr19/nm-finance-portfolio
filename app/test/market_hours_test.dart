import 'package:flutter_test/flutter_test.dart';

import 'package:fiidesk/core/market_hours.dart';

void main() {
  test('B3 closed on Saturday BRT', () {
    // Sat 2026-08-29 12:00 UTC = 09:00 BRT
    final utc = DateTime.utc(2026, 8, 29, 12);
    expect(MarketHours.b3Session(utc).isOpen, isFalse);
  });

  test('B3 open mid session BRT', () {
    // Wed 2026-08-27 15:00 UTC = 12:00 BRT
    final utc = DateTime.utc(2026, 8, 27, 15);
    expect(MarketHours.b3Session(utc).isOpen, isTrue);
  });

  test('US closed when B3 open (overnight BR)', () {
    // Wed 2026-08-27 15:00 UTC = 11:00 ET (EDT) — before 9:30 open
    final utc = DateTime.utc(2026, 8, 27, 13);
    expect(MarketHours.usSession(utc).isOpen, isFalse);
  });
}
