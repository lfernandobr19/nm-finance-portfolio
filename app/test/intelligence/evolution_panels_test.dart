import 'package:fiidesk/core/api_client.dart';
import 'package:fiidesk/data/models/intelligence_pulse.dart';
import 'package:fiidesk/data/repositories/intelligence_repository.dart';
import 'package:fiidesk/features/intelligence/evolution_panels.dart';
import 'package:fiidesk/features/intelligence/intelligence_panels.dart';
import 'package:fiidesk/features/intelligence/intelligence_store.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';

void main() {
  testWidgets('PulsePanelBody shows live checklist', (tester) async {
    const pulse = IntelligencePulse(
      available: true,
      ts: '2026-09-13T03:00:00Z',
      livePromotion: {
        'ready': false,
        'items': [
          {'id': 'paper_n', 'ok': false, 'detail': 'hv_dip fechados=1 piso=30'},
        ],
      },
    );
    await tester.pumpWidget(
      const MaterialApp(
        home: Scaffold(body: PulsePanelBody(pulse: pulse)),
      ),
    );
    expect(find.textContaining('checklist incompleto'), findsOneWidget);
    expect(find.textContaining('snapshot'), findsOneWidget);
  });

  testWidgets('EvolutionPanel lists events from the store', (tester) async {
    final store = IntelligenceStore(
      IntelligenceRepository(ApiClient(baseUrl: 'http://127.0.0.1:9')),
    );
    store.evolution = [
      {'kind': 'memory', 'title': 'REFUTADA hv_dip:deep_dip', 'detail': 'fraco', 'ts': 't'},
    ];
    await tester.pumpWidget(
      MaterialApp(
        home: ChangeNotifierProvider.value(
          value: store,
          child: const Scaffold(
            body: EvolutionPanel(accountId: 'a', refreshTick: 0),
          ),
        ),
      ),
    );
    expect(find.textContaining('REFUTADA'), findsOneWidget);
  });

  testWidgets('MemoryPanel filters REFUTADA vs válida', (tester) async {
    final store = IntelligenceStore(
      IntelligenceRepository(ApiClient(baseUrl: 'http://127.0.0.1:9')),
    );
    store.memories = [
      {
        'refuted': true,
        'scope': 'hv_dip:deep_dip',
        'text': 'dip fraco',
      },
      {
        'refuted': false,
        'scope': 'desk:budget',
        'text': 'fatia ok',
      },
    ];
    await tester.pumpWidget(
      MaterialApp(
        home: ChangeNotifierProvider.value(
          value: store,
          child: const Scaffold(
            body: MemoryPanel(accountId: 'a', refreshTick: 0),
          ),
        ),
      ),
    );
    expect(find.textContaining('REFUTADA · hv_dip:deep_dip'), findsOneWidget);
    expect(find.textContaining('válida · desk:budget'), findsOneWidget);
    await tester.enterText(find.byType(TextField), 'refutada');
    await tester.pump();
    expect(find.textContaining('dip fraco'), findsOneWidget);
    expect(find.textContaining('fatia ok'), findsNothing);
  });

  testWidgets('ReliabilityChart paints without throwing', (tester) async {
    await tester.pumpWidget(
      const MaterialApp(
        home: Scaffold(
          body: ReliabilityChart(buckets: [
            {'p_mean': 0.2, 'freq': 0.1, 'n': 8},
            {'p_mean': 0.8, 'freq': 0.7, 'n': 10},
          ]),
        ),
      ),
    );
    expect(find.byType(ReliabilityChart), findsOneWidget);
  });
}
