/// Nightly intelligence snapshot (read-only). Mirrors GET /intelligence/pulse.
class IntelligencePulse {
  const IntelligencePulse({
    required this.available,
    this.ts,
    this.llmDefault,
    this.lastSource,
    this.newsJsonOk,
    this.nClosedUsd = 0,
    this.learn = const {},
    this.reviewsN = 0,
    this.calibration = const {},
    this.hvDipAutoBuyEnabled = false,
    this.recentReviews = const [],
    this.swingH1,
    this.swingH1Ts,
    this.ollama,
    this.ollamaExpiresAt,
    this.groqCooldown = false,
    this.lastLlmSource,
    this.studies,
    this.assertiveness = const {},
    this.research = const {},
    this.memory = const {},
    this.livePromotion = const {},
    this.deskSlices = const {},
    this.hvDipLiveAutoBuy = false,
    this.platt = const {},
    this.dtGates = const {},
  });

  final bool available;
  final String? ts;
  final String? llmDefault;
  final String? lastSource;
  final int? newsJsonOk;
  final int nClosedUsd;
  final Map<String, LearnStatus> learn;
  final int reviewsN;
  final Map<String, dynamic> calibration;
  final bool hvDipAutoBuyEnabled;
  final List<LlmReview> recentReviews;
  final Map<String, int>? swingH1;
  final String? swingH1Ts;
  final String? ollama;
  final String? ollamaExpiresAt;
  final bool groqCooldown;
  final String? lastLlmSource;
  final StudiesSnapshot? studies;
  final Map<String, dynamic> assertiveness;
  final Map<String, dynamic> research;
  final Map<String, dynamic> memory;
  final Map<String, dynamic> livePromotion;
  final Map<String, dynamic> deskSlices;
  final bool hvDipLiveAutoBuy;
  final Map<String, dynamic> platt;
  final Map<String, dynamic> dtGates;

  factory IntelligencePulse.unavailable() =>
      const IntelligencePulse(available: false);

  factory IntelligencePulse.fromJson(Map<String, dynamic> json) {
    final learnRaw = json['learn'];
    final learn = <String, LearnStatus>{};
    if (learnRaw is Map) {
      learnRaw.forEach((k, v) {
        if (v is Map) {
          learn[k.toString()] = LearnStatus.fromJson(
            v.map((key, val) => MapEntry(key.toString(), val)),
          );
        }
      });
    }
    final cal = json['calibration'];
    final reviews = json['recent_reviews'];
    final h1Raw = json['swing_h1'];
    Map<String, int>? swingH1;
    String? swingH1Ts;
    if (h1Raw is Map) {
      swingH1 = {
        'h1_ok': (h1Raw['h1_ok'] as num?)?.toInt() ?? 0,
        'h1_skip': (h1Raw['h1_skip'] as num?)?.toInt() ?? 0,
        'h1_fail': (h1Raw['h1_fail'] as num?)?.toInt() ?? 0,
      };
      swingH1Ts = h1Raw['ts'] as String?;
    }
    return IntelligencePulse(
      available: json['available'] != false,
      ts: json['ts'] as String?,
      llmDefault: json['llm_default'] as String?,
      lastSource: json['last_source'] as String?,
      newsJsonOk: (json['news_json_ok'] as num?)?.toInt(),
      nClosedUsd: (json['n_closed_usd'] as num?)?.toInt() ?? 0,
      learn: learn,
      reviewsN: (json['reviews_n'] as num?)?.toInt() ?? 0,
      calibration: cal is Map
          ? cal.map((k, v) => MapEntry(k.toString(), v))
          : const {},
      hvDipAutoBuyEnabled: json['hv_dip_auto_buy_enabled'] == true,
      recentReviews: reviews is List
          ? reviews
              .whereType<Map>()
              .map((e) => LlmReview.fromJson(
                    e.map((k, v) => MapEntry(k.toString(), v)),
                  ))
              .toList()
          : const [],
      swingH1: swingH1,
      swingH1Ts: swingH1Ts,
      ollama: json['ollama'] as String?,
      ollamaExpiresAt: json['ollama_expires_at'] as String?,
      groqCooldown: json['groq_cooldown'] == true,
      lastLlmSource: json['last_llm_source'] as String?,
      studies: json['studies'] is Map
          ? StudiesSnapshot.fromJson(
              (json['studies'] as Map).map((k, v) => MapEntry(k.toString(), v)))
          : null,
      assertiveness: json['assertiveness'] is Map
          ? (json['assertiveness'] as Map)
              .map((k, v) => MapEntry(k.toString(), v))
          : const {},
      research: json['research'] is Map
          ? (json['research'] as Map).map((k, v) => MapEntry(k.toString(), v))
          : const {},
      memory: json['memory'] is Map
          ? (json['memory'] as Map).map((k, v) => MapEntry(k.toString(), v))
          : const {},
      livePromotion: json['live_promotion'] is Map
          ? (json['live_promotion'] as Map)
              .map((k, v) => MapEntry(k.toString(), v))
          : const {},
      deskSlices: json['desk_slices'] is Map
          ? (json['desk_slices'] as Map).map((k, v) => MapEntry(k.toString(), v))
          : const {},
      hvDipLiveAutoBuy: json['hv_dip_live_auto_buy'] == true,
      platt: json['platt'] is Map
          ? (json['platt'] as Map).map((k, v) => MapEntry(k.toString(), v))
          : const {},
      dtGates: json['dt_gates'] is Map
          ? (json['dt_gates'] as Map).map((k, v) => MapEntry(k.toString(), v))
          : const {},
    );
  }
}

