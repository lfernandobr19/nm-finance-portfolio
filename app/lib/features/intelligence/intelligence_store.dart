import 'dart:async';

import 'package:flutter/widgets.dart';
import 'package:provider/provider.dart';

import '../../data/models/intelligence_pulse.dart';
import '../../data/repositories/intelligence_repository.dart';

/// Null when the widget is outside the dashboard (widget tests, mobile).
IntelligenceStore? maybeWatchStore(BuildContext context) {
  try {
    return Provider.of<IntelligenceStore>(context);
  } on ProviderNotFoundException {
    return null;
  }
}

/// Single poller for pulse + evolution lists. Panels listen; they do not GET.
class IntelligenceStore extends ChangeNotifier {
  IntelligenceStore(this._repo);

  final IntelligenceRepository _repo;
  Timer? _timer;

  IntelligencePulse? pulse;
  List<Map<String, dynamic>> evolution = const [];
  List<Map<String, dynamic>> memories = const [];
  Object? error;
  bool loading = false;

  void start() {
    refresh();
    _timer?.cancel();
    _timer = Timer.periodic(const Duration(seconds: 60), (_) => refresh());
  }

  Future<void> refresh() async {
    loading = pulse == null;
    error = null;
    if (loading) notifyListeners();
    try {
      await for (final p in _repo.watchPulse()) {
        pulse = p;
        notifyListeners();
      }
      evolution = await _repo.getEvolution();
      memories = await _repo.getMemory();
      error = null;
    } catch (e) {
      error = e;
    } finally {
      loading = false;
      notifyListeners();
    }
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }
}
