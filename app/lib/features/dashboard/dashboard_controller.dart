import 'package:flutter/foundation.dart';

import '../../core/api_client.dart';
import '../../core/pnl_line_chart.dart';
import '../../data/models/account.dart';
import '../../data/models/order.dart';
import '../../data/models/pnl_series.dart';
import '../../data/models/position.dart';
import '../../data/repositories/accounts_repository.dart';
import '../../data/repositories/orders_repository.dart';
import '../../data/repositories/portfolio_repository.dart';
import 'dashboard_data.dart';

/// Carrega e agrega, no cliente, todas as contas em dois blocos por moeda
/// (Brasil/BRL e EUA/USD). Sem endpoint novo no backend.
class DashboardController extends ChangeNotifier {
  DashboardController(this._api);

  final ApiClient _api;

  bool loading = false;
  String? error;
  String period = 'month'; // day | week | month | year
  DashboardData? data;

  Future<void> load() async {
    loading = true;
    error = null;
    notifyListeners();
    try {
      final accounts = await AccountsRepository(_api).list();
      final pfRepo = PortfolioRepository(_api);
      final ordersRepo = OrdersRepository(_api);

      final brlAccounts = accounts.where((a) => !isUsdAccount(a)).toList();
      final usdAccounts = accounts.where(isUsdAccount).toList();

      final brl = await _buildBucket(
        pfRepo,
        accounts: brlAccounts,
        currency: 'BRL',
        label: 'Brasil',
      );
      final usd = await _buildBucket(
        pfRepo,
        accounts: usdAccounts,
        currency: 'USD',
        label: 'EUA',
      );

      final activity = await _loadActivity(
        ordersRepo,
        brlAccounts: brlAccounts,
        usdAccounts: usdAccounts,
      );

      data = DashboardData(
        brl: brl,
        usd: usd,
        activity: activity,
        updatedAt: DateTime.now(),
      );
    } catch (e) {
      error = formatApiError(e);
    } finally {
      loading = false;
      notifyListeners();
    }
  }

  Future<void> setPeriod(String next) async {
    if (next == period) return;
    period = next;
    await load();
  }

  Future<CurrencyBucket?> _buildBucket(
    PortfolioRepository pfRepo, {
    required List<Account> accounts,
    required String currency,
    required String label,
  }) async {
    if (accounts.isEmpty) return null;

    var cash = 0.0;
    var invested = 0.0;
    var marketValue = 0.0;
    var equity = 0.0;
    var unrealized = 0.0;
    var realized = 0.0;
    var realizedDay = 0.0;
    var openPositions = 0;
    final positions = <Position>[];
    final series = <PnlSeries>[];

    for (final a in accounts) {
      final pf = await pfRepo.getPortfolio(a.id);
      cash += pf.cashBrl;
      invested += pf.investedOpenBrl;
      marketValue += pf.marketValueOpenBrl;
      equity += pf.equityBrl;
      unrealized += pf.unrealizedPnlBrl;
      realizedDay += pf.realizedPnlDayBrl;
      openPositions += pf.openPositions;

      final open = await pfRepo.listPositions(a.id, status: 'open');
      positions.addAll(open);

      final s = await pfRepo.getPnlSeries(a.id, period: period);
      series.add(s);

      final report = await pfRepo.getPnlReport(a.id, period: 'year');
      realized += _scorecardRealized(report);
    }

    return CurrencyBucket(
      currency: currency,
      label: label,
      cash: _round(cash),
      invested: _round(invested),
      marketValue: _round(marketValue),
      equity: _round(equity),
      unrealizedPnl: _round(unrealized),
      realizedPnl: _round(realized),
      realizedPnlDay: _round(realizedDay),
      openPositions: openPositions,
      pnlPoints: mergePnlSeries(series),
      allocation: buildAllocation(positions),
      positions: positions,
    );
  }

  Future<List<ActivityItem>> _loadActivity(
    OrdersRepository ordersRepo, {
    required List<Account> brlAccounts,
    required List<Account> usdAccounts,
  }) async {
    final items = <ActivityItem>[];
    for (final a in brlAccounts) {
      items.addAll(buildActivity(await ordersRepo.list(a.id), currency: 'BRL'));
    }
    for (final a in usdAccounts) {
      items.addAll(buildActivity(await ordersRepo.list(a.id), currency: 'USD'));
    }
    items.sort((x, y) => y.at.compareTo(x.at));
    return items.take(6).toList();
  }

