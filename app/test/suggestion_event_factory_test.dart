import 'package:flutter_test/flutter_test.dart';

import 'package:fiidesk/core/suggestion_event_factory.dart';

void main() {
  test('parses status and catalyst from metrics', () {
    final e = newSuggestionEventFromApi(
      accountId: 'a',
      isUsd: true,
      sm: {
        'id': 's1',
        'ticker': 'TSLA',
        'strategy_kind': 'hv_dip',
        'status': 'pending',
        'review_required': false,
        'swing_score_letter': 'A',
        'metrics': {
          'catalyst': {
            'event_type': 'partnership',
            'sentiment': 'bullish',
            'confidence': 0.9,
            'impact_score': 75,
            'title': 'Acordo',
          },
        },
      },
    );
    expect(e.status, 'pending');
    expect(e.isAuto, false);
    expect(e.catalyst, isNotNull);
    expect(e.catalyst!.eventType, 'partnership');
    expect(e.catalyst!.sentiment, 'bullish');
    expect(e.catalyst!.confidence, 0.9);
    expect(e.catalyst!.impactScore, 75);
    expect(e.catalyst!.title, 'Acordo');
  });

  test('handles missing catalyst and status gracefully', () {
    final e = newSuggestionEventFromApi(
      accountId: 'a',
      isUsd: false,
      sm: {
        'id': 's2',
        'ticker': 'VALE3',
        'strategy_kind': 'swing',
        'metrics': {},
      },
    );
    expect(e.status, isNull);
    expect(e.isAuto, false);
    expect(e.catalyst, isNull);
  });

  test('isAuto true for auto_approved status', () {
    final e = newSuggestionEventFromApi(
      accountId: 'a',
      isUsd: true,
      sm: {
        'id': 's3',
        'ticker': 'AMD',
        'strategy_kind': 'hv_dip',
        'status': 'auto_approved',
        'metrics': {'catalyst': {'event_type': 'guidance_up'}},
      },
    );
    expect(e.isAuto, true);
  });
}
