import '../../core/api_client.dart';
import '../models/watchlist_item.dart';

/// Typed access to the watchlist (observação) endpoints.
class WatchlistRepository {
  WatchlistRepository(this._api);

  final ApiClient _api;

  Future<List<WatchlistItem>> list(String accountId) async {
    final raw = await _api.getList('/accounts/$accountId/watchlist');
    return raw
        .whereType<Map>()
        .map((e) =>
            WatchlistItem.fromJson(e.map((k, v) => MapEntry(k.toString(), v))))
        .toList();
  }

  Future<WatchlistItem> add(
    String accountId,
    String ticker, {
    String? note,
  }) async {
    final raw = await _api.post(
      '/accounts/$accountId/watchlist',
      {'ticker': ticker, if (note != null) 'note': note},
    );
    return WatchlistItem.fromJson(raw);
  }

  Future<void> remove(String accountId, String ticker) async {
    await _api.delete('/accounts/$accountId/watchlist/${Uri.encodeComponent(ticker)}');
  }
}
