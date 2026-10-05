import 'package:fiidesk/data/models/intelligence_pulse.dart';
import 'package:fiidesk/features/intelligence/intelligence_panels.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  testWidgets('StudiesPanelBody shows n, P(vender mais caro) and a guard',
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

    await tester.pumpWidget(
      const MaterialApp(
        home: Scaffold(body: StudiesPanelBody(studies: studies)),
      ),
    );

    expect(find.textContaining('Dip profundo costuma recuperar?'), findsOneWidget);
    expect(find.textContaining('n=40'), findsOneWidget);
    expect(find.textContaining('P(valorizar ~2 sem)'), findsOneWidget);
    expect(find.textContaining('desk bloqueou'), findsOneWidget);
    expect(find.textContaining('AMD'), findsOneWidget);
  });

  testWidgets('StudiesPanelBody empty state', (tester) async {
    await tester.pumpWidget(
      const MaterialApp(
        home: Scaffold(body: StudiesPanelBody(studies: null)),
      ),
    );
    expect(find.textContaining('Nenhum estudo ativo'), findsOneWidget);
  });

  testWidgets('StudiesPanelBody renders insights', (tester) async {
    const studies = StudiesSnapshot(
      ts: '2026-09-11T09:00:00Z',
      queries: [],
      results: [],
      insights: [
        Insight(
          ticker: 'AMD',
          kind: 'ticker',
          text: 'AMD recupera o alvo mais que o universo.',
          evidence: [InsightEvidence(fact: 'vs universo', value: '+7pp')],
          confidence: 0.6,
          channel: 'hv_dip',
        ),
      ],
    );

    await tester.pumpWidget(
      const MaterialApp(
        home: Scaffold(body: StudiesPanelBody(studies: studies)),
      ),
    );

    expect(find.text('Insights'), findsOneWidget);
    expect(find.textContaining('AMD recupera o alvo'), findsOneWidget);
    expect(find.textContaining('vs universo: +7pp'), findsOneWidget);
    expect(find.text('ticker'), findsOneWidget);
  });
}
