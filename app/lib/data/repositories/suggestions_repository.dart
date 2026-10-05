import '../../core/api_client.dart';
import '../models/suggestion.dart';

/// Typed access to strategy suggestions + approve/reject actions.
class SuggestionsRepository {
  SuggestionsRepository(this._api);

  final ApiClient _api;

  Future<List<Suggestion>> list(
    String accountId, {
    String? status,
    String? strategyKind,
  }) async {
    final query = <String, String>{
      if (status != null) 'status': status,
      if (strategyKind != null) 'strategy_kind': strategyKind,
    };
    final raw = await _api.getList('/accounts/$accountId/suggestions', query);
    return raw
        .whereType<Map>()
        .map((e) =>
            Suggestion.fromJson(e.map((k, v) => MapEntry(k.toString(), v))))
        .toList();
  }

  Future<Suggestion> get(String accountId, String suggestionId) async {
    final raw =
        await _api.getMap('/accounts/$accountId/suggestions/$suggestionId');
    return Suggestion.fromJson(raw);
  }

  Future<Map<String, dynamic>> approve(
    String accountId,
    String suggestionId, {
    String? note,
    double? amountUsd,
  }) async {
    return _api.post(
      '/accounts/$accountId/suggestions/$suggestionId/approve',
      {
        if (note != null) 'note': note,
        if (amountUsd != null) 'amount_usd': amountUsd,
      },
    );
  }

  Future<Map<String, dynamic>> reject(
    String accountId,
    String suggestionId, {
    String? note,
  }) async {
    return _api.post(
      '/accounts/$accountId/suggestions/$suggestionId/reject',
      {if (note != null) 'note': note},
    );
  }
}
