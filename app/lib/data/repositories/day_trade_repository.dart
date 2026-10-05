import '../../core/api_client.dart';
import '../models/day_trade.dart';

/// Typed access to day-trade signals, analytics, config, and live state.
class DayTradeRepository {
  DayTradeRepository(this._api);

  final ApiClient _api;

  Future<List<DayTradeSignal>> listSignals(String accountId) async {
    final raw = await _api.getList('/accounts/$accountId/day-trade/signals');
    return raw
        .whereType<Map>()
        .map((e) =>
            DayTradeSignal.fromJson(e.map((k, v) => MapEntry(k.toString(), v))))
        .toList();
  }

  Future<List<IntradayBar>> intradayBars(
    String accountId,
    String ticker,
  ) async {
    final raw = await _api.getList(
      '/accounts/$accountId/tickers/$ticker/bars/intraday',
      {'timeframe': '5m'},
    );
    return raw
        .whereType<Map>()
        .map((e) =>
            IntradayBar.fromJson(e.map((k, v) => MapEntry(k.toString(), v))))
        .toList();
  }

  Future<DayTradeAnalytics> getAnalytics(String accountId) async {
    final raw = await _api.getMap('/accounts/$accountId/day-trade/analytics');
    return DayTradeAnalytics.fromJson(raw);
  }

  Future<DayTradeConfig> getConfig(String accountId) async {
    final raw = await _api.getMap('/accounts/$accountId/day-trade/config');
    return DayTradeConfig.fromJson(raw);
  }

  Future<List<DayTradeConfigHistory>> getConfigHistory(String accountId) async {
    final raw =
        await _api.getList('/accounts/$accountId/day-trade/config/history');
    return raw
        .whereType<Map>()
        .map((e) => DayTradeConfigHistory.fromJson(
            e.map((k, v) => MapEntry(k.toString(), v))))
        .toList();
  }

  Future<DayTradeState> getState(String accountId) async {
    final raw = await _api.getMap('/accounts/$accountId/day-trade/state');
    return DayTradeState.fromJson(raw);
  }

  Future<DayTradeConfig> rollbackConfig(String accountId, int version) async {
    final raw = await _api.post(
      '/accounts/$accountId/day-trade/config/rollback',
      const {},
      query: {'version': '$version'},
    );
    return DayTradeConfig.fromJson(raw);
  }
}
