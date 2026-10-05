import 'package:flutter_test/flutter_test.dart';

import 'package:fiidesk/core/pnl_line_chart.dart';
import 'package:fiidesk/data/models/account.dart';
import 'package:fiidesk/data/models/order.dart';
import 'package:fiidesk/data/models/pnl_series.dart';
import 'package:fiidesk/data/models/position.dart';
import 'package:fiidesk/features/dashboard/dashboard_controller.dart';
import 'package:fiidesk/features/dashboard/dashboard_data.dart';

Account _account({String currency = 'BRL', String broker = 'inter'}) => Account(
      id: 'id-$currency-$broker',
      name: 'conta',
      ownerUserId: 'u1',
      targetCapital: 0,
      currency: currency,
      brokerCode: broker,
    );

void main() {
  test('isUsdAccount detects USD currency and alpaca broker', () {
    expect(DashboardController.isUsdAccount(_account(currency: 'BRL')), isFalse);
    expect(DashboardController.isUsdAccount(_account(currency: 'USD')), isTrue);
    expect(
      DashboardController.isUsdAccount(_account(currency: 'BRL', broker: 'alpaca')),
      isTrue,
    );
  });

  test('mergePnlSeries sums cumulative and target across accounts by day', () {
    final a = PnlSeries(
      period: 'month',
      points: [
        PnlSeriesPoint(
          date: DateTime(2026, 8, 1),
          cumulativePnl: 10,
          dayPnl: 10,
          targetCumulativePnl: 7,
          dayTargetPnl: 7,
        ),
        PnlSeriesPoint(
          date: DateTime(2026, 8, 2),
          cumulativePnl: 15,
          dayPnl: 5,
          targetCumulativePnl: 14,
          dayTargetPnl: 7,
        ),
      ],
    );
    final b = PnlSeries(
      period: 'month',
      points: [
        PnlSeriesPoint(
          date: DateTime(2026, 8, 1),
          cumulativePnl: 4,
          dayPnl: 4,
          targetCumulativePnl: 7,
          dayTargetPnl: 7,
        ),
      ],
    );
    final merged = DashboardController.mergePnlSeries([a, b]);
    expect(merged.length, 2);
    expect(merged[0].cumulativePnl, 14);
    expect(merged[0].targetCumulativePnl, 14);
    expect(merged[1].cumulativePnl, 15);
  });

  test('buildAllocation groups by ticker and computes percentages', () {
    final positions = [
      Position(
        id: '1',
        accountId: 'a',
        ticker: 'PETR4',
        strategyKind: 'swing',
        quantity: 2,
        entryPrice: 5,
        status: 'open',
        openedAt: DateTime(2026, 1, 1),
        marketValueBrl: 100,
      ),
      Position(
        id: '2',
        accountId: 'a',
        ticker: 'PETR4',
        strategyKind: 'swing',
        quantity: 2,
        entryPrice: 5,
        status: 'open',
        openedAt: DateTime(2026, 1, 1),
        marketValueBrl: 50,
      ),
      Position(
        id: '3',
        accountId: 'a',
        ticker: 'ITSA4',
        strategyKind: 'swing',
        quantity: 1,
        entryPrice: 10,
        status: 'open',
        openedAt: DateTime(2026, 1, 1),
        marketValueBrl: 50,
      ),
    ];
    final slices = DashboardController.buildAllocation(positions);
    expect(slices.length, 2);
    expect(slices[0].ticker, 'PETR4');
    expect(slices[0].value, 150);
    expect(slices[0].pct, closeTo(75.0, 0.001));
    expect(slices[1].ticker, 'ITSA4');
    expect(slices[1].pct, closeTo(25.0, 0.001));
  });

  test('buildActivity maps orders with filled price and currency', () {
    final orders = [
      Order(
        id: 'o1',
        accountId: 'a',
        ticker: 'MARA',
        side: 'buy',
        quantity: 2,
        amountBrl: 20,
        limitPrice: 10,
        status: 'filled',
        broker: 'alpaca',
        executionMode: 'paper',
        createdAt: DateTime(2026, 8, 30),
        filledPrice: 10,
      ),
    ];
    final items = DashboardController.buildActivity(orders, currency: 'USD');
    expect(items.length, 1);
    expect(items[0].ticker, 'MARA');
    expect(items[0].side, 'buy');
    expect(items[0].price, 10);
    expect(items[0].currency, 'USD');
  });

  test('buildActivity falls back to limit price when not filled', () {
    final orders = [
      Order(
        id: 'o2',
        accountId: 'a',
        ticker: 'LCID',
        side: 'buy',
        quantity: 1,
        amountBrl: 5,
        limitPrice: 5,
        status: 'queued',
        broker: 'alpaca',
        executionMode: 'paper',
        createdAt: DateTime(2026, 8, 30),
      ),
    ];
    final items = DashboardController.buildActivity(orders, currency: 'USD');
    expect(items[0].price, 5);
  });

  test('totalPnl sums realized and unrealized', () {
    final bucket = CurrencyBucket(
      currency: 'BRL',
      label: 'Brasil',
      cash: 0,
      invested: 0,
      marketValue: 0,
      equity: 0,
      unrealizedPnl: -30,
      realizedPnl: 50,
      realizedPnlDay: 0,
      openPositions: 0,
      pnlPoints: const [],
      allocation: const [],
      positions: const [],
    );
    expect(bucket.totalPnl, 20);
  });

  test('buildProfitCurve folds unrealized into the last point', () {
    final realized = [
      PnlPoint(date: DateTime(2026, 8, 1), cumulativePnl: 0),
      PnlPoint(date: DateTime(2026, 8, 2), cumulativePnl: 12),
      PnlPoint(date: DateTime(2026, 8, 3), cumulativePnl: 20),
    ];
    final curve = DashboardController.buildProfitCurve(realized, 5);
    expect(curve.length, 3);
    expect(curve.first.cumulativePnl, 0); // base em 0
    expect(curve[1].cumulativePnl, 12);
    expect(curve.last.cumulativePnl, 25); // 20 + 5
  });

  test('buildProfitCurve with empty series returns 0 -> unrealized', () {
    final curve = DashboardController.buildProfitCurve(const [], -7);
    expect(curve.length, 2);
    expect(curve.first.cumulativePnl, 0);
    expect(curve.last.cumulativePnl, -7);
  });
}
