import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:fiidesk/features/suggestions/desk/desk_summary_header.dart';

void main() {
  testWidgets('DeskSummaryHeader shows equity and market pill', (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: DeskSummaryHeader(
            portfolio: {
              'equity_brl': 100.0,
              'cash_brl': 100.0,
              'realized_pnl_day_brl': 7.55,
            },
            isUs: true,
            moneyCcy: 'USD',
            openCount: 0,
            waitingCount: 1,
            onTapSummary: () {},
            onTapMarket: () {},
          ),
        ),
      ),
    );

    expect(find.text('US\$100.00'), findsOneWidget);
    expect(find.textContaining('Nasdaq'), findsOneWidget);
    expect(find.textContaining('1 fila'), findsOneWidget);
  });
}
