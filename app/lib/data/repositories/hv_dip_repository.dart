import '../../core/api_client.dart';
import '../models/hv_dip.dart';

/// Typed access to the hv_dip learning loop (observation radar + config).
class HvDipRepository {
  HvDipRepository(this._api);

  final ApiClient _api;

  Future<List<Observation>> listObservations(String accountId) async {
    final raw = await _api.getList('/accounts/$accountId/hv-dip/observations');
    return raw
        .whereType<Map>()
        .map((e) =>
            Observation.fromJson(e.map((k, v) => MapEntry(k.toString(), v))))
        .toList();
  }

  Future<HvDipConfig> getConfig(String accountId) async {
    final raw = await _api.getMap('/accounts/$accountId/hv-dip/config');
    return HvDipConfig.fromJson(raw);
  }

  Future<List<HvDipConfigHistory>> getConfigHistory(String accountId) async {
    final raw =
        await _api.getList('/accounts/$accountId/hv-dip/config/history');
    return raw
        .whereType<Map>()
        .map((e) => HvDipConfigHistory.fromJson(
            e.map((k, v) => MapEntry(k.toString(), v))))
        .toList();
  }

  Future<HvDipConfig> rollbackConfig(String accountId, int version) async {
    final raw = await _api.post(
      '/accounts/$accountId/hv-dip/config/rollback',
      const {},
      query: {'version': '$version'},
    );
    return HvDipConfig.fromJson(raw);
  }
}
