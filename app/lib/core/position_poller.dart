/// Poll open positions for exit alerts (Exit Engine V2 + legacy).
library;

import 'dart:async';
import 'dart:convert';

import 'package:shared_preferences/shared_preferences.dart';

import 'api_client.dart';
import 'format.dart';
import 'market_prefs.dart';

class ExitAlertEvent {
  ExitAlertEvent({
    required this.positionId,
    required this.accountId,
    required this.suggestionId,
    required this.ticker,
    required this.alert,
    required this.markPrice,
    this.unrealizedPct,
    this.newSuggestionId,
  });

  final String positionId;
  final String accountId;
  final String suggestionId;
  final String ticker;
  final String alert;
  final double markPrice;
  final double? unrealizedPct;
  /// For rotation alerts — the pending suggestion to swap in.
  final String? newSuggestionId;

  String dedupKey() => '$positionId:$alert${newSuggestionId ?? ""}';

  String toPayload() =>
      '$accountId|$suggestionId|$positionId|$alert|${newSuggestionId ?? ""}';
}

class PositionPoller {
  PositionPoller(this.api, {this.interval = const Duration(seconds: 60)});

  final ApiClient api;
  final Duration interval;
  Timer? _timer;
  void Function(List<ExitAlertEvent> alerts)? onExitAlerts;

  static const _keysKey = 'position_alert_keys';

  void start() {
    _timer?.cancel();
    _timer = Timer.periodic(interval, (_) => _tick());
    _tick();
  }

  void stop() {
    _timer?.cancel();
    _timer = null;
  }

  static bool _isUsdAccount(Map<String, dynamic> map) {
    final ccy = (map['currency'] as String?)?.toUpperCase() ?? 'BRL';
    final broker = (map['broker_code'] as String?)?.toLowerCase() ?? '';
    return ccy == 'USD' || broker == 'alpaca';
  }

  static String alertTitle(String alert, String ticker) {
    switch (alert) {
      case 'stop':
        return 'STOP $ticker';
      case 'target':
        return 'ALVO $ticker';
      case 'recovery':
        return 'RECUP $ticker';
      case 'trailing':
        return 'TRAIL $ticker';
      case 'latched':
        return 'OBS $ticker';
      case 'protect':
        return 'PROT $ticker';
      case 'time_review':
        return 'D14 $ticker';
      case 'rotation':
        return 'Rotação? $ticker';
      default:
        return '$ticker · $alert';
    }
  }

  static String alertBody(ExitAlertEvent e) {
    final px = formatUsd(e.markPrice);
    final pct = e.unrealizedPct;
    switch (e.alert) {
      case 'stop':
        return 'Cotação $px ≤ stop — toque para ver posição';
      case 'target':
        return 'Cotação $px ≥ alvo — considere realização';
      case 'recovery':
        return 'Cotação $px ≥ topo do dip';
      case 'trailing':
        return pct != null
            ? 'Lucro ${formatPct(pct)} caiu do pico — proteja ganho'
            : 'Lucro caiu do pico — proteja ganho';
      case 'latched':
        return pct != null
            ? 'Observação +5% · lucro ${formatPct(pct)} · $px'
            : 'Entrou em observação (+5%) · $px';
      case 'protect':
        return 'Proteção acionada — saída em $px';
      case 'time_review':
        return pct != null
            ? 'Dia 14 — avalie saída · PnL ${formatPct(pct)} · $px'
            : 'Dia 14 — avalie saída · $px';
      case 'rotation':
        return 'Setup melhor disponível — toque para comparar';
      default:
        return 'Alerta $px';
    }
  }

  Future<void> _tick() async {
    if (api.accessToken == null) return;
    try {
      final market = await MarketPrefs.load();
      final accounts = await api.getList('/accounts');
      final prefs = await SharedPreferences.getInstance();
      final knownRaw = prefs.getString(_keysKey);
      final known = <String>{
        if (knownRaw != null) ...List<String>.from(jsonDecode(knownRaw) as List),
      };

      final currentKeys = <String>{};
      final newAlerts = <ExitAlertEvent>[];

      for (final raw in accounts) {
        final map = Map<String, dynamic>.from(raw as Map);
        final id = map['id'] as String?;
        if (id == null) continue;
        final isUsd = _isUsdAccount(map);
        if (market == 'us' && !isUsd) continue;
        if (market == 'br' && isUsd) continue;

        final list = await api.getList(
          '/accounts/$id/positions',
          {'status': 'open'},
        );
        for (final p in list) {
          final pm = Map<String, dynamic>.from(p as Map);
          final alert = pm['price_alert'] as String?;
          if (alert == null || alert.isEmpty) continue;
          final posId = pm['id'] as String?;
          final sugId = pm['suggestion_id'] as String?;
          if (posId == null || sugId == null) continue;
          final key = '$posId:$alert';
          currentKeys.add(key);
          if (!known.contains(key)) {
            newAlerts.add(
              ExitAlertEvent(
                positionId: posId,
                accountId: id,
                suggestionId: sugId,
                ticker: pm['ticker'] as String? ?? '?',
                alert: alert,
                markPrice: (pm['mark_price'] as num?)?.toDouble() ?? 0,
                unrealizedPct: (pm['unrealized_pnl_pct'] as num?)?.toDouble(),
              ),
            );
          }
        }
      }

      if (newAlerts.isNotEmpty) {
        onExitAlerts?.call(newAlerts);
      }
      await prefs.setString(_keysKey, jsonEncode(currentKeys.toList()));
    } catch (_) {
      // ignore transient network errors
    }
  }
}
