import 'package:fiidesk/core/format.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  group('h1ChipLabel', () {
    test('maps known statuses and hides the rest', () {
      expect(h1ChipLabel('h1_ok'), '1h OK');
      expect(h1ChipLabel('h1_skip'), '1h —');
      expect(h1ChipLabel('h1_fail'), '1h NÃO');
      expect(h1ChipLabel(null), isNull);
      expect(h1ChipLabel(''), isNull);
      expect(h1ChipLabel('other'), isNull);
    });
  });

  test('h1_status is a header metric labeled 1h', () {
    expect(metricLabel('h1_status'), '1h');
    expect(swingHeaderMetricKeys, contains('h1_status'));
  });

  test('h1PulseLine formats scan counts', () {
    expect(h1PulseLine(ok: 3, skip: 1, fail: 2), '1h 3 OK · 1 — · 2 fora');
    expect(h1PulseLine(), '1h 0 OK · 0 — · 0 fora');
    final withTs = h1PulseLine(
      ok: 3,
      skip: 1,
      fail: 2,
      ts: '2026-09-11T15:10:00Z',
    );
    expect(withTs, startsWith('1h 3 OK · 1 — · 2 fora · scan '));
    expect(withTs, matches(RegExp(r'scan \d{2}:\d{2}$')));
  });

  test('llmHealthLine maps ollama and groq cooldown', () {
    expect(llmHealthLine(ollama: 'warm'), '7B warm · groq ok');
    expect(llmHealthLine(ollama: 'cold'), '7B cold');
    expect(llmHealthLine(ollama: 'down'), '7B down');
    expect(llmHealthLine(groqCooldown: true), 'groq cooldown');
    expect(llmHealthLine(), isNull);
    final until = llmHealthLine(
      ollama: 'warm',
      expiresAt: '2026-09-11T12:42:00Z',
    );
    expect(until, startsWith('7B warm · até '));
    expect(until, matches(RegExp(r'até \d{2}:\d{2}$')));
  });

  test('lastLlmLine only shows ollama or groq', () {
    expect(lastLlmLine('ollama'), 'último: ollama');
    expect(lastLlmLine('groq'), 'último: groq');
    expect(lastLlmLine('fail'), isNull);
    expect(lastLlmLine(null), isNull);
  });

  testWidgets('Wrap shows four compact chips without approve', (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: Wrap(
            spacing: 4,
            runSpacing: 0,
            children: [
              const Chip(
                label: Text('VIVA', style: TextStyle(fontSize: 10)),
                visualDensity: VisualDensity.compact,
                padding: EdgeInsets.zero,
              ),
              const Chip(
                label: Text('CATALISTA', style: TextStyle(fontSize: 10)),
                visualDensity: VisualDensity.compact,
                padding: EdgeInsets.zero,
              ),
              const Chip(
                label: Text('REVIEW', style: TextStyle(fontSize: 10)),
                visualDensity: VisualDensity.compact,
                padding: EdgeInsets.zero,
              ),
              Chip(
                label: Text(
                  h1ChipLabel('h1_ok')!,
                  style: const TextStyle(fontSize: 10),
                ),
                visualDensity: VisualDensity.compact,
                padding: EdgeInsets.zero,
              ),
            ],
          ),
        ),
      ),
    );

    expect(find.byType(Wrap), findsOneWidget);
    expect(find.byType(Chip), findsNWidgets(4));
    expect(find.text('1h OK'), findsOneWidget);
    expect(find.textContaining('Aprovar'), findsNothing);
    expect(find.byType(FilledButton), findsNothing);
    expect(find.byType(ElevatedButton), findsNothing);
  });
}
