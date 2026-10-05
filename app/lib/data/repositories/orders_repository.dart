import '../../core/api_client.dart';
import '../models/order.dart';

/// Typed access to broker orders.
class OrdersRepository {
  OrdersRepository(this._api);

  final ApiClient _api;

  Future<List<Order>> list(String accountId) async {
    final raw = await _api.getList('/accounts/$accountId/orders');
    return raw
        .whereType<Map>()
        .map((e) => Order.fromJson(e.map((k, v) => MapEntry(k.toString(), v))))
        .toList();
  }

  Future<Order> markFilled(
    String accountId,
    String orderId, {
    double? filledPrice,
    String? note,
  }) async {
    final raw = await _api.post(
      '/accounts/$accountId/orders/$orderId/mark-filled',
      {
        if (filledPrice != null) 'filled_price': filledPrice,
        if (note != null) 'note': note,
      },
    );
    return Order.fromJson(raw);
  }

  Future<Order> markCancelled(String accountId, String orderId) async {
    final raw = await _api
        .post('/accounts/$accountId/orders/$orderId/mark-cancelled', const {});
    return Order.fromJson(raw);
  }
}
