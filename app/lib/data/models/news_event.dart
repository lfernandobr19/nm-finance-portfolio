import 'json.dart';

/// Catalisador de notícia classificado pelo LLM.
class NewsEvent {
  const NewsEvent({
    required this.id,
    required this.title,
    required this.url,
    this.ticker,
    this.source = '',
    this.eventType,
    this.sentiment,
    this.confidence,
    this.impactScore,
    this.catalystStrength,
    this.publishedAt,
    this.processedAt,
    this.usedInSuggestion = false,
  });

  final String id;
  final String title;
  final String url;
  final String? ticker;
  final String source;
  final String? eventType;
  final String? sentiment;
  final double? confidence;
  final double? impactScore;
  final String? catalystStrength;
  final DateTime? publishedAt;
  final DateTime? processedAt;
  final bool usedInSuggestion;

  factory NewsEvent.fromJson(Map<String, dynamic> json) => NewsEvent(
        id: asString(json['id']),
        title: asString(json['title']),
        url: asString(json['url']),
        ticker: asStringOrNull(json['ticker']),
        source: asString(json['source']),
        eventType: asStringOrNull(json['event_type']),
        sentiment: asStringOrNull(json['sentiment']),
        confidence: asDoubleOrNull(json['confidence']),
        impactScore: asDoubleOrNull(json['impact_score']),
        catalystStrength: asStringOrNull(json['catalyst_strength']),
        publishedAt: DateTime.tryParse(asString(json['published_at'])),
        processedAt: DateTime.tryParse(asString(json['processed_at'])),
        usedInSuggestion: asBool(json['used_in_suggestion']),
      );
}
