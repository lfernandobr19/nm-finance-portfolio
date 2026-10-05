import 'package:flutter_test/flutter_test.dart';

import 'package:fiidesk/core/fcm_service.dart';

void main() {
  test('payloadFromData for pending suggestion', () {
    final payload = FcmService.payloadFromData({
      'account_id': 'a1',
      'suggestion_id': 's1',
      'status': 'pending',
    });
    expect(payload, 'a1|s1|0');
  });

  test('payloadFromData for review_required suggestion', () {
    final payload = FcmService.payloadFromData({
      'account_id': 'a1',
      'suggestion_id': 's2',
      'status': 'review_required',
    });
    expect(payload, 'a1|s2|1');
  });

  test('payloadFromData for order_filled includes position', () {
    final payload = FcmService.payloadFromData({
      'account_id': 'a1',
      'suggestion_id': 's3',
      'status': 'auto_approved',
      'kind': 'order_filled',
      'position_id': 'p1',
    });
    expect(payload, 'a1|s3|p1|filled');
  });

  test('payloadFromData for position alert routes by alert', () {
    final payload = FcmService.payloadFromData({
      'account_id': 'a1',
      'position_id': 'p2',
      'alert': 'protect',
      'ticker': 'MARA',
    });
    expect(payload, 'a1||p2|protect');
  });

  test('payloadFromData for rotation keeps position context', () {
    final payload = FcmService.payloadFromData({
      'account_id': 'a1',
      'suggestion_id': 's4',
      'kind': 'rotation',
      'position_id': 'p3',
      'alert': 'rotation',
    });
    expect(payload, 'a1|s4|p3|rotation');
  });

  test('payloadFromData with empty data is safe', () {
    final payload = FcmService.payloadFromData({});
    expect(payload, '||0');
  });
}
