import 'json.dart';

/// Sugestão gerada pelas estratégias (income/swing/hv_dip).
class Suggestion {
  const Suggestion({
    required this.id,
    required this.accountId,
    required this.ticker,
    required this.strategyKind,
    required this.assetClass,
    required this.score,
    required this.status,
    required this.reasons,
    required this.metrics,
    required this.priceExplanation,
    required this.ruleVersion,
    required this.proposedAmountBrl,
    required this.expiresAt,
    required this.createdAt,
    this.dividendFrequency,
    this.swingScoreLetter,
    this.entryPrice,
    this.stopPrice,
    this.targetPrice,
    this.rMultiple,
    this.llmSummary,
    this.setupLow,
    this.trancheIndex = 1,
    this.reviewRequired = false,
    this.reviewReason,
    this.actedByUserId,
    this.actionNote,
    this.actedAt,
  });

  final String id;
  final String accountId;
  final String ticker;
  final String strategyKind;
  final String assetClass;
  final String? dividendFrequency;
  final double score;
  final String? swingScoreLetter;
  final double? entryPrice;
  final double? stopPrice;
  final double? targetPrice;
  final double? rMultiple;
  final String status;
  final List<dynamic> reasons;
  final Map<String, dynamic> metrics;
  final String priceExplanation;
  final String? llmSummary;
  final int ruleVersion;
  final double proposedAmountBrl;
  final double? setupLow;
  final int trancheIndex;
  final bool reviewRequired;
  final String? reviewReason;
  final String? actedByUserId;
  final String? actionNote;
  final DateTime? actedAt;
  final DateTime expiresAt;
  final DateTime createdAt;

  factory Suggestion.fromJson(Map<String, dynamic> json) => Suggestion(
        id: asString(json['id']),
        accountId: asString(json['account_id']),
        ticker: asString(json['ticker']),
        strategyKind: asString(json['strategy_kind'], 'income'),
        assetClass: asString(json['asset_class']),
        dividendFrequency: asStringOrNull(json['dividend_frequency']),
        score: asDouble(json['score']),
        swingScoreLetter: asStringOrNull(json['swing_score_letter']),
        entryPrice: asDoubleOrNull(json['entry_price']),
        stopPrice: asDoubleOrNull(json['stop_price']),
        targetPrice: asDoubleOrNull(json['target_price']),
        rMultiple: asDoubleOrNull(json['r_multiple']),
        status: asString(json['status']),
        reasons: asList(json['reasons']),
        metrics: asMap(json['metrics']),
        priceExplanation: asString(json['price_explanation']),
        llmSummary: asStringOrNull(json['llm_summary']),
        ruleVersion: asInt(json['rule_version']),
        proposedAmountBrl: asDouble(json['proposed_amount_brl']),
        setupLow: asDoubleOrNull(json['setup_low']),
        trancheIndex: asInt(json['tranche_index'], 1),
        reviewRequired: asBool(json['review_required']),
        reviewReason: asStringOrNull(json['review_reason']),
        actedByUserId: asStringOrNull(json['acted_by_user_id']),
        actionNote: asStringOrNull(json['action_note']),
        actedAt: DateTime.tryParse(asString(json['acted_at'])),
        expiresAt:
            DateTime.tryParse(asString(json['expires_at'])) ?? DateTime.now(),
        createdAt:
            DateTime.tryParse(asString(json['created_at'])) ?? DateTime.now(),
      );
}
