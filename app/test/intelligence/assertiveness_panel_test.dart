import 'package:fiidesk/data/models/intelligence_pulse.dart';
import 'package:fiidesk/features/intelligence/intelligence_panels.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  testWidgets('AssertivenessPanelBody explains empty ledger', (tester) async {
    await tester.pumpWidget(
      const MaterialApp(
        home: Scaffold(
          body: AssertivenessPanelBody(
            pulse: IntelligencePulse(available: true),
          ),
        ),
      ),
    );
    expect(find.textContaining('quando digo 60%'), findsOneWidget);
  });

  testWidgets('AssertivenessPanelBody shows Platt news when ledger is pending',
      (tester) async {
    const pulse = IntelligencePulse(
      available: true,
      assertiveness: {
        'by_source': {
          'studies': {'n': 58, 'resolved': 0, 'hit_rate': null, 'brier': null},
        },
        'calibrators': {
          'news': {
            'n': 3014,
            'brier_raw': 0.36,
            'brier_calibrated': 0.24,
          },
        },
      },
    );
    await tester.pumpWidget(
      const MaterialApp(
        home: Scaffold(body: AssertivenessPanelBody(pulse: pulse)),
      ),
    );
    expect(find.textContaining('Platt'), findsOneWidget);
    expect(find.textContaining('0.24'), findsOneWidget);
  });

  testWidgets('AssertivenessPanelBody shows per-source Brier', (tester) async {
    const pulse = IntelligencePulse(
      available: true,
      assertiveness: {
        'by_source': {
          'hv_dip': {'resolved': 40, 'hit_rate': 0.55, 'brier': 0.18},
        },
      },
    );
    await tester.pumpWidget(
      const MaterialApp(
        home: Scaffold(body: AssertivenessPanelBody(pulse: pulse)),
      ),
    );
    expect(find.textContaining('hv_dip'), findsOneWidget);
    expect(find.textContaining('brier'), findsOneWidget);
  });

  testWidgets('AssertivenessPanelBody shows mega_rotation with n below 30',
      (tester) async {
    const pulse = IntelligencePulse(
      available: true,
      assertiveness: {
        'by_source': {
          'mega_rotation': {
            'n': 5,
            'resolved': 2,
            'hit_rate': 0.5,
            'brier': 0.2,
          },
          'judgment': {
            'n': 3,
            'resolved': 0,
            'hit_rate': null,
            'brier': null,
          },
        },
        'curves': {
          'mega_rotation': [
            {'n': 2, 'p_mean': 0.7, 'freq': 0.5},
          ],
        },
      },
    );
    await tester.pumpWidget(
      const MaterialApp(
        home: Scaffold(body: AssertivenessPanelBody(pulse: pulse)),
      ),
    );
    expect(find.textContaining('mega_rotation'), findsWidgets);
    expect(find.textContaining('judgment'), findsOneWidget);
    expect(find.textContaining('n 5'), findsOneWidget);
  });
}
