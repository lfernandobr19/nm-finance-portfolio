import '../../core/api_client.dart';
import '../models/intelligence_pulse.dart';

/// Read-only intelligence. Cache-first pulse stream (Context7 offline-first).
class IntelligenceRepository {
  IntelligenceRepository(this._api);

  final ApiClient _api;
  IntelligencePulse? _cache;

  Future<IntelligencePulse> getPulse() async {
    final raw = await _api.getMap('/intelligence/pulse');
    final pulse = IntelligencePulse.fromJson(raw);
    _cache = pulse;
    return pulse;
  }

  Stream<IntelligencePulse> watchPulse() async* {
    if (_cache != null) yield _cache!;
    yield await getPulse();
  }

  Future<List<Map<String, dynamic>>> getEvolution({int limit = 40}) async {
    final raw = await _api.getMap('/intelligence/evolution', {'limit': '$limit'});
    final items = raw['items'];
    if (items is! List) return const [];
    return items
        .whereType<Map>()
        .map((e) => e.map((k, v) => MapEntry(k.toString(), v)))
        .toList();
  }

  Future<List<Map<String, dynamic>>> getMemory({int limit = 40}) async {
    final raw = await _api.getMap('/intelligence/memory', {'limit': '$limit'});
    final items = raw['items'];
    if (items is! List) return const [];
    return items
        .whereType<Map>()
        .map((e) => e.map((k, v) => MapEntry(k.toString(), v)))
        .toList();
  }

  Future<List<Map<String, dynamic>>> getDecisions({int limit = 40}) async {
    final raw = await _api.getMap('/intelligence/decisions', {'limit': '$limit'});
    final items = raw['items'];
    if (items is! List) return const [];
    return items
        .whereType<Map>()
        .map((e) => e.map((k, v) => MapEntry(k.toString(), v)))
        .toList();
  }
}
