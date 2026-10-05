import 'json.dart';

/// Estatística agrupada de sinais day-trade (por rule/ticker/side).
class DayTradeGroupStat {
  const DayTradeGroupStat({
    required this.key,
    this.n = 0,
    this.wins = 0,
    this.losses = 0,
    this.winRate = 0,
    this.winRateLo = 0,
    this.winRateHi = 0,
    this.expectancyR,
    this.expectancyRLo,
    this.expectancyRHi,
    this.profitFactor,
    this.avgHoldMinutes,
    this.totalPnl = 0,
    this.totalR = 0,
  });

  final String key;
  final int n;
  final int wins;
  final int losses;
  final double winRate;
  final double winRateLo;
  final double winRateHi;
  final double? expectancyR;
  final double? expectancyRLo;
  final double? expectancyRHi;
  final double? profitFactor;
  final double? avgHoldMinutes;
  final double totalPnl;
  final double totalR;

  factory DayTradeGroupStat.fromJson(Map<String, dynamic> json) =>
      DayTradeGroupStat(
        key: asString(json['key']),
        n: asInt(json['n']),
        wins: asInt(json['wins']),
        losses: asInt(json['losses']),
        winRate: asDouble(json['win_rate']),
        winRateLo: asDouble(json['win_rate_lo']),
        winRateHi: asDouble(json['win_rate_hi']),
        expectancyR: asDoubleOrNull(json['expectancy_r']),
        expectancyRLo: asDoubleOrNull(json['expectancy_r_lo']),
        expectancyRHi: asDoubleOrNull(json['expectancy_r_hi']),
        profitFactor: asDoubleOrNull(json['profit_factor']),
        avgHoldMinutes: asDoubleOrNull(json['avg_hold_minutes']),
        totalPnl: asDouble(json['total_pnl']),
        totalR: asDouble(json['total_r']),
      );
}

/// Analytics de performance dos sinais day-trade fechados.
class DayTradeAnalytics {
  const DayTradeAnalytics({
    this.totalClosed = 0,
    this.byRule = const [],
    this.byTicker = const [],
    this.bySide = const [],
  });

  final int totalClosed;
  final List<DayTradeGroupStat> byRule;
  final List<DayTradeGroupStat> byTicker;
  final List<DayTradeGroupStat> bySide;

  factory DayTradeAnalytics.fromJson(Map<String, dynamic> json) =>
      DayTradeAnalytics(
        totalClosed: asInt(json['total_closed']),
        byRule: asListOf(json['by_rule'], DayTradeGroupStat.fromJson),
        byTicker: asListOf(json['by_ticker'], DayTradeGroupStat.fromJson),
        bySide: asListOf(json['by_side'], DayTradeGroupStat.fromJson),
      );
}

/// Sinal day-trade (intraday) com P&L simulado.
class DayTradeSignal {
  const DayTradeSignal({
    required this.id,
    required this.accountId,
    required this.sessionDate,
    required this.ticker,
    required this.ruleId,
    required this.side,
    required this.entryPrice,
    required this.stopPrice,
    required this.targetPrice,
    required this.status,
    required this.createdAt,
    this.simulatedPnlUsd,
    this.metrics = const {},
    this.closedAt,
  });

  final String id;
  final String accountId;
  final DateTime sessionDate;
  final String ticker;
  final String ruleId;
  final String side;
  final double entryPrice;
  final double stopPrice;
  final double targetPrice;
  final String status;
  final double? simulatedPnlUsd;
  final Map<String, dynamic> metrics;
  final DateTime createdAt;
  final DateTime? closedAt;

