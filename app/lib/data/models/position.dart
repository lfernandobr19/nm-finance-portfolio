import 'json.dart';

/// Posição (aberta/fechada) de uma conta.
class Position {
  const Position({
    required this.id,
    required this.accountId,
    required this.ticker,
    required this.strategyKind,
    required this.quantity,
    required this.entryPrice,
    required this.status,
    required this.openedAt,
    this.orderId,
    this.suggestionId,
    this.stopPrice,
    this.targetPrice,
    this.setupLow,
    this.trancheIndex = 1,
    this.avgEntryPrice,
    this.exitReason,
    this.exitPrice,
    this.realizedPnlBrl,
    this.realizedPnlPct,
    this.rMultipleRealized,
    this.closedAt,
    this.markPrice,
    this.costBrl,
    this.marketValueBrl,
    this.unrealizedPnlBrl,
    this.unrealizedPnlPct,
    this.peakUnrealizedPct,
    this.priceAlert,
    this.exitState,
    this.latched5,
    this.protectActive,
    this.mustReviewBy,
    this.daysUntilReview,
  });

  final String id;
  final String accountId;
  final String ticker;
  final String strategyKind;
  final double quantity;
  final double entryPrice;
  final String status;
  final DateTime openedAt;
  final String? orderId;
  final String? suggestionId;
  final double? stopPrice;
  final double? targetPrice;
  final double? setupLow;
  final int trancheIndex;
  final double? avgEntryPrice;
  final String? exitReason;
  final double? exitPrice;
  final double? realizedPnlBrl;
  final double? realizedPnlPct;
  final double? rMultipleRealized;
  final DateTime? closedAt;
  final double? markPrice;
  final double? costBrl;
  final double? marketValueBrl;
  final double? unrealizedPnlBrl;
  final double? unrealizedPnlPct;
  final double? peakUnrealizedPct;
  final String? priceAlert;
  final String? exitState;
  final bool? latched5;
  final bool? protectActive;
  final String? mustReviewBy;
  final int? daysUntilReview;

  factory Position.fromJson(Map<String, dynamic> json) => Position(
        id: asString(json['id']),
        accountId: asString(json['account_id']),
        ticker: asString(json['ticker']),
        strategyKind: asString(json['strategy_kind']),
        quantity: asDouble(json['quantity']),
        entryPrice: asDouble(json['entry_price']),
        status: asString(json['status']),
        openedAt:
            DateTime.tryParse(asString(json['opened_at'])) ?? DateTime.now(),
        orderId: asStringOrNull(json['order_id']),
        suggestionId: asStringOrNull(json['suggestion_id']),
        stopPrice: asDoubleOrNull(json['stop_price']),
        targetPrice: asDoubleOrNull(json['target_price']),
        setupLow: asDoubleOrNull(json['setup_low']),
        trancheIndex: asInt(json['tranche_index'], 1),
        avgEntryPrice: asDoubleOrNull(json['avg_entry_price']),
        exitReason: asStringOrNull(json['exit_reason']),
        exitPrice: asDoubleOrNull(json['exit_price']),
        realizedPnlBrl: asDoubleOrNull(json['realized_pnl_brl']),
        realizedPnlPct: asDoubleOrNull(json['realized_pnl_pct']),
        rMultipleRealized: asDoubleOrNull(json['r_multiple_realized']),
        closedAt: DateTime.tryParse(asString(json['closed_at'])),
        markPrice: asDoubleOrNull(json['mark_price']),
        costBrl: asDoubleOrNull(json['cost_brl']),
        marketValueBrl: asDoubleOrNull(json['market_value_brl']),
        unrealizedPnlBrl: asDoubleOrNull(json['unrealized_pnl_brl']),
        unrealizedPnlPct: asDoubleOrNull(json['unrealized_pnl_pct']),
        peakUnrealizedPct: asDoubleOrNull(json['peak_unrealized_pct']),
        priceAlert: asStringOrNull(json['price_alert']),
        exitState: asStringOrNull(json['exit_state']),
        latched5: json['latched_5'] == null ? null : asBool(json['latched_5']),
        protectActive: json['protect_active'] == null
            ? null
            : asBool(json['protect_active']),
        mustReviewBy: asStringOrNull(json['must_review_by']),
        daysUntilReview: json['days_until_review'] == null
            ? null
            : asInt(json['days_until_review']),
      );
}

/// Snapshot de portfólio (cash/equity/posições) de uma conta.
class Portfolio {
  const Portfolio({
    required this.cashBrl,
    required this.investedOpenBrl,
    required this.equityBrl,
    required this.openPositions,
    required this.realizedPnlDayBrl,
    this.marketValueOpenBrl = 0,
    this.unrealizedPnlBrl = 0,
    this.equityCostBrl,
    this.openSwing = 0,
    this.openIncome = 0,
    this.openHvDip = 0,
    this.currency = 'BRL',
    this.cashUsd,
    this.cashPctOfEquity,
  });

  final double cashBrl;
  final double investedOpenBrl;
  final double marketValueOpenBrl;
  final double unrealizedPnlBrl;
  final double equityBrl;
  final double? equityCostBrl;
  final int openPositions;
  final int openSwing;
  final int openIncome;
  final int openHvDip;
  final double realizedPnlDayBrl;
  final String currency;
  final double? cashUsd;
  final double? cashPctOfEquity;

  factory Portfolio.fromJson(Map<String, dynamic> json) => Portfolio(
        cashBrl: asDouble(json['cash_brl']),
        investedOpenBrl: asDouble(json['invested_open_brl']),
        marketValueOpenBrl: asDouble(json['market_value_open_brl']),
        unrealizedPnlBrl: asDouble(json['unrealized_pnl_brl']),
        equityBrl: asDouble(json['equity_brl']),
        equityCostBrl: asDoubleOrNull(json['equity_cost_brl']),
        openPositions: asInt(json['open_positions']),
        openSwing: asInt(json['open_swing']),
        openIncome: asInt(json['open_income']),
        openHvDip: asInt(json['open_hv_dip']),
        realizedPnlDayBrl: asDouble(json['realized_pnl_day_brl']),
        currency: asString(json['currency'], 'BRL'),
        cashUsd: asDoubleOrNull(json['cash_usd']),
        cashPctOfEquity: asDoubleOrNull(json['cash_pct_of_equity']),
      );
}
