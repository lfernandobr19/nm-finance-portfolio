import 'package:fiidesk/data/models/intelligence_pulse.dart';
import 'package:fiidesk/features/intelligence/intelligence_panels.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  testWidgets('PulsePanelBody shows hit rate, no_data and a lesson',
      (tester) async {
    const pulse = IntelligencePulse(
      available: true,
      nClosedUsd: 0,
      newsJsonOk: 45,
      hvDipAutoBuyEnabled: false,
      learn: {
        'hv_dip': LearnStatus(status: 'no_data', n: 0),
        'desk': LearnStatus(status: 'no_data', n: 0),
        'day_trade': LearnStatus(status: 'no_data', n: 0),
      },
      calibration: {
        'n_labeled': 45,
        'hit_rate': 0.27,
        'brier': 0.4,
      },
      recentReviews: [
        LlmReview(
          ticker: 'VALE3',
          lesson: 'stop hit',
          wouldChange: 'none',
        ),
      ],
      swingH1: {'h1_ok': 3, 'h1_skip': 1, 'h1_fail': 2},
      swingH1Ts: '2026-09-11T15:10:00Z',
      ollama: 'warm',
      ollamaExpiresAt: '2026-09-11T12:42:00Z',
      lastLlmSource: 'ollama',
    );

    await tester.pumpWidget(
      const MaterialApp(
        home: Scaffold(body: PulsePanelBody(pulse: pulse)),
      ),
    );

    expect(find.textContaining('hit 0.27'), findsOneWidget);
    expect(find.textContaining('hv_dip · no_data · 0 < 30'), findsOneWidget);
    expect(find.textContaining('auto-buy desligado'), findsOneWidget);
    expect(find.text('stop hit'), findsOneWidget);
    expect(find.textContaining('VALE3'), findsOneWidget);
    expect(find.textContaining('1h 3 OK · 1 — · 2 fora'), findsOneWidget);
    expect(find.textContaining('scan'), findsOneWidget);
    expect(find.textContaining('7B warm · até'), findsOneWidget);
    expect(find.text('último: ollama'), findsOneWidget);
  });

  testWidgets('PulsePanelBody empty state when pulse unavailable',
      (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: PulsePanelBody(pulse: IntelligencePulse.unavailable()),
        ),
      ),
    );
    expect(find.textContaining('Pulso ainda não rodou'), findsOneWidget);
  });

  testWidgets('PulsePanelBody shows 1h counts when nightly pulse is missing',
      (tester) async {
    const pulse = IntelligencePulse(
      available: false,
      hvDipAutoBuyEnabled: false,
      swingH1: {'h1_ok': 3, 'h1_skip': 1, 'h1_fail': 2},
    );
    await tester.pumpWidget(
      const MaterialApp(
        home: Scaffold(body: PulsePanelBody(pulse: pulse)),
      ),
    );
    expect(find.text('1h 3 OK · 1 — · 2 fora'), findsOneWidget);
    expect(find.textContaining('auto-buy'), findsNothing);
  });
}
