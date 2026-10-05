import 'format.dart';
import 'suggestion_poller.dart';

/// Build [NewSuggestionEvent] from API suggestion JSON + account context.
NewSuggestionEvent newSuggestionEventFromApi({
  required Map<String, dynamic> sm,
  required String accountId,
  required bool isUsd,
}) {
  final metrics = Map<String, dynamic>.from(sm['metrics'] as Map? ?? {});

  double? pick(String topKey, String metricKey) =>
      asNum(sm[topKey]) ?? asNum(metrics[metricKey]);

  CatalystInfo? parseCatalyst() {
    final raw = metrics['catalyst'];
    if (raw is! Map) return null;
    final c = Map<String, dynamic>.from(raw);
    return CatalystInfo(
      eventType: c['event_type'] as String?,
      sentiment: c['sentiment'] as String?,
      confidence: asNum(c['confidence']),
      impactScore: asNum(c['impact_score']),
      title: c['title'] as String?,
    );
  }

  return NewSuggestionEvent(
    id: sm['id'] as String,
    accountId: accountId,
    ticker: (sm['ticker'] as String?) ?? '?',
    strategyKind: (sm['strategy_kind'] as String?) ?? 'income',
    letter: sm['swing_score_letter'] as String?,
    reviewRequired: sm['review_required'] == true,
    isUsd: isUsd,
    entry: pick('entry_price', 'entry') ?? asNum(metrics['price']),
    stop: pick('stop_price', 'stop'),
    target: pick('target_price', 'target'),
    proposedAmount: asNum(sm['proposed_amount_brl']),
    assetName: metrics['name'] as String?,
    grossYield: asNum(metrics['gross_yield']),
    effectiveYield: asNum(metrics['effective_yield']),
    pVp: asNum(metrics['p_vp']),
    dipLive: asNum(metrics['dip_pct_live']),
    status: sm['status'] as String?,
    catalyst: parseCatalyst(),
  );
}