class LearnStatus {
  const LearnStatus({required this.status, this.n});

  final String status;
  final int? n;

  factory LearnStatus.fromJson(Map<String, dynamic> json) => LearnStatus(
        status: (json['status'] as String?) ?? 'unknown',
        n: (json['n'] as num?)?.toInt(),
      );
}

class LlmReview {
  const LlmReview({
    required this.ticker,
    this.lesson = '',
    this.wouldChange = '',
    this.confidence,
    this.source,
  });

  final String ticker;
  final String lesson;
  final String wouldChange;
  final double? confidence;
  final String? source;

  factory LlmReview.fromJson(Map<String, dynamic> json) => LlmReview(
        ticker: (json['ticker'] as String?) ?? '',
        lesson: (json['lesson'] as String?) ?? '',
        wouldChange: (json['would_change'] as String?) ?? '',
        confidence: (json['confidence'] as num?)?.toDouble(),
        source: json['source'] as String?,
      );
}

/// Active learn studies snapshot (read-only, mirrors GET /intelligence/pulse).
class StudiesSnapshot {
  const StudiesSnapshot({
    this.ts,
    this.queries = const [],
    this.results = const [],
    this.guards = const {},
    this.decisions = const [],
    this.insights = const [],
  });

  final String? ts;
  final List<StudyQuery> queries;
  final List<StudyResult> results;
  final Map<String, dynamic> guards;
  final List<Map<String, dynamic>> decisions;
  final List<Insight> insights;

  factory StudiesSnapshot.fromJson(Map<String, dynamic> json) {
    final queries = json['queries'];
    final results = json['results'];
    final decisions = json['decisions'];
    final insights = json['insights'];
    return StudiesSnapshot(
      ts: json['ts'] as String?,
      queries: queries is List
          ? queries
              .whereType<Map>()
              .map((e) => StudyQuery.fromJson(
                    e.map((k, v) => MapEntry(k.toString(), v)),
                  ))
              .toList()
          : const [],
      results: results is List
          ? results
              .whereType<Map>()
              .map((e) => StudyResult.fromJson(
                    e.map((k, v) => MapEntry(k.toString(), v)),
                  ))
              .toList()
          : const [],
      guards: json['guards'] is Map
          ? (json['guards'] as Map).map((k, v) => MapEntry(k.toString(), v))
          : const {},
      decisions: decisions is List
          ? decisions
              .whereType<Map>()
              .map((e) => e.map((k, v) => MapEntry(k.toString(), v)))
              .toList()
          : const [],
      insights: insights is List
          ? insights
              .whereType<Map>()
              .map((e) => Insight.fromJson(
                    e.map((k, v) => MapEntry(k.toString(), v)),
                  ))
              .toList()
          : const [],
    );
  }
}

class StudyQuery {
  const StudyQuery({
    required this.id,
    required this.label,
    required this.channel,
    required this.fingerprint,
    this.horizon = 10,
    this.metric = 'p_higher',
    this.targetR = 2.0,
    this.stopPct,
    this.params = const {},
  });

  final String id;
  final String label;
  final String channel;
  final String fingerprint;
  final int horizon;
  final String metric;
  final double targetR;
  final double? stopPct;
  final Map<String, double> params;

