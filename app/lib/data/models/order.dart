import 'json.dart';

/// Ordem de corretora originada de uma sugestão aprovada.
class Order {
  const Order({
    required this.id,
    required this.accountId,
    required this.ticker,
    required this.side,
    required this.quantity,
    required this.amountBrl,
    required this.limitPrice,
    required this.status,
    required this.broker,
    required this.executionMode,
    required this.createdAt,
    this.suggestionId,
    this.strategyKind = 'income',
    this.brokerOrderId,
    this.filledPrice,
    this.filledAt,
    this.errorMessage,
    this.executionPayload = const {},
    this.actedByUserId,
  });

  final String id;
  final String accountId;
  final String? suggestionId;
  final String ticker;
  final String strategyKind;
  final String side;
  final double quantity;
  final double amountBrl;
  final double limitPrice;
  final String status;
  final String broker;
  final String executionMode;
  final String? brokerOrderId;
  final double? filledPrice;
  final DateTime? filledAt;
  final String? errorMessage;
  final Map<String, dynamic> executionPayload;
  final String? actedByUserId;
  final DateTime createdAt;

  factory Order.fromJson(Map<String, dynamic> json) => Order(
        id: asString(json['id']),
        accountId: asString(json['account_id']),
        suggestionId: asStringOrNull(json['suggestion_id']),
        ticker: asString(json['ticker']),
        strategyKind: asString(json['strategy_kind'], 'income'),
        side: asString(json['side']),
        quantity: asDouble(json['quantity']),
        amountBrl: asDouble(json['amount_brl']),
        limitPrice: asDouble(json['limit_price']),
        status: asString(json['status']),
        broker: asString(json['broker']),
        executionMode: asString(json['execution_mode']),
        brokerOrderId: asStringOrNull(json['broker_order_id']),
        filledPrice: asDoubleOrNull(json['filled_price']),
        filledAt: DateTime.tryParse(asString(json['filled_at'])),
        errorMessage: asStringOrNull(json['error_message']),
        executionPayload: asMap(json['execution_payload']),
        actedByUserId: asStringOrNull(json['acted_by_user_id']),
        createdAt:
            DateTime.tryParse(asString(json['created_at'])) ?? DateTime.now(),
      );
}