  static double _scorecardRealized(Map<String, dynamic> report) {
    final scorecard = report['scorecard'];
    if (scorecard is! Map) return 0.0;
    final v = scorecard['realized_pnl'];
    return v is num ? v.toDouble() : 0.0;
  }

  static double _round(double v) => (v * 100).roundToDouble() / 100;

  // ---- Helpers puros (testáveis) ----

  static bool isUsdAccount(Account a) =>
      a.currency.toUpperCase() == 'USD' || a.brokerCode.toLowerCase() == 'alpaca';

  /// Soma as curvas diárias de várias contas por data (realizado + meta).
  static List<PnlPoint> mergePnlSeries(List<PnlSeries> series) {
    final byDate = <DateTime, PnlPoint>{};
    for (final s in series) {
      for (final p in s.points) {
        final day = DateTime(p.date.year, p.date.month, p.date.day);
        final existing = byDate[day];
        byDate[day] = PnlPoint(
          date: p.date,
          cumulativePnl: (existing?.cumulativePnl ?? 0) + p.cumulativePnl,
          dayPnl: (existing?.dayPnl ?? 0) + p.dayPnl,
          targetCumulativePnl: (existing?.targetCumulativePnl ?? 0) +
              p.targetCumulativePnl,
          dayTargetPnl: (existing?.dayTargetPnl ?? 0) + p.dayTargetPnl,
          dayPnlPct: (existing?.dayPnlPct ?? 0) + p.dayPnlPct,
          dayTargetPct: (existing?.dayTargetPct ?? 0) + p.dayTargetPct,
        );
      }
    }
    final keys = byDate.keys.toList()..sort();
    return keys.map((k) => byDate[k]!).toList();
  }

  /// Curva de lucro começando em 0; dobra o não realizado no último ponto.
  ///
  /// A série `/pnl/series` traz só o realizado (fica em 0 para contas com
  /// posições abertas). Para mostrar "no verde ou no vermelho", somamos o não
  /// realizado corrente ao último ponto — preservando a base 0 no início.
  static List<PnlPoint> buildProfitCurve(
    List<PnlPoint> realized,
    double unrealized,
  ) {
    if (realized.isEmpty) {
      return [
        PnlPoint(date: DateTime.now(), cumulativePnl: 0),
        PnlPoint(date: DateTime.now(), cumulativePnl: unrealized),
      ];
    }
    final out = List<PnlPoint>.of(realized);
    final last = out.last;
    out[out.length - 1] = PnlPoint(
      date: last.date,
      cumulativePnl: last.cumulativePnl + unrealized,
      dayPnl: last.dayPnl,
      targetCumulativePnl: last.targetCumulativePnl,
      dayTargetPnl: last.dayTargetPnl,
      dayPnlPct: last.dayPnlPct,
      dayTargetPct: last.dayTargetPct,
    );
    return out;
  }

  /// Alocação por ativo (top tickers por valor de mercado).
  static List<AllocationSlice> buildAllocation(List<Position> positions) {
    final byTicker = <String, double>{};
    for (final p in positions) {
      final v = p.marketValueBrl ??
          p.costBrl ??
          (p.entryPrice * p.quantity);
      byTicker[p.ticker] = (byTicker[p.ticker] ?? 0) + v;
    }
    final total =
        byTicker.values.fold<double>(0, (sum, v) => sum + v);
    final sorted = byTicker.entries.toList()
      ..sort((a, b) => b.value.compareTo(a.value));
    return [
      for (final e in sorted)
        AllocationSlice(
          ticker: e.key,
          value: _round(e.value),
          pct: total > 0 ? (e.value / total) * 100 : 0,
        ),
    ];
  }

  /// Movimentações a partir de ordens (lado, quantidade e preço preenchidos).
  static List<ActivityItem> buildActivity(
    List<Order> orders, {
    required String currency,
  }) {
    return [
      for (final o in orders)
        ActivityItem(
          id: o.id,
          ticker: o.ticker,
          side: o.side,
          quantity: o.quantity,
          price: o.filledPrice ?? o.limitPrice,
          status: o.status,
          currency: currency,
          at: o.filledAt ?? o.createdAt,
        ),
    ];
  }
}
