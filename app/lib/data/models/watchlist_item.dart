import 'json.dart';

/// Item da watchlist de observação (enriquecido com cotação ao vivo).
class WatchlistItem {
  const WatchlistItem({
    required this.id,
    required this.accountId,
    required this.ticker,
    this.note,
    this.createdAt,
    this.price,
    this.prevClose,
    this.changePct,
    this.currency = 'BRL',
  });

  final String id;
  final String accountId;
  final String ticker;
  final String? note;
  final DateTime? createdAt;
  final double? price;
  final double? prevClose;
  final double? changePct;
  final String currency;

  factory WatchlistItem.fromJson(Map<String, dynamic> json) => WatchlistItem(
        id: asString(json['id']),
        accountId: asString(json['account_id']),
        ticker: asString(json['ticker']),
        note: asStringOrNull(json['note']),
        createdAt: DateTime.tryParse(asString(json['created_at'])),
        price: asDoubleOrNull(json['price']),
        prevClose: asDoubleOrNull(json['prev_close']),
        changePct: asDoubleOrNull(json['change_pct']),
        currency: asString(json['currency'], 'BRL'),
      );
}
