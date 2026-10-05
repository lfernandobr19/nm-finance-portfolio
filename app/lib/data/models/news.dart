import 'json.dart';

/// Notícia (feed simples, não classificada por LLM).
class NewsItem {
  const NewsItem({
    required this.id,
    required this.title,
    required this.url,
    this.ticker,
    this.source = '',
    this.publishedAt,
  });

  final String id;
  final String? ticker;
  final String title;
  final String url;
  final String source;
  final DateTime? publishedAt;

  factory NewsItem.fromJson(Map<String, dynamic> json) => NewsItem(
        id: asString(json['id']),
        ticker: asStringOrNull(json['ticker']),
        title: asString(json['title']),
        url: asString(json['url']),
        source: asString(json['source']),
        publishedAt: DateTime.tryParse(asString(json['published_at'])),
      );
}