  factory StudyQuery.fromJson(Map<String, dynamic> json) => StudyQuery(
        id: (json['id'] as String?) ?? '',
        label: (json['label'] as String?) ?? '',
        channel: (json['channel'] as String?) ?? '',
        fingerprint: (json['fingerprint'] as String?) ?? '',
        horizon: (json['horizon'] as num?)?.toInt() ?? 10,
        metric: (json['metric'] as String?) ?? 'p_higher',
        targetR: (json['target_r'] as num?)?.toDouble() ?? 2.0,
        stopPct: (json['stop_pct'] as num?)?.toDouble(),
        params: json['params'] is Map
            ? (json['params'] as Map).map((k, v) => MapEntry(
                  k.toString(),
                  (v as num).toDouble(),
                ))
            : const {},
      );
}

class StudyResult {
  const StudyResult({
    required this.queryId,
    this.label = '',
    this.channel = 'hv_dip',
    this.fingerprint = '',
    this.ticker = 'UNIVERSE',
    this.n = 0,
    this.pHigher,
    this.pStopFirst,
    this.expectancyR,
    this.trendUp,
    this.vsUniverse,
    this.pRecover,
    this.oosN = 0,
    this.oosPHigher,
    this.oosPRecover,
    this.applied = false,
    this.note,
  });

  final String queryId;
  final String label;
  final String channel;
  final String fingerprint;
  final String ticker;
  final int n;
  final double? pHigher;
  final double? pStopFirst;
  final double? expectancyR;
  final double? trendUp;
  final double? vsUniverse;
  final double? pRecover;
  final int oosN;
  final double? oosPHigher;
  final double? oosPRecover;
  final bool applied;
  final String? note;

  factory StudyResult.fromJson(Map<String, dynamic> json) => StudyResult(
        queryId: (json['query_id'] as String?) ?? '',
        label: (json['label'] as String?) ?? '',
        channel: (json['channel'] as String?) ?? 'hv_dip',
        fingerprint: (json['fingerprint'] as String?) ?? '',
        ticker: (json['ticker'] as String?) ?? 'UNIVERSE',
        n: (json['n'] as num?)?.toInt() ?? 0,
        pHigher: (json['p_higher'] as num?)?.toDouble(),
        pStopFirst: (json['p_stop_first'] as num?)?.toDouble(),
        expectancyR: (json['expectancy_r'] as num?)?.toDouble(),
        trendUp: (json['trend_up'] as num?)?.toDouble(),
        vsUniverse: (json['vs_universe'] as num?)?.toDouble(),
        pRecover: (json['p_recover'] as num?)?.toDouble(),
        oosN: (json['oos_n'] as num?)?.toInt() ?? 0,
        oosPHigher: (json['oos_p_higher'] as num?)?.toDouble(),
        oosPRecover: (json['oos_p_recover'] as num?)?.toDouble(),
        applied: json['applied'] == true,
        note: json['note'] as String?,
      );
}

/// A qualitative, grounded insight the LLM wrote from a numeric digest.
class Insight {
  const Insight({
    this.ticker = 'UNIVERSE',
    this.kind = 'universe',
    this.text = '',
    this.evidence = const [],
    this.confidence = 0.0,
    this.channel = 'hv_dip',
  });

  final String ticker;
  final String kind;
  final String text;
  final List<InsightEvidence> evidence;
  final double confidence;
  final String channel;

  factory Insight.fromJson(Map<String, dynamic> json) {
    final evidence = json['evidence'];
    return Insight(
      ticker: (json['ticker'] as String?) ?? 'UNIVERSE',
      kind: (json['kind'] as String?) ?? 'universe',
      text: (json['text'] as String?) ?? '',
      evidence: evidence is List
          ? evidence
              .whereType<Map>()
              .map((e) => InsightEvidence.fromJson(
                    e.map((k, v) => MapEntry(k.toString(), v)),
                  ))
              .toList()
          : const [],
      confidence: (json['confidence'] as num?)?.toDouble() ?? 0.0,
      channel: (json['channel'] as String?) ?? 'hv_dip',
    );
  }
}

class InsightEvidence {
  const InsightEvidence({this.fact = '', this.value = ''});

  final String fact;
  final String value;

  factory InsightEvidence.fromJson(Map<String, dynamic> json) => InsightEvidence(
        fact: (json['fact'] as String?) ?? '',
        value: (json['value'] as String?) ?? '',
      );
}
