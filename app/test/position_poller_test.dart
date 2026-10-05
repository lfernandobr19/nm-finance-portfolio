import 'package:flutter_test/flutter_test.dart';

import 'package:fiidesk/core/position_poller.dart';

void main() {
  test('ExitAlertEvent dedup key is position:alert', () {
    final e = ExitAlertEvent(
      positionId: 'p1',
      accountId: 'a1',
      suggestionId: 's1',
      ticker: 'LCID',
      alert: 'recovery',
      markPrice: 6.1,
    );
    expect(e.dedupKey(), 'p1:recovery');
  });

  test('alertTitle maps v2 alerts', () {
    expect(PositionPoller.alertTitle('recovery', 'LCID'), 'RECUP LCID');
    expect(PositionPoller.alertTitle('trailing', 'MARA'), 'TRAIL MARA');
    expect(PositionPoller.alertTitle('latched', 'CRWD'), 'OBS CRWD');
    expect(PositionPoller.alertTitle('protect', 'NET'), 'PROT NET');
    expect(PositionPoller.alertTitle('time_review', 'MDB'), 'D14 MDB');
  });
}
