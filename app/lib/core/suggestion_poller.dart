/// Poll pending suggestions for in-app and system notifications.
library;

import 'dart:async';
import 'dart:convert';

import 'package:shared_preferences/shared_preferences.dart';

import 'api_client.dart';
import 'market_prefs.dart';
import 'suggestion_event_factory.dart';

/// Structured news-catalyst metadata attached to a suggestion.
class CatalystInfo {
  const CatalystInfo({
    this.eventType,
    this.sentiment,
    this.confidence,
    this.impactScore,
    this.title,
  });

  final String? eventType;
  final String? sentiment;
  final double? confidence;
  final double? impactScore;
  final String? title;
}

class NewSuggestionEvent {
  NewSuggestionEvent({
    required this.id,
    required this.accountId,
    required this.ticker,
    required this.strategyKind,
    this.letter,
    this.reviewRequired = false,
    required this.isUsd,
    this.entry,
    this.stop,
    this.target,
    this.proposedAmount,
    this.assetName,
    this.grossYield,
    this.effectiveYield,
    this.pVp,
    this.dipLive,
    this.status,
    this.catalyst,
  });

  final String id;
  final String accountId;
  final String ticker;
  final String strategyKind;
  final String? letter;
  final bool reviewRequired;
  final bool isUsd;
  final double? entry;
  final double? stop;
  final double? target;
  final double? proposedAmount;
  final String? assetName;
  final double? grossYield;
  final double? effectiveYield;
  final double? pVp;
  final double? dipLive;
  final String? status;
  final CatalystInfo? catalyst;

  bool get isAuto => status == 'auto_approved';

  String get currency => isUsd ? 'USD' : 'BRL';

  /// Payload for notification actions: accountId|suggestionId|review|0or1
  String toPayload() =>
      '$accountId|$id|${reviewRequired ? 1 : 0}';
}

class SuggestionPoller {
  SuggestionPoller(this.api, {this.interval = const Duration(seconds: 45)});

  final ApiClient api;
  final Duration interval;
  Timer? _timer;
  void Function(int pendingCount)? onPendingChanged;
  void Function(List<NewSuggestionEvent> newOnes)? onNewSuggestions;

  static const _idsKey = 'pending_suggestion_ids';

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

  Future<void> _tick() async {
    if (api.accessToken == null) return;
    try {
      final market = await MarketPrefs.load();
      final accounts = await api.getList('/accounts');
      final prefs = await SharedPreferences.getInstance();
      final knownRaw = prefs.getString(_idsKey);
      final known = <String>{
        if (knownRaw != null) ...List<String>.from(jsonDecode(knownRaw) as List),
      };

      var total = 0;
      final currentIds = <String>{};
      final newOnes = <NewSuggestionEvent>[];

      for (final raw in accounts) {
        final map = Map<String, dynamic>.from(raw as Map);
        final id = map['id'] as String?;
        if (id == null) continue;
        final isUsd = _isUsdAccount(map);
        if (market == 'us' && !isUsd) continue;
        if (market == 'br' && isUsd) continue;

        final list = await api.getList(
          '/accounts/$id/suggestions',
          {'status': 'pending'},
        );
        total += list.length;
        for (final s in list) {
          final sm = Map<String, dynamic>.from(s as Map);
          final sid = sm['id'] as String?;
          if (sid == null) continue;
          currentIds.add(sid);
          if (!known.contains(sid)) {
            newOnes.add(
              newSuggestionEventFromApi(
                sm: sm,
                accountId: id,
                isUsd: isUsd,
              ),
            );
          }
        }
      }

      if (newOnes.isNotEmpty) {
        onNewSuggestions?.call(newOnes);
      }
      onPendingChanged?.call(total);
      await prefs.setString(_idsKey, jsonEncode(currentIds.toList()));
    } catch (_) {
      // ignore transient network errors
    }
  }
}
