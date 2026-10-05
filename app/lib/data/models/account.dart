import 'json.dart';

/// Conta de investimento (compartilhada, com papel do usuário).
class Account {
  const Account({
    required this.id,
    required this.name,
    required this.ownerUserId,
    required this.targetCapital,
    required this.currency,
    this.autoApproveEnabled = false,
    this.autoApproveMinScore = 0,
    this.dailyAutoApproveLimit = 0,
    this.maxTicketBrl = 0,
    this.brokerCode = 'inter',
    this.executionMode = 'paper',
    this.cashBrl = 0,
    this.cashUsd = 0,
    this.automationPaused = false,
    this.myRole,
    this.createdAt,
  });

  final String id;
  final String name;
  final String ownerUserId;
  final double targetCapital;
  final bool autoApproveEnabled;
  final double autoApproveMinScore;
  final int dailyAutoApproveLimit;
  final double maxTicketBrl;
  final String brokerCode;
  final String executionMode;
  final double cashBrl;
  final double cashUsd;
  final bool automationPaused;
  final String currency;
  final String? myRole;
  final DateTime? createdAt;

  factory Account.fromJson(Map<String, dynamic> json) => Account(
        id: asString(json['id']),
        name: asString(json['name']),
        ownerUserId: asString(json['owner_user_id']),
        targetCapital: asDouble(json['target_capital']),
        autoApproveEnabled: asBool(json['auto_approve_enabled']),
        autoApproveMinScore: asDouble(json['auto_approve_min_score']),
        dailyAutoApproveLimit: asInt(json['daily_auto_approve_limit']),
        maxTicketBrl: asDouble(json['max_ticket_brl']),
        brokerCode: asString(json['broker_code'], 'inter'),
        executionMode: asString(json['execution_mode'], 'paper'),
        cashBrl: asDouble(json['cash_brl']),
        cashUsd: asDouble(json['cash_usd']),
        automationPaused: asBool(json['automation_paused']),
        currency: asString(json['currency'], 'BRL'),
        myRole: _parseRole(json['my_role']),
        createdAt: DateTime.tryParse(asString(json['created_at'])),
      );
}

/// `my_role` chega como objeto (`{"value": "owner"}`) ou string simples.
String? _parseRole(Object? value) {
  if (value == null) return null;
  if (value is Map) return asStringOrNull(value['value']) ?? asStringOrNull(value);
  return asStringOrNull(value);
}
