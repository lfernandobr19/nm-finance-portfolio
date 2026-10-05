import '../../core/api_client.dart';
import '../models/pnl_series.dart';
import '../models/position.dart';

/// Typed access to portfolio snapshot, positions, and P&L series.
class PortfolioRepository {
  PortfolioRepository(this._api);

  final ApiClient _api;

  Future<Portfolio> getPortfolio(String accountId) async {
    final raw = await _api.getMap('/accounts/$accountId/portfolio');
    return Portfolio.fromJson(raw);
  }

  Future<List<Position>> listPositions(
    String accountId, {
    String? status,
    String? strategyKind,
  }) async {
    final query = <String, String>{
      if (status != null) 'status': status,
      if (strategyKind != null) 'strategy_kind': strategyKind,
    };
    final raw = await _api.getList('/accounts/$accountId/positions', query);
    return raw
        .whereType<Map>()
        .map((e) =>
            Position.fromJson(e.map((k, v) => MapEntry(k.toString(), v))))
        .toList();
  }

  Future<PnlSeries> getPnlSeries(
    String accountId, {
    String period = 'month',
    String? strategyKind,
  }) async {
    final query = <String, String>{
      'period': period,
      if (strategyKind != null) 'strategy_kind': strategyKind,
    };
    final raw = await _api.getMap('/accounts/$accountId/pnl/series', query);
    return PnlSeries.fromJson(raw);
  }

  Future<Map<String, dynamic>> getPnlReport(
    String accountId, {
    String period = 'year',
    String? strategyKind,
  }) async {
    final query = <String, String>{
      'period': period,
      if (strategyKind != null) 'strategy_kind': strategyKind,
    };
    return _api.getMap('/accounts/$accountId/pnl', query);
  }

  Future<Map<String, dynamic>> closePosition(
    String accountId,
    String positionId, {
    required String reason,
    double? price,
  }) async {
    return _api.post(
      '/accounts/$accountId/positions/$positionId/close',
      {
        'reason': reason,
        if (price != null) 'price': price,
      },
    );
  }

  /// "Comprar mais" em uma posição hv_dip aberta: gera nova sugestão pendente
  /// (tranche N+1) que passa pela revisão/auto-buy normal.
  Future<Map<String, dynamic>> suggestMore(
    String accountId,
    String positionId,
  ) async {
    return _api.post(
      '/accounts/$accountId/positions/$positionId/suggest-more',
      {},
    );
  }

  Future<Map<String, dynamic>> closeAllPositions(
    String accountId, {
    String? strategyKind,
  }) async {
    return _api.post(
      '/accounts/$accountId/positions/close-all',
      {},
      query: {if (strategyKind != null) 'strategy_kind': strategyKind},
    );
  }
}
