import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:fiidesk/core/pnl_line_chart.dart';
import 'package:fiidesk/features/dashboard/dashboard_data.dart';
import 'package:fiidesk/features/dashboard/widgets/allocation_pie.dart';
import 'package:fiidesk/features/dashboard/widgets/currency_bucket_card.dart';
import 'package:fiidesk/features/dashboard/widgets/profit_curve_card.dart';
import 'package:fiidesk/features/dashboard/widgets/stat_card.dart';

CurrencyBucket _bucket({required double unrealized, required double realized}) {
  return CurrencyBucket(
    currency: 'USD',
    label: 'EUA',
    cash: 100,
    invested: 200,
    marketValue: 300,
    equity: 400,
    unrealizedPnl: unrealized,
    realizedPnl: realized,
    realizedPnlDay: 5,
    openPositions: 2,
    pnlPoints: const [],
    allocation: const [],
    positions: const [],
  );
}

void main() {
  testWidgets('DashboardStatCard renders label and value', (tester) async {
    await tester.pumpWidget(
      const MaterialApp(
        home: Scaffold(
          body: DashboardStatCard(label: 'Caixa', value: 'R\$ 100,00'),
        ),
      ),
    );
    expect(find.text('Caixa'), findsOneWidget);
    expect(find.text('R\$ 100,00'), findsOneWidget);
  });

  testWidgets('AllocationPieChart renders with slices', (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: AllocationPieChart(
            currency: 'BRL',
            slices: const [
              AllocationSlice(ticker: 'PETR4', value: 60, pct: 60),
              AllocationSlice(ticker: 'ITSA4', value: 40, pct: 40),
            ],
          ),
        ),
      ),
    );
    expect(find.text('PETR4'), findsOneWidget);
    expect(find.text('ITSA4'), findsOneWidget);
  });

  testWidgets('AllocationPieChart shows empty state', (tester) async {
    await tester.pumpWidget(
      const MaterialApp(
        home: Scaffold(
          body: AllocationPieChart(currency: 'BRL', slices: []),
        ),
      ),
    );
    expect(find.text('Sem posições abertas para alocar.'), findsOneWidget);
  });

  testWidgets('CurrencyBucketCard shows green Lucro for positive total', (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: CurrencyBucketCard(
            bucket: _bucket(unrealized: 10, realized: 20),
          ),
        ),
      ),
    );
    expect(find.text('Lucro'), findsOneWidget);
  });

  testWidgets('CurrencyBucketCard shows red Prejuízo for negative total', (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: CurrencyBucketCard(
            bucket: _bucket(unrealized: -40, realized: 10),
          ),
        ),
      ),
    );
    expect(find.text('Prejuízo'), findsOneWidget);
  });

  testWidgets('ProfitCurveCard renders with points', (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: ProfitCurveCard(
            currency: 'USD',
            period: 'month',
            onPeriodChanged: (_) {},
            points: [
              PnlPoint(date: DateTime(2026, 8, 1), cumulativePnl: 0),
              PnlPoint(date: DateTime(2026, 8, 2), cumulativePnl: 12),
            ],
          ),
        ),
      ),
    );
    expect(find.text('Lucro no período'), findsOneWidget);
  });
}

