import 'json.dart';

/// Radar de observação (facas caindo) — estado persistido do hv_dip.
class Observation {
  const Observation({
    required this.ticker,
    required this.status,
    this.recoveryProbability,
    this.recoveryInProgress = false,
    this.activeCatalyst = false,
    this.lastDecision,
    this.note,
    this.firstSeenAt,
    this.lastEvaluatedAt,
    this.updatedAt,
  });

  final String ticker;
  final String status;
  final double? recoveryProbability;
  final bool recoveryInProgress;
  final bool activeCatalyst;
  final String? lastDecision;
  final String? note;
  final DateTime? firstSeenAt;
  final DateTime? lastEvaluatedAt;
  final DateTime? updatedAt;

  factory Observation.fromJson(Map<String, dynamic> json) => Observation(
        ticker: asString(json['ticker']),
        status: asString(json['status']),
        recoveryProbability: asDoubleOrNull(json['recovery_probability']),
        recoveryInProgress: asBool(json['recovery_in_progress']),
        activeCatalyst: asBool(json['active_catalyst']),
        lastDecision: asStringOrNull(json['last_decision']),
        note: asStringOrNull(json['note']),
        firstSeenAt: DateTime.tryParse(asString(json['first_seen_at'])),
        lastEvaluatedAt: DateTime.tryParse(asString(json['last_evaluated_at'])),
        updatedAt: DateTime.tryParse(asString(json['updated_at'])),
      );
}

/// Config ativa do loop de aprendizado hv_dip.
class HvDipConfig {
  const HvDipConfig({
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

  factory HvDipConfig.fromJson(Map<String, dynamic> json) => HvDipConfig(
        version: asInt(json['version']),
        isActive: asBool(json['is_active']),
        params: asMap(json['params']),
        origin: asString(json['origin']),
        validation: asMap(json['validation']),
        activatedAt: DateTime.tryParse(asString(json['activated_at'])),
        createdAt: DateTime.tryParse(asString(json['created_at'])),
      );
}

/// Entrada do histórico append-only de configuração hv_dip.
class HvDipConfigHistory {
  const HvDipConfigHistory({
    required this.version,
    required this.params,
    required this.origin,
    required this.reason,
    this.validation = const {},
    this.createdAt,
  });

  final int version;
  final Map<String, dynamic> params;
  final String origin;
  final String reason;
  final Map<String, dynamic> validation;
  final DateTime? createdAt;

  factory HvDipConfigHistory.fromJson(Map<String, dynamic> json) =>
      HvDipConfigHistory(
        version: asInt(json['version']),
        params: asMap(json['params']),
        origin: asString(json['origin']),
        reason: asString(json['reason']),
        validation: asMap(json['validation']),
        createdAt: DateTime.tryParse(asString(json['created_at'])),
      );
}
