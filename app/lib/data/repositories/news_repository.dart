import '../../core/api_client.dart';
import '../models/news.dart';

/// Typed access to the raw news feed.
class NewsRepository {
  NewsRepository(this._api);

  final ApiClient _api;

  Future<List<NewsItem>> list(String accountId) async {
    final raw = await _api.getList('/accounts/$accountId/news');
    return raw
        .whereType<Map>()
        .map((e) =>
            NewsItem.fromJson(e.map((k, v) => MapEntry(k.toString(), v))))
        .toList();
  }
}
