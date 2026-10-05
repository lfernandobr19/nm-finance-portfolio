import 'package:flutter/foundation.dart';

import '../data/models/account.dart';

/// Shared "selected account" state across the desktop tabs. The Accounts tab
/// sets it; account-scoped tabs (Mesa, Notícias, Ordens, Day Trade, Inteligência)
/// read it and show an empty-state hint when no account is selected.
class SelectedAccount extends ChangeNotifier {
  Account? _current;

  Account? get current => _current;

  bool get hasAccount => _current != null;

  String get accountId => _current?.id ?? '';

  void select(Account? account) {
    if (identical(_current, account)) return;
    _current = account;
    notifyListeners();
  }
}