  factory DayTradeSignal.fromJson(Map<String, dynamic> json) => DayTradeSignal(
        id: asString(json['id']),
        accountId: asString(json['account_id']),
        sessionDate:
            DateTime.tryParse(asString(json['session_date'])) ?? DateTime.now(),
        ticker: asString(json['ticker']),
        ruleId: asString(json['rule_id']),
        side: asString(json['side']),
        entryPrice: asDouble(json['entry_price']),
        stopPrice: asDouble(json['stop_price']),
        targetPrice: asDouble(json['target_price']),
        status: asString(json['status']),
        simulatedPnlUsd: asDoubleOrNull(json['simulated_pnl_usd']),
        metrics: asMap(json['metrics']),
        createdAt:
            DateTime.tryParse(asString(json['created_at'])) ?? DateTime.now(),
        closedAt: DateTime.tryParse(asString(json['closed_at'])),
      );
}

/// Barra OHLC intraday (5m) para o gráfico day-trade.
class IntradayBar {
  const IntradayBar({
    required this.ts,
    required this.open,
    required this.high,
    required this.low,
    required this.close,
    required this.volume,
  });

  final DateTime ts;
  final double open;
  final double high;
  final double low;
  final double close;
  final double volume;

  factory IntradayBar.fromJson(Map<String, dynamic> json) => IntradayBar(
        ts: DateTime.tryParse(asString(json['ts'])) ?? DateTime.now(),
        open: asDouble(json['open']),
        high: asDouble(json['high']),
        low: asDouble(json['low']),
        close: asDouble(json['close']),
        volume: asDouble(json['volume']),
      );
}

/// Config ativa do loop day-trade.
class DayTradeConfig {
  const DayTradeConfig({
    required this.version,
    required this.isActive,
    required this.params,
    required this.origin,
    this.validation = const {},
    this.activatedAt,
    this.createdAt,
  });

  final int version;
  final bool isActive;
  final Map<String, dynamic> params;
  final String origin;
  final Map<String, dynamic> validation;
  final DateTime? activatedAt;
  final DateTime? createdAt;

  factory DayTradeConfig.fromJson(Map<String, dynamic> json) => DayTradeConfig(
        version: asInt(json['version']),
        isActive: asBool(json['is_active']),
        params: asMap(json['params']),
        origin: asString(json['origin']),
        validation: asMap(json['validation']),
        activatedAt: DateTime.tryParse(asString(json['activated_at'])),
        createdAt: DateTime.tryParse(asString(json['created_at'])),
      );
}

class DayTradeConfigHistory {
  const DayTradeConfigHistory({
    required this.version,
    required this.origin,
    required this.reason,
    this.validation = const {},
    this.createdAt,
  });

  final int version;
  final String origin;
  final String reason;
  final Map<String, dynamic> validation;
  final DateTime? createdAt;

  factory DayTradeConfigHistory.fromJson(Map<String, dynamic> json) =>
      DayTradeConfigHistory(
        version: asInt(json['version']),
        origin: asString(json['origin']),
        reason: asString(json['reason']),
        validation: asMap(json['validation']),
        createdAt: DateTime.tryParse(asString(json['created_at'])),
      );
}

/// Regime de sessão de um ticker (trend/chop/warmup).
class DayTradeRegime {
  const DayTradeRegime({
    required this.ticker,
    required this.regime,
    this.slope,
  });

  final String ticker;
  final String regime;
  final double? slope;

  factory DayTradeRegime.fromJson(Map<String, dynamic> json) => DayTradeRegime(
        ticker: asString(json['ticker']),
        regime: asString(json['regime']),
        slope: asDoubleOrNull(json['slope']),
      );
}

/// Estado vivo do day-trade: circuit breaker + regimes por ticker.
class DayTradeState {
  const DayTradeState({
    this.circuitBreakerTripped = const [],
    this.regimes = const [],
  });

  final List<String> circuitBreakerTripped;
  final List<DayTradeRegime> regimes;

  factory DayTradeState.fromJson(Map<String, dynamic> json) => DayTradeState(
        circuitBreakerTripped:
            asList(json['circuit_breaker_tripped']).map(asString).toList(),
        regimes: asListOf(json['regimes'], DayTradeRegime.fromJson),
      );
}
