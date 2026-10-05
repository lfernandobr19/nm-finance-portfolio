import '../../core/api_client.dart';
import '../models/account.dart';

/// Typed access to investment accounts.
class AccountsRepository {
  AccountsRepository(this._api);

  final ApiClient _api;

  Future<List<Account>> list() async {
    final raw = await _api.getList('/accounts');
    return raw
        .whereType<Map>()
        .map(
            (e) => Account.fromJson(e.map((k, v) => MapEntry(k.toString(), v))))
        .toList();
  }

  Future<Account> get(String accountId) async {
    final raw = await _api.getMap('/accounts/$accountId');
    return Account.fromJson(raw);
  }

  Future<Account> setAutomationPaused(String accountId, bool paused) async {
    final raw = await _api.patch('/accounts/$accountId', {'automation_paused': paused});
    return Account.fromJson(raw);
  }

  Future<Account> rename(String accountId, String name) async {
    final raw = await _api.patch('/accounts/$accountId', {'name': name});
    return Account.fromJson(raw);
  }

  Future<void> delete(String accountId) async {
    await _api.delete('/accounts/$accountId');
  }
}
