import 'json.dart';

/// Ponto da curva de P&L (equity) de uma conta.
class PnlSeriesPoint {
  const PnlSeriesPoint({
    required this.date,
    required this.cumulativePnl,
    this.dayPnl = 0,
    this.targetCumulativePnl = 0,
    this.dayTargetPnl = 0,
    this.dayPnlPct = 0,
    this.dayTargetPct = 7.0,
  });

  final DateTime date;
  final double cumulativePnl;
  final double dayPnl;
  final double targetCumulativePnl;
  final double dayTargetPnl;
  final double dayPnlPct;
  final double dayTargetPct;

  factory PnlSeriesPoint.fromJson(Map<String, dynamic> json) => PnlSeriesPoint(
        date: DateTime.tryParse(asString(json['date'])) ?? DateTime.now(),
        cumulativePnl: asDouble(json['cumulative_pnl']),
        dayPnl: asDouble(json['day_pnl']),
        targetCumulativePnl: asDouble(json['target_cumulative_pnl']),
        dayTargetPnl: asDouble(json['day_target_pnl']),
        dayPnlPct: asDouble(json['day_pnl_pct']),
        dayTargetPct: asDouble(json['day_target_pct']),
      );
}

/// Série de P&L + metas de uma conta.
class PnlSeries {
  const PnlSeries({
    required this.period,
    this.strategyKind,
    this.currency = 'BRL',
    this.from,
    this.points = const [],
    this.dailyTargetPct = 7.0,
    this.equityRef = 0,
  });

  final String period;
  final String? strategyKind;
  final String currency;
  final DateTime? from;
  final List<PnlSeriesPoint> points;
  final double dailyTargetPct;
  final double equityRef;

  factory PnlSeries.fromJson(Map<String, dynamic> json) => PnlSeries(
        period: asString(json['period']),
        strategyKind: asStringOrNull(json['strategy_kind']),
        currency: asString(json['currency'], 'BRL'),
        from: DateTime.tryParse(asString(json['from'])),
        points: asListOf(json['points'], PnlSeriesPoint.fromJson),
        dailyTargetPct: asDouble(json['daily_target_pct'], 7.0),
        equityRef: asDouble(json['equity_ref']),
      );
}
