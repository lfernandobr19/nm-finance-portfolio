import 'package:fiidesk/data/models/intelligence_pulse.dart';
import 'package:fiidesk/features/intelligence/studies_page.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  testWidgets('StudiesBody shows learn progression and a study with guard',
      (tester) async {
    const studies = StudiesSnapshot(
      ts: '2026-09-11T09:00:00Z',
      queries: [
        StudyQuery(
          id: 'hv_dip_deep_dip',
          label: 'Dip profundo costuma recuperar?',
          channel: 'hv_dip',
          fingerprint: 'deep_dip',
          horizon: 10,
          metric: 'p_recover',
          targetR: 2.0,
          params: {'min_dip_pct': 15.0},
        ),
      ],
      results: [
        StudyResult(
          queryId: 'hv_dip_deep_dip',
          label: 'Dip profundo costuma recuperar?',
          channel: 'hv_dip',
          fingerprint: 'deep_dip',
          ticker: 'UNIVERSE',
          n: 40,
          pHigher: 0.35,
          pStopFirst: 0.65,
          pRecover: 0.35,
          trendUp: 0.5,
        ),
        StudyResult(
          queryId: 'hv_dip_deep_dip',
          label: 'Dip profundo costuma recuperar?',
          channel: 'hv_dip',
          fingerprint: 'deep_dip',
          ticker: 'AMD',
          n: 12,
          pHigher: 0.6,
          pStopFirst: 0.4,
          pRecover: 0.6,
          vsUniverse: 0.25,
        ),
      ],
      decisions: [
        {
          'key': 'hv_dip:deep_dip',
          'action': 'force_review',
          'reason': 'P(recupera em ~2 semanas)=0.35 fraca',
        },
      ],
    );

    const pulse = IntelligencePulse(
      available: true,
      nClosedUsd: 6,
      learn: {
        'hv_dip': LearnStatus(status: 'no_data', n: 12),
        'desk': LearnStatus(status: 'no_data', n: 4),
        'day_trade': LearnStatus(status: 'no_data', n: 35),
      },
      studies: studies,
    );

    await tester.pumpWidget(
      const MaterialApp(
        home: Scaffold(body: StudiesBody(pulse: pulse)),
      ),
    );

    expect(find.text('Progressão do aprendizado'), findsOneWidget);
    expect(find.text('Estudos'), findsOneWidget);
    expect(find.textContaining('High-Vol Dip'), findsOneWidget);
    expect(find.textContaining('n=12/30'), findsOneWidget);
    expect(find.textContaining('Day Trade'), findsOneWidget);
    expect(find.textContaining('n=35/30'), findsOneWidget);
    expect(find.textContaining('Dip profundo costuma recuperar?'), findsOneWidget);
    expect(find.textContaining('P(valorizar ~2 sem)'), findsOneWidget);
    expect(find.textContaining('desk bloqueou'), findsOneWidget);
    expect(find.textContaining('AMD'), findsOneWidget);
  });

  testWidgets('StudiesBody empty state when no pulse and no studies',
      (tester) async {
    await tester.pumpWidget(
      const MaterialApp(
        home: Scaffold(body: StudiesBody(pulse: IntelligencePulse(available: false))),
      ),
    );
    expect(find.textContaining('Nenhum estudo ativo'), findsOneWidget);
  });

  testWidgets('StudiesBody renders grounded insights with evidence',
      (tester) async {
    const studies = StudiesSnapshot(
      ts: '2026-09-11T09:00:00Z',
      queries: [],
      results: [],
      insights: [
        Insight(
          ticker: 'UNIVERSE',
          kind: 'universe',
          text: 'Deep dip persegue o alvo em 33% dos casos.',
          evidence: [InsightEvidence(fact: 'P(alvo)', value: '0.33')],
          confidence: 0.8,
          channel: 'hv_dip',
        ),
      ],
    );

    const pulse = IntelligencePulse(available: true, studies: studies);

    await tester.pumpWidget(
      const MaterialApp(
        home: Scaffold(body: StudiesBody(pulse: pulse)),
      ),
    );

    expect(find.text('Insights'), findsOneWidget);
    expect(find.textContaining('Deep dip persegue o alvo'), findsOneWidget);
    expect(find.textContaining('P(alvo): 0.33'), findsOneWidget);
    expect(find.textContaining('universe'), findsOneWidget);
  });
}
