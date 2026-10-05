import '../../core/api_client.dart';
import '../models/news_event.dart';

/// Typed access to the LLM-classified catalyst feed.
class CatalystsRepository {
  CatalystsRepository(this._api);

  final ApiClient _api;

  Future<List<NewsEvent>> listNewsEvents(
    String accountId, {
    String? ticker,
    String? eventType,
    String? sentiment,
  }) async {
    final query = <String, String>{
      if (ticker != null) 'ticker': ticker,
      if (eventType != null) 'event_type': eventType,
      if (sentiment != null) 'sentiment': sentiment,
    };
    final raw = await _api.getList('/accounts/$accountId/news-events', query);
    return raw
        .whereType<Map>()
        .map((e) =>
            NewsEvent.fromJson(e.map((k, v) => MapEntry(k.toString(), v))))
        .toList();
  }
}
