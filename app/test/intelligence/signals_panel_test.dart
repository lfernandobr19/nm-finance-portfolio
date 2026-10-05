import 'package:fiidesk/data/models/day_trade.dart';
import 'package:fiidesk/features/intelligence/intelligence_panels.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

DayTradeSignal _signal({
  required String ticker,
  required String status,
  String side = 'long',
  double? pnl,
  DateTime? createdAt,
}) {
  return DayTradeSignal(
    id: 'sig-$ticker-$status',
    accountId: 'acc-1',
    sessionDate: DateTime(2026, 9, 12),
    ticker: ticker,
    ruleId: 'vwap_reclaim',
    side: side,
    entryPrice: 100.0,
    stopPrice: 99.0,
    targetPrice: 102.0,
    status: status,
    simulatedPnlUsd: pnl,
    createdAt: createdAt ?? DateTime(2026, 9, 12, 10, 30),
  );
}

void main() {
  testWidgets('SignalsPanelBody summarises open, closed and P&L',
      (tester) async {
    final signals = [
      _signal(ticker: 'AAPL', status: 'open'),
      _signal(ticker: 'MSFT', status: 'closed', pnl: 2.5),
      _signal(ticker: 'NVDA', status: 'closed', pnl: -1.0),
    ];

    await tester.pumpWidget(
      MaterialApp(home: Scaffold(body: SignalsPanelBody(signals: signals))),
    );

    expect(find.text('1 abertos'), findsOneWidget);
    expect(find.text('2 fechados'), findsOneWidget);
    expect(find.textContaining('Sessão mais recente: 12/09'), findsOneWidget);
    expect(find.text('AAPL'), findsOneWidget);
    expect(find.textContaining('vwap_reclaim'), findsNWidgets(3));
  });

  testWidgets('SignalsPanelBody shows expectancy-cut rules', (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: SignalsPanelBody(
            signals: [_signal(ticker: 'AAPL', status: 'closed', pnl: -1)],
            gatedRules: const ['vwap_reclaim'],
          ),
        ),
      ),
    );
    expect(find.textContaining('regra cortada'), findsOneWidget);
    expect(find.textContaining('soma R'), findsOneWidget);
    expect(find.textContaining('vwap_reclaim'), findsWidgets);
  });

  testWidgets('SignalsPanelBody shows cut rule even without signals',
      (tester) async {
    await tester.pumpWidget(
      const MaterialApp(
        home: Scaffold(
          body: SignalsPanelBody(
            signals: [],
            gatedRules: ['vwap_reclaim'],
          ),
        ),
      ),
    );
    expect(find.textContaining('regra cortada'), findsOneWidget);
    expect(find.textContaining('soma R'), findsOneWidget);
  });

  testWidgets('SignalsPanelBody empty state explains the stall', (tester) async {
    await tester.pumpWidget(
      const MaterialApp(
        home: Scaffold(body: SignalsPanelBody(signals: [])),
      ),
    );
    expect(find.textContaining('Nenhum sinal day trade ainda'), findsOneWidget);
  });

  testWidgets('SignalsPanelBody renders expired signals without a P&L badge',
      (tester) async {
    final signals = [_signal(ticker: 'TSLA', status: 'expired')];

    await tester.pumpWidget(
      MaterialApp(home: Scaffold(body: SignalsPanelBody(signals: signals))),
    );

    expect(find.text('expired'), findsOneWidget);
    expect(find.text('0 abertos'), findsOneWidget);
    expect(find.text('0 fechados'), findsOneWidget);
  });

  testWidgets('SignalsPanelBody sorts newest first', (tester) async {
    final signals = [
      _signal(
        ticker: 'OLD',
        status: 'closed',
        pnl: 1.0,
        createdAt: DateTime(2026, 9, 12, 9, 40),
      ),
      _signal(
        ticker: 'NEW',
        status: 'closed',
        pnl: 1.0,
        createdAt: DateTime(2026, 9, 12, 15, 10),
      ),
    ];

    await tester.pumpWidget(
      MaterialApp(home: Scaffold(body: SignalsPanelBody(signals: signals))),
    );

    final newY = tester.getTopLeft(find.text('NEW')).dy;
    final oldY = tester.getTopLeft(find.text('OLD')).dy;
    expect(newY, lessThan(oldY));
  });
}
