import 'package:fiidesk/core/candlestick_chart.dart';
import 'package:fiidesk/core/ohlc_chart.dart';
import 'package:fiidesk/core/pnl_line_chart.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

List<OhlcBar> _bars(int n) {
  final base = DateTime(2026, 1, 1);
  return [
    for (var i = 0; i < n; i++)
      OhlcBar(
        date: base.add(Duration(days: i)),
        open: 100 + i * 0.2,
        high: 102 + i * 0.2,
        low: 99 + i * 0.2,
        close: 101 + i * 0.2,
        volume: 1000000 + i * 10000,
      ),
  ];
}

void main() {
  testWidgets('InteractiveCandlestickChart renders candles + volume', (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: SizedBox(
            width: 600,
            height: 400,
            child: InteractiveCandlestickChart(
              bars: _bars(60),
              entry: 101,
              showStopTarget: true,
              stop: 99,
              target: 104,
              setupLow: 98,
            ),
          ),
        ),
      ),
    );
    await tester.pump();
    expect(find.byType(InteractiveCandlestickChart), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('InteractiveCandlestickChart handles few bars gracefully', (tester) async {
    await tester.pumpWidget(
      const MaterialApp(
        home: Scaffold(
          body: SizedBox(
            width: 400,
            height: 300,
            child: InteractiveCandlestickChart(bars: []),
          ),
        ),
      ),
    );
    await tester.pump();
    expect(find.textContaining('Gráfico indisponível'), findsOneWidget);
  });

  testWidgets('PnlLineChart renders realized + target line', (tester) async {
    final points = [
      for (var i = 0; i < 5; i++)
        PnlPoint(
          date: DateTime(2026, 1, 1).add(Duration(days: i)),
          cumulativePnl: 10.0 + i * 5,
          targetCumulativePnl: 12.0 + i * 6,
        ),
    ];
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: SizedBox(
            width: 600,
            height: 300,
            child: PnlLineChart(points: points, currency: 'BRL'),
          ),
        ),
      ),
    );
    await tester.pump();
    expect(tester.takeException(), isNull);
  });
}
