import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../core/api_client.dart';
import '../../core/format.dart';
import '../../core/pnl_line_chart.dart';
import '../../data/models/day_trade.dart';
import '../../data/models/hv_dip.dart';
import '../../data/models/intelligence_pulse.dart';
import '../../data/models/news_event.dart';
import '../../data/models/pnl_series.dart';
import '../../data/models/position.dart';
import '../../data/repositories/catalysts_repository.dart';
import '../../data/repositories/day_trade_repository.dart';
import '../../data/repositories/hv_dip_repository.dart';
import '../../data/repositories/intelligence_repository.dart';
import '../../data/repositories/portfolio_repository.dart';
import 'evolution_panels.dart';
import 'intelligence_store.dart';

/// Shared building blocks for the intelligence panels. Each panel is a
/// self-contained widget that loads its own data from the typed repositories
/// and renders a compact, scrollable body that fits the dashboard tile.

String _assertivenessLine(Map<String, dynamic> raw) {
  final by = raw['by_source'];
  if (by is! Map) return '';
  final parts = <String>[];
  by.forEach((k, v) {
    if (v is Map) {
      parts.add('$k brier ${_fmtValue(v['brier'])} n ${_fmtValue(v['resolved'])}');
    }
  });
  return parts.isEmpty ? '' : 'Ledger: ${parts.join(' · ')}';
}

String _fmtValue(Object? v) {
  if (v == null) return '—';
  if (v is bool) return v ? 'sim' : 'não';
  if (v is num) {
    final n = v.toDouble();
    if (n == n.roundToDouble() && n.abs() < 1e9) return n.round().toString();
    return n.toStringAsFixed(4).replaceFirst(RegExp(r'\.?0+$'), '');
  }
  return v.toString();
}

Color _sentimentColor(String? sentiment) {
  switch (sentiment?.toLowerCase()) {
    case 'positive':
    case 'bullish':
      return Colors.green.shade700;
    case 'negative':
    case 'bearish':
      return Colors.red.shade700;
    case 'neutral':
      return Colors.orange.shade800;
    default:
      return Colors.blueGrey.shade600;
  }
}

Color _regimeColor(String regime) {
  switch (regime.toLowerCase()) {
    case 'trend':
      return Colors.green.shade700;
    case 'chop':
      return Colors.orange.shade800;
    case 'warmup':
      return Colors.blueGrey.shade500;
    default:
      return Colors.blueGrey.shade500;
  }
}

class _Badge extends StatelessWidget {
  const _Badge({required this.label, required this.color});

  final String label;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.14),
        borderRadius: BorderRadius.circular(20),
      ),
      child: Text(
        label,
        style: Theme.of(context).textTheme.labelSmall?.copyWith(
              color: color,
              fontWeight: FontWeight.w700,
            ),
      ),
    );
  }
}

Widget _panelMessage(BuildContext context, String message, {IconData? icon}) {
  return Center(
    child: Padding(
      padding: const EdgeInsets.all(16),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon ?? Icons.inbox_outlined,
              size: 32, color: Theme.of(context).colorScheme.outline),
          const SizedBox(height: 8),
          Text(
            message,
            textAlign: TextAlign.center,
            style: Theme.of(context).textTheme.bodySmall?.copyWith(
                color: Theme.of(context).colorScheme.onSurfaceVariant),
          ),
        ],
      ),
    ),
  );
}

// ---------------------------------------------------------------------------
// 1. Radar de observação (facas caindo)
// ---------------------------------------------------------------------------
class RadarPanel extends StatefulWidget {
  const RadarPanel(
      {super.key, required this.accountId, required this.refreshTick});

  final String accountId;
  final int refreshTick;

  @override
  State<RadarPanel> createState() => _RadarPanelState();
}

class _RadarPanelState extends State<RadarPanel> {
  late Future<List<Observation>> _future;

  @override
  void initState() {
    super.initState();
    _future = _load();
  }

  @override
  void didUpdateWidget(covariant RadarPanel old) {
    super.didUpdateWidget(old);
    if (old.accountId != widget.accountId ||
        old.refreshTick != widget.refreshTick) {
      _future = _load();
    }
  }

  Future<List<Observation>> _load() =>
      HvDipRepository(context.read<ApiClient>())
          .listObservations(widget.accountId);

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<List<Observation>>(
      future: _future,
      builder: (context, snap) {
        if (snap.connectionState == ConnectionState.waiting) {
          return const Center(child: CircularProgressIndicator());
        }
        if (snap.hasError) {
          return _panelMessage(context, formatApiError(snap.error!),
              icon: Icons.error_outline);
        }
        final obs = snap.data ?? const [];
        if (obs.isEmpty) {
          return _panelMessage(
              context, 'Nenhuma faca caindo em observação no momento.');
        }
        return ListView.separated(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
          itemCount: obs.length,
          separatorBuilder: (_, __) => const Divider(height: 1),
          itemBuilder: (context, i) {
            final o = obs[i];
            return Padding(
              padding: const EdgeInsets.symmetric(vertical: 6),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Expanded(
                        child: Text(o.ticker,
                            style: Theme.of(context)
                                .textTheme
                                .titleSmall
                                ?.copyWith(fontWeight: FontWeight.w700)),
                      ),
                      _Badge(label: o.status, color: _regimeColor(o.status)),
                      const SizedBox(width: 6),
                      _Badge(
                        label:
                            'rec ${formatPct((o.recoveryProbability ?? 0) * 100)}',
                        color: (o.recoveryProbability ?? 0) >= 0.5
                            ? Colors.green.shade700
                            : Colors.orange.shade800,
                      ),
                    ],
                  ),
                  const SizedBox(height: 4),
                  Wrap(
                    spacing: 6,
                    runSpacing: 4,
                    children: [
                      if (o.recoveryInProgress)
                        const _Badge(label: 'recuperação', color: Colors.teal),
                      if (o.activeCatalyst)
                        const _Badge(
                            label: 'catalisador', color: Colors.indigo),
                      if (o.lastDecision != null)
                        _Badge(
                            label: o.lastDecision!,
                            color: Colors.blueGrey.shade600),
                    ],
                  ),
                  if (o.note != null && o.note!.isNotEmpty) ...[
                    const SizedBox(height: 4),
                    Text(o.note!,
                        style: Theme.of(context).textTheme.bodySmall?.copyWith(
                            color: Theme.of(context)
                                .colorScheme
                                .onSurfaceVariant)),
                  ],
                ],
              ),
            );
          },
        );
      },
    );
  }
}

// ---------------------------------------------------------------------------
// 2. Auto-calibração (hv_dip + day_trade)
// ---------------------------------------------------------------------------
class CalibrationPanel extends StatefulWidget {
  const CalibrationPanel(
      {super.key, required this.accountId, required this.refreshTick});

  final String accountId;
  final int refreshTick;

  @override
  State<CalibrationPanel> createState() => _CalibrationPanelState();
}

class _CalibrationPanelState extends State<CalibrationPanel> {
  late Future<_CalibrationData> _future;

  @override
  void initState() {
    super.initState();
    _future = _load();
  }

  @override
  void didUpdateWidget(covariant CalibrationPanel old) {
    super.didUpdateWidget(old);
    if (old.accountId != widget.accountId ||
        old.refreshTick != widget.refreshTick) {
      _future = _load();
    }
  }

  Future<_CalibrationData> _load() async {
    final client = context.read<ApiClient>();
    final cachedPulse = maybeWatchStore(context)?.pulse;
    final hvDip = HvDipRepository(client);
    final dt = DayTradeRepository(client);
    final results = await Future.wait([
      hvDip.getConfig(widget.accountId),
      hvDip.getConfigHistory(widget.accountId),
      dt.getConfig(widget.accountId),
      dt.getConfigHistory(widget.accountId),
    ]);
    final pulse =
        cachedPulse ?? await IntelligenceRepository(client).getPulse();
    return _CalibrationData(
      hvDip: results[0] as HvDipConfig,
      hvDipHistory: results[1] as List<HvDipConfigHistory>,
      dayTrade: results[2] as DayTradeConfig,
      dayTradeHistory: results[3] as List<DayTradeConfigHistory>,
      pulse: pulse,
    );
  }

  Future<void> _rollbackHvDip() async {
    final repo = HvDipRepository(context.read<ApiClient>());
    try {
      final data = await _future;
      HvDipConfigHistory? prev;
      for (final h in data.hvDipHistory) {
        if (h.version < data.hvDip.version &&
            (prev == null || h.version > prev.version)) {
          prev = h;
        }
      }
      if (prev == null) {
        _toast('Sem versão anterior para restaurar.');
        return;
      }
      await repo.rollbackConfig(widget.accountId, prev.version);
      setState(() => _future = _load());
      _toast('Config hv_dip restaurada para v${prev.version}.');
    } catch (e) {
      _toast(formatApiError(e));
    }
  }

  void _toast(String msg) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(msg)));
  }

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<_CalibrationData>(
      future: _future,
      builder: (context, snap) {
        if (snap.connectionState == ConnectionState.waiting) {
          return const Center(child: CircularProgressIndicator());
        }
        if (snap.hasError) {
          return _panelMessage(context, formatApiError(snap.error!),
              icon: Icons.error_outline);
        }
        final d = snap.data!;
        return ListView(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
          children: [
            _sectionTitle(
                context, 'hv_dip · v${d.hvDip.version} (${d.hvDip.origin})'),
            ...d.hvDip.params.entries
                .map((e) => _kvLine(context, e.key, e.value)),
            const Divider(),
            _sectionTitle(context,
                'day_trade · v${d.dayTrade.version} (${d.dayTrade.origin})'),
            ...d.dayTrade.params.entries
                .map((e) => _kvLine(context, e.key, e.value)),
            const Divider(),
            Row(
              children: [
                Expanded(
                  child: _sectionTitle(
                      context, 'histórico · ${d.hvDipHistory.length} entradas'),
                ),
                IconButton(
                  tooltip: 'Restaurar versão anterior do hv_dip',
                  visualDensity: VisualDensity.compact,
                  onPressed: _rollbackHvDip,
                  icon: const Icon(Icons.restore, size: 18),
                ),
              ],
            ),
            ...d.hvDipHistory.take(4).map((h) => _kvLine(
                context,
                'v${h.version} · ${h.origin}',
                h.reason.isEmpty ? '—' : h.reason)),
            if (d.dayTradeHistory.isNotEmpty) ...[
              const Divider(),
              _sectionTitle(context,
                  'day_trade histórico · ${d.dayTradeHistory.length}'),
              ...d.dayTradeHistory.take(4).map((h) => _kvLine(
                  context,
                  'v${h.version} · ${h.origin}',
                  h.reason.isEmpty ? '—' : h.reason)),
            ],
            if (d.pulse.deskSlices.isNotEmpty) ...[
              const Divider(),
              _sectionTitle(context,
                  'desk slices · v${d.pulse.deskSlices['version'] ?? '—'}'),
              _kvLine(context, 'fatias', d.pulse.deskSlices['slices']),
              _kvLine(context, 'validação', d.pulse.deskSlices['validation']),
            ],
          ],
        );
      },
    );
  }

  Widget _sectionTitle(BuildContext context, String title) {
    return Padding(
      padding: const EdgeInsets.only(top: 4, bottom: 2),
      child: Text(title,
          style: Theme.of(context)
              .textTheme
              .labelMedium
              ?.copyWith(fontWeight: FontWeight.w700)),
    );
  }

  Widget _kvLine(BuildContext context, String key, Object? value) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 2),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Expanded(
            child: Text(key, style: Theme.of(context).textTheme.bodySmall),
          ),
          const SizedBox(width: 8),
          Text(_fmtValue(value),
              style: Theme.of(context)
                  .textTheme
                  .bodySmall
                  ?.copyWith(fontWeight: FontWeight.w600)),
        ],
      ),
    );
  }
}

class _CalibrationData {
  const _CalibrationData({
    required this.hvDip,
    required this.hvDipHistory,
    required this.dayTrade,
    this.dayTradeHistory = const [],
    this.pulse = const IntelligencePulse(available: false),
  });

  final HvDipConfig hvDip;
  final List<HvDipConfigHistory> hvDipHistory;
  final DayTradeConfig dayTrade;
  final List<DayTradeConfigHistory> dayTradeHistory;
  final IntelligencePulse pulse;
}

// ---------------------------------------------------------------------------
// 3. Feed de catalisadores
// ---------------------------------------------------------------------------
class CatalystsPanel extends StatefulWidget {
  const CatalystsPanel(
      {super.key, required this.accountId, required this.refreshTick});

  final String accountId;
  final int refreshTick;

  @override
  State<CatalystsPanel> createState() => _CatalystsPanelState();
}

class _CatalystsPanelState extends State<CatalystsPanel> {
  late Future<List<NewsEvent>> _future;

  @override
  void initState() {
    super.initState();
    _future = _load();
  }

  @override
  void didUpdateWidget(covariant CatalystsPanel old) {
    super.didUpdateWidget(old);
    if (old.accountId != widget.accountId ||
        old.refreshTick != widget.refreshTick) {
      _future = _load();
    }
  }

  Future<List<NewsEvent>> _load() =>
      CatalystsRepository(context.read<ApiClient>())
          .listNewsEvents(widget.accountId);

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<List<NewsEvent>>(
      future: _future,
      builder: (context, snap) {
        if (snap.connectionState == ConnectionState.waiting) {
          return const Center(child: CircularProgressIndicator());
        }
        if (snap.hasError) {
          return _panelMessage(context, formatApiError(snap.error!),
              icon: Icons.error_outline);
        }
        final events = snap.data ?? const [];
        if (events.isEmpty) {
          return _panelMessage(
              context, 'Nenhum catalisador classificado ainda.');
        }
        return ListView.separated(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
          itemCount: events.length,
          separatorBuilder: (_, __) => const Divider(height: 1),
          itemBuilder: (context, i) {
            final e = events[i];
            return Padding(
              padding: const EdgeInsets.symmetric(vertical: 6),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      if (e.ticker != null) ...[
                        Text(e.ticker!,
                            style: Theme.of(context)
                                .textTheme
                                .titleSmall
                                ?.copyWith(fontWeight: FontWeight.w700)),
                        const SizedBox(width: 8),
                      ],
                      if (e.eventType != null)
                        _Badge(
                            label: e.eventType!,
                            color: Colors.blueGrey.shade600),
                      const SizedBox(width: 6),
                      if (e.sentiment != null)
                        _Badge(
                            label: e.sentiment!,
                            color: _sentimentColor(e.sentiment)),
                    ],
                  ),
                  const SizedBox(height: 2),
                  Text(e.title,
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: Theme.of(context).textTheme.bodySmall),
                  const SizedBox(height: 2),
                  Text(
                    [
                      if (e.confidence != null)
                        'conf ${formatPct((e.confidence! * 100))}',
                      if (e.impactScore != null)
                        'impacto ${formatRatio(e.impactScore)}',
                      if (e.catalystStrength != null) e.catalystStrength!,
                    ].join(' · '),
                    style: Theme.of(context).textTheme.labelSmall?.copyWith(
                        color: Theme.of(context).colorScheme.onSurfaceVariant),
                  ),
                ],
              ),
            );
          },
        );
      },
    );
  }
}

// ---------------------------------------------------------------------------
// 4. Analytics profunda (by_ticker / by_side)
// ---------------------------------------------------------------------------
class AnalyticsPanel extends StatefulWidget {
  const AnalyticsPanel(
      {super.key, required this.accountId, required this.refreshTick});

  final String accountId;
  final int refreshTick;

  @override
  State<AnalyticsPanel> createState() => _AnalyticsPanelState();
}

class _AnalyticsPanelState extends State<AnalyticsPanel> {
  late Future<DayTradeAnalytics> _future;

  @override
  void initState() {
    super.initState();
    _future = _load();
  }

  @override
  void didUpdateWidget(covariant AnalyticsPanel old) {
    super.didUpdateWidget(old);
    if (old.accountId != widget.accountId ||
        old.refreshTick != widget.refreshTick) {
      _future = _load();
    }
  }

  Future<DayTradeAnalytics> _load() =>
      DayTradeRepository(context.read<ApiClient>())
          .getAnalytics(widget.accountId);

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<DayTradeAnalytics>(
      future: _future,
      builder: (context, snap) {
        if (snap.connectionState == ConnectionState.waiting) {
          return const Center(child: CircularProgressIndicator());
        }
        if (snap.hasError) {
          return _panelMessage(context, formatApiError(snap.error!),
              icon: Icons.error_outline);
        }
        final a = snap.data!;
        if (a.totalClosed == 0 && a.byTicker.isEmpty && a.bySide.isEmpty) {
          return _panelMessage(
              context, 'Sem trades day-trade fechados para analisar.');
        }
        return ListView(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
          children: [
            _statHeader(context, '${a.totalClosed} trades fechados'),
            if (a.byTicker.isNotEmpty) ...[
              _statHeader(context, 'Por ticker'),
              ...a.byTicker.map((s) => _statRow(context, s)),
            ],
            if (a.bySide.isNotEmpty) ...[
              _statHeader(context, 'Por lado'),
              ...a.bySide.map((s) => _statRow(context, s)),
            ],
          ],
        );
      },
    );
  }

  Widget _statHeader(BuildContext context, String title) {
    return Padding(
      padding: const EdgeInsets.only(top: 4, bottom: 2),
      child: Text(title,
          style: Theme.of(context)
              .textTheme
              .labelMedium
              ?.copyWith(fontWeight: FontWeight.w700)),
    );
  }

  Widget _statRow(BuildContext context, DayTradeGroupStat s) {
    final expectancy = s.expectancyR;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 3),
      child: Row(
        children: [
          SizedBox(
            width: 72,
            child: Text(s.key,
                style: Theme.of(context)
                    .textTheme
                    .bodySmall
                    ?.copyWith(fontWeight: FontWeight.w600)),
          ),
          Expanded(
            child: Text('n=${s.n} · WR ${formatPct(s.winRate)}',
                style: Theme.of(context).textTheme.bodySmall),
          ),
          Text(
            'E ${expectancy == null ? '—' : formatRatio(expectancy)}'
            ' · PF ${s.profitFactor == null ? '—' : formatRatio(s.profitFactor)}',
            style: Theme.of(context).textTheme.bodySmall?.copyWith(
                fontWeight: FontWeight.w600,
                color: (expectancy ?? 0) >= 0
                    ? Colors.green.shade700
                    : Colors.red.shade700),
          ),
        ],
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// 5. Regime + Circuit breaker
// ---------------------------------------------------------------------------
class RegimePanel extends StatefulWidget {
  const RegimePanel(
      {super.key, required this.accountId, required this.refreshTick});

  final String accountId;
  final int refreshTick;

  @override
  State<RegimePanel> createState() => _RegimePanelState();
}

class _RegimePanelState extends State<RegimePanel> {
  late Future<DayTradeState> _future;

  @override
  void initState() {
    super.initState();
    _future = _load();
  }

  @override
  void didUpdateWidget(covariant RegimePanel old) {
    super.didUpdateWidget(old);
    if (old.accountId != widget.accountId ||
        old.refreshTick != widget.refreshTick) {
      _future = _load();
    }
  }

  Future<DayTradeState> _load() =>
      DayTradeRepository(context.read<ApiClient>()).getState(widget.accountId);

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<DayTradeState>(
      future: _future,
      builder: (context, snap) {
        if (snap.connectionState == ConnectionState.waiting) {
          return const Center(child: CircularProgressIndicator());
        }
        if (snap.hasError) {
          return _panelMessage(context, formatApiError(snap.error!),
              icon: Icons.error_outline);
        }
        final st = snap.data!;
        return ListView(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
          children: [
            Row(
              children: [
                Expanded(
                  child: Text('Circuit breaker',
                      style: Theme.of(context)
                          .textTheme
                          .labelMedium
                          ?.copyWith(fontWeight: FontWeight.w700)),
                ),
                _Badge(
                  label:
                      st.circuitBreakerTripped.isEmpty ? 'armado' : 'disparado',
                  color: st.circuitBreakerTripped.isEmpty
                      ? Colors.green.shade700
                      : Colors.red.shade700,
                ),
              ],
            ),
            if (st.circuitBreakerTripped.isEmpty)
              Padding(
                padding: const EdgeInsets.only(top: 2),
                child: Text('Nenhum ticker em halt de proteção.',
                    style: Theme.of(context).textTheme.bodySmall),
              )
            else
              ...st.circuitBreakerTripped.map((t) => Padding(
                    padding: const EdgeInsets.symmetric(vertical: 2),
                    child: Text('• $t',
                        style: Theme.of(context)
                            .textTheme
                            .bodySmall
                            ?.copyWith(color: Colors.red.shade700)),
                  )),
            const Divider(),
            Text('Regimes por ticker',
                style: Theme.of(context)
                    .textTheme
                    .labelMedium
                    ?.copyWith(fontWeight: FontWeight.w700)),
            const SizedBox(height: 4),
            if (st.regimes.isEmpty)
              _panelMessage(context, 'Sem regime calculado ainda.')
            else
              ...st.regimes.map((r) => Padding(
                    padding: const EdgeInsets.symmetric(vertical: 3),
                    child: Row(
                      children: [
                        SizedBox(
                          width: 72,
                          child: Text(r.ticker,
                              style: Theme.of(context)
                                  .textTheme
                                  .bodySmall
                                  ?.copyWith(fontWeight: FontWeight.w600)),
                        ),
                        _Badge(label: r.regime, color: _regimeColor(r.regime)),
                        const Spacer(),
                        if (r.slope != null)
                          Text('slope ${formatRatio(r.slope)}',
                              style: Theme.of(context).textTheme.labelSmall),
                      ],
                    ),
                  )),
          ],
        );
      },
    );
  }
}

// ---------------------------------------------------------------------------
// 6. Curva de equity
// ---------------------------------------------------------------------------
class EquityPanel extends StatefulWidget {
  const EquityPanel(
      {super.key, required this.accountId, required this.refreshTick});

  final String accountId;
  final int refreshTick;

  @override
  State<EquityPanel> createState() => _EquityPanelState();
}

class _EquityPanelState extends State<EquityPanel> {
  late Future<_EquityData> _future;

  @override
  void initState() {
    super.initState();
    _future = _load();
  }

  @override
  void didUpdateWidget(covariant EquityPanel old) {
    super.didUpdateWidget(old);
    if (old.accountId != widget.accountId ||
        old.refreshTick != widget.refreshTick) {
      _future = _load();
    }
  }

  Future<_EquityData> _load() async {
    final repo = PortfolioRepository(context.read<ApiClient>());
    final results = await Future.wait([
      repo.getPnlSeries(widget.accountId),
      repo.getPortfolio(widget.accountId),
    ]);
    return _EquityData(
      series: results[0] as PnlSeries,
      portfolio: results[1] as Portfolio,
    );
  }

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<_EquityData>(
      future: _future,
      builder: (context, snap) {
        if (snap.connectionState == ConnectionState.waiting) {
          return const Center(child: CircularProgressIndicator());
        }
        if (snap.hasError) {
          return _panelMessage(context, formatApiError(snap.error!),
              icon: Icons.error_outline);
        }
        final d = snap.data!;
        final points = d.series.points
            .map((p) => PnlPoint(
                  date: p.date,
                  cumulativePnl: p.cumulativePnl,
                  dayPnl: p.dayPnl,
                  targetCumulativePnl: p.targetCumulativePnl,
                  dayTargetPnl: p.dayTargetPnl,
                  dayPnlPct: p.dayPnlPct,
                  dayTargetPct: p.dayTargetPct,
                ))
            .toList();
        return ListView(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
          children: [
            Row(
              children: [
                Expanded(
                  child: Text(
                    'Equity ${formatMoney(d.portfolio.equityBrl, currency: d.portfolio.currency)}',
                    style: Theme.of(context)
                        .textTheme
                        .titleSmall
                        ?.copyWith(fontWeight: FontWeight.w700),
                  ),
                ),
                Text(
                  'dia ${formatMoney(d.portfolio.realizedPnlDayBrl, currency: d.portfolio.currency)}',
                  style: Theme.of(context).textTheme.bodySmall?.copyWith(
                      fontWeight: FontWeight.w600,
                      color: d.portfolio.realizedPnlDayBrl >= 0
                          ? Colors.green.shade700
                          : Colors.red.shade700),
                ),
              ],
            ),
            const SizedBox(height: 4),
            PnlLineChart(
              points: points,
              currency: d.series.currency,
              height: 140,
              dailyTargetPct: d.series.dailyTargetPct,
            ),
          ],
        );
      },
    );
  }
}

class _EquityData {
  const _EquityData({required this.series, required this.portfolio});

  final PnlSeries series;
  final Portfolio portfolio;
}

// ---------------------------------------------------------------------------
// Pulso noturno (HITL só leitura)
// ---------------------------------------------------------------------------
class PulsePanel extends StatelessWidget {
  const PulsePanel(
      {super.key, required this.accountId, required this.refreshTick});

  final String accountId;
  final int refreshTick;

  @override
  Widget build(BuildContext context) {
    final store = maybeWatchStore(context);
    if (store != null) {
      if (store.loading && store.pulse == null) {
        return const Center(child: CircularProgressIndicator());
      }
      if (store.error != null && store.pulse == null) {
        return _panelMessage(context, formatApiError(store.error!),
            icon: Icons.error_outline);
      }
      return PulsePanelBody(
          pulse: store.pulse ?? IntelligencePulse.unavailable());
    }
    return _PulsePanelFetch(refreshTick: refreshTick);
  }
}

class _PulsePanelFetch extends StatefulWidget {
  const _PulsePanelFetch({required this.refreshTick});

  final int refreshTick;

  @override
  State<_PulsePanelFetch> createState() => _PulsePanelFetchState();
}

class _PulsePanelFetchState extends State<_PulsePanelFetch> {
  late Future<IntelligencePulse> _future;

  @override
  void initState() {
    super.initState();
    _future = _load();
  }

  @override
  void didUpdateWidget(covariant _PulsePanelFetch old) {
    super.didUpdateWidget(old);
    if (old.refreshTick != widget.refreshTick) {
      _future = _load();
    }
  }

  Future<IntelligencePulse> _load() =>
      IntelligenceRepository(context.read<ApiClient>()).getPulse();

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<IntelligencePulse>(
      future: _future,
      builder: (context, snap) {
        if (snap.connectionState == ConnectionState.waiting) {
          return const Center(child: CircularProgressIndicator());
        }
        if (snap.hasError) {
          return _panelMessage(context, formatApiError(snap.error!),
              icon: Icons.error_outline);
        }
        return PulsePanelBody(pulse: snap.data ?? IntelligencePulse.unavailable());
      },
    );
  }
}

/// Presentational body so widget tests do not need [ApiClient].
class PulsePanelBody extends StatelessWidget {
  const PulsePanelBody({super.key, required this.pulse});

  final IntelligencePulse pulse;

  static const _learnFloor = 30;

  @override
  Widget build(BuildContext context) {
    if (!pulse.available &&
        pulse.swingH1 == null &&
        pulse.ollama == null &&
        !pulse.groqCooldown) {
      return _panelMessage(
        context,
        'Pulso ainda não rodou. O worker grava o snapshot às 06:00 UTC.',
        icon: Icons.hourglass_empty,
      );
    }
    final cal = pulse.calibration;
    final hitRate = cal['hit_rate'];
    final brier = cal['brier'];
    final nLabeled = cal['n_labeled'] ?? pulse.newsJsonOk;
    final h1 = pulse.swingH1;
    final llmLine = llmHealthLine(
      ollama: pulse.ollama,
      groqCooldown: pulse.groqCooldown,
      expiresAt: pulse.ollamaExpiresAt,
    );
    final lastLine = lastLlmLine(pulse.lastLlmSource);
    return ListView(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      children: [
        if (h1 != null) ...[
          Text(
            h1PulseLine(
              ok: h1['h1_ok'] ?? 0,
              skip: h1['h1_skip'] ?? 0,
              fail: h1['h1_fail'] ?? 0,
              ts: pulse.swingH1Ts,
            ),
            style: Theme.of(context)
                .textTheme
                .bodySmall
                ?.copyWith(fontWeight: FontWeight.w600),
          ),
          const SizedBox(height: 6),
        ],
        if (llmLine != null) ...[
          Text(
            llmLine,
            style: Theme.of(context).textTheme.bodySmall,
          ),
          const SizedBox(height: 6),
        ],
        if (lastLine != null) ...[
          Text(
            lastLine,
            style: Theme.of(context).textTheme.bodySmall,
          ),
          const SizedBox(height: 6),
        ],
        if (!pulse.available)
          Text(
            'Pulso noturno ainda não rodou. O worker grava o snapshot às 06:00 UTC.',
            style: Theme.of(context).textTheme.bodySmall,
          )
        else ...[
          Text(
            'n_labeled ${nLabeled ?? '—'} · hit ${_fmtValue(hitRate)} · brier ${_fmtValue(brier)}',
            style: Theme.of(context)
                .textTheme
                .bodySmall
                ?.copyWith(fontWeight: FontWeight.w600),
          ),
          if (pulse.assertiveness['by_source'] is Map) ...[
            const SizedBox(height: 4),
            Text(
              _assertivenessLine(pulse.assertiveness),
              style: Theme.of(context).textTheme.bodySmall,
            ),
          ],
          const SizedBox(height: 6),
          Text(
            'USD fechados ${pulse.nClosedUsd} · auto-buy ${pulse.hvDipAutoBuyEnabled ? 'ligado' : 'desligado'}'
            '${pulse.hvDipLiveAutoBuy ? ' · live auto-buy ligado' : ''}',
            style: Theme.of(context).textTheme.bodySmall,
          ),
          if (pulse.ts != null)
            Text('snapshot ${pulse.ts}',
                style: Theme.of(context).textTheme.labelSmall),
          if (pulse.livePromotion['items'] is List) ...[
            const SizedBox(height: 6),
            Text(
              pulse.livePromotion['ready'] == true
                  ? 'Live: checklist verde'
                  : 'Live: checklist incompleto',
              style: Theme.of(context)
                  .textTheme
                  .bodySmall
                  ?.copyWith(fontWeight: FontWeight.w600),
            ),
            for (final raw in pulse.livePromotion['items'] as List)
              if (raw is Map)
                Text(
                  '${raw['ok'] == true ? 'ok' : 'não'} · ${raw['detail'] ?? raw['id']}',
                  style: Theme.of(context).textTheme.labelSmall,
                ),
          ],
          const Divider(),
          ...['hv_dip', 'desk', 'day_trade'].map((kind) {
            final st = pulse.learn[kind];
            final n = st?.n;
            final status = st?.status ?? 'unknown';
            final floor = n == null
                ? status
                : (n < _learnFloor
                    ? '$status · $n < $_learnFloor'
                    : '$status · $n');
            return Padding(
              padding: const EdgeInsets.symmetric(vertical: 2),
              child: Text(
                '$kind · $floor',
                style: Theme.of(context).textTheme.bodySmall,
              ),
            );
          }),
          const Divider(),
          if (pulse.recentReviews.isEmpty)
            Text('Sem post-mortem ainda.',
                style: Theme.of(context).textTheme.bodySmall)
          else
            ...pulse.recentReviews.map(
              (r) => Padding(
                padding: const EdgeInsets.symmetric(vertical: 4),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      '${r.ticker} · ${r.wouldChange.isEmpty ? '—' : r.wouldChange}',
                      style: Theme.of(context)
                          .textTheme
                          .labelMedium
                          ?.copyWith(fontWeight: FontWeight.w700),
                    ),
                    if (r.lesson.isNotEmpty)
                      Text(r.lesson,
                          style: Theme.of(context).textTheme.bodySmall),
                  ],
                ),
              ),
            ),
        ],
      ],
    );
  }
}

// ---------------------------------------------------------------------------
// 8. Estudos ativos (padrão / tendência / chance)
// ---------------------------------------------------------------------------
class StudiesPanel extends StatelessWidget {
  const StudiesPanel(
      {super.key, required this.accountId, required this.refreshTick});

  final String accountId;
  final int refreshTick;

  @override
  Widget build(BuildContext context) {
    final store = maybeWatchStore(context);
    if (store != null) {
      if (store.loading && store.pulse == null) {
        return const Center(child: CircularProgressIndicator());
      }
      if (store.error != null && store.pulse == null) {
        return _panelMessage(context, formatApiError(store.error!),
            icon: Icons.error_outline);
      }
      return StudiesPanelBody(studies: store.pulse?.studies);
    }
    return _StudiesPanelFetch(refreshTick: refreshTick);
  }
}

class _StudiesPanelFetch extends StatefulWidget {
  const _StudiesPanelFetch({required this.refreshTick});

  final int refreshTick;

  @override
  State<_StudiesPanelFetch> createState() => _StudiesPanelFetchState();
}

class _StudiesPanelFetchState extends State<_StudiesPanelFetch> {
  IntelligencePulse? _data;
  Object? _error;
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void didUpdateWidget(covariant _StudiesPanelFetch old) {
    super.didUpdateWidget(old);
    if (old.refreshTick != widget.refreshTick) {
      _load();
    }
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final pulse =
          await IntelligenceRepository(context.read<ApiClient>()).getPulse();
      if (!mounted) return;
      setState(() {
        _data = pulse;
        _loading = false;
        _error = null;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = e;
        _loading = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_loading) {
      return const Center(child: CircularProgressIndicator());
    }
    if (_error != null) {
      return _panelMessage(context, formatApiError(_error!),
          icon: Icons.error_outline);
    }
    return StudiesPanelBody(studies: _data?.studies);
  }
}

double? _pRecover(StudyResult r) {
  // The desk's ruler: P(close above entry after the horizon) — "does it
  // appreciate again in ~2 weeks?" — not the tighter target-before-stop ratio.
  if (r.n == 0 || r.pRecover == null) return null;
  return r.pRecover;
}

/// Presentational body so widget tests do not need [ApiClient].
class StudiesPanelBody extends StatelessWidget {
  const StudiesPanelBody({super.key, required this.studies});

  final StudiesSnapshot? studies;

  @override
  Widget build(BuildContext context) {
    final snap = studies;
    if (snap == null ||
        (snap.queries.isEmpty && snap.results.isEmpty && snap.insights.isEmpty)) {
      return _panelMessage(context,
          'Nenhum estudo ativo ainda. O worker calcula analogias em tempo real.',
          icon: Icons.query_stats);
    }

    final byQuery = <String, List<StudyResult>>{};
    for (final r in snap.results) {
      byQuery.putIfAbsent(r.queryId, () => []).add(r);
    }
    StudyResult? universeOf(String id) {
      for (final r in byQuery[id] ?? const <StudyResult>[]) {
        if (r.ticker == 'UNIVERSE') return r;
      }
      return null;
    }

    final decisions = <String, Map<String, dynamic>>{
      for (final d in snap.decisions)
        if (d['key'] is String) d['key'] as String: d,
    };

    return ListView(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      children: [
        for (final q in snap.queries) ...[
          _StudyCard(
            query: q,
            universe: universeOf(q.id),
            perTicker: (byQuery[q.id] ?? const <StudyResult>[])
                .where((r) => r.ticker != 'UNIVERSE')
                .toList(),
            decision: decisions['${q.channel}:${q.fingerprint}'],
          ),
          const Divider(height: 1),
        ],
        if (snap.guards.isNotEmpty) ...[
          const Divider(),
          Text(
            'Guards',
            style: Theme.of(context)
                .textTheme
                .labelMedium
                ?.copyWith(fontWeight: FontWeight.w700),
          ),
          for (final e in snap.guards.entries)
            Text(
              '${e.key} · ${(e.value is Map ? e.value['reason'] : e.value) ?? ''}',
              style: Theme.of(context).textTheme.bodySmall,
            ),
        ],
        if (snap.insights.isNotEmpty) ...[
          const Divider(),
          Padding(
            padding: const EdgeInsets.only(top: 4, bottom: 2),
            child: Text(
              'Insights',
              style: Theme.of(context)
                  .textTheme
                  .labelMedium
                  ?.copyWith(fontWeight: FontWeight.w700),
            ),
          ),
          for (final ins in snap.insights) _InsightCard(insight: ins),
        ],
      ],
    );
  }
}

class _StudyCard extends StatelessWidget {
  const _StudyCard({
    required this.query,
    required this.universe,
    required this.perTicker,
    required this.decision,
  });

  final StudyQuery query;
  final StudyResult? universe;
  final List<StudyResult> perTicker;
  final Map<String, dynamic>? decision;

  @override
  Widget build(BuildContext context) {
    final u = universe;
    final action = decision?['action'] as String?;
    final reason = decision?['reason'] as String?;

    final badges = <Widget>[];
    if (action == 'force_review' || action == 'suppress') {
      badges.add(_Badge(label: 'desk bloqueou', color: Colors.red.shade700));
    } else if (action == 'skipped') {
      badges.add(_Badge(label: 'skipped', color: Colors.blueGrey.shade600));
    } else if (action == 'hold') {
      badges.add(_Badge(label: 'observando', color: Colors.green.shade700));
    }

    final pTarget = u == null ? null : _pRecover(u);
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  query.label,
                  style: Theme.of(context)
                      .textTheme
                      .labelMedium
                      ?.copyWith(fontWeight: FontWeight.w700),
                ),
              ),
              ...badges,
            ],
          ),
          const SizedBox(height: 2),
          Text(
            u == null
                ? 'n=0 · sem analogias suficientes'
                : 'n=${u.n} · P(valorizar ~2 sem) ${formatPct((pTarget ?? 0) * 100)}'
                    ' · tendência ${formatPct((u.trendUp ?? 0) * 100)}'
                    '${u.oosN > 0 ? ' · OOS n=${u.oosN}'
                        '${u.oosPRecover == null ? '' : ' p=${u.oosPRecover}'}' : ''}',
            style: Theme.of(context).textTheme.bodySmall?.copyWith(
                  fontWeight: FontWeight.w600,
                  color: (pTarget ?? 0) >= 0.5
                      ? Colors.green.shade700
                      : Colors.orange.shade800,
                ),
          ),
          if (reason != null && reason.isNotEmpty) ...[
            const SizedBox(height: 2),
            Text(reason,
                style: Theme.of(context).textTheme.labelSmall?.copyWith(
                    color: Theme.of(context).colorScheme.onSurfaceVariant)),
          ],
          if (perTicker.isNotEmpty) ...[
            const SizedBox(height: 4),
            for (final r in perTicker.take(5))
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 1),
                child: Text(
                  '${r.ticker} · n=${r.n}'
                  '${r.vsUniverse == null ? '' : ' · vs universo ${r.vsUniverse! >= 0 ? '+' : ''}${formatRatio(r.vsUniverse! * 100)}pp'}',
                  style: Theme.of(context).textTheme.labelSmall,
                ),
              ),
          ],
        ],
      ),
    );
  }
}

class _InsightCard extends StatelessWidget {
  const _InsightCard({required this.insight});

  final Insight insight;

  @override
  Widget build(BuildContext context) {
    final isUniverse = insight.kind == 'universe';
    final color = isUniverse ? Colors.indigo.shade700 : Colors.teal.shade700;
    return Card(
      margin: const EdgeInsets.symmetric(vertical: 4),
      child: Padding(
        padding: const EdgeInsets.all(10),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                _Badge(label: insight.kind, color: color),
                if (insight.ticker.isNotEmpty &&
                    insight.ticker != 'UNIVERSE') ...[
                  const SizedBox(width: 6),
                  _Badge(
                      label: insight.ticker, color: Colors.blueGrey.shade600),
                ],
                const Spacer(),
                Text(
                  'conf ${formatPct(insight.confidence * 100)}',
                  style: Theme.of(context).textTheme.labelSmall?.copyWith(
                      color: Theme.of(context).colorScheme.onSurfaceVariant),
                ),
              ],
            ),
            const SizedBox(height: 6),
            Text(
              insight.text,
              style: Theme.of(context)
                  .textTheme
                  .bodySmall
                  ?.copyWith(fontWeight: FontWeight.w600),
            ),
            if (insight.evidence.isNotEmpty) ...[
              const SizedBox(height: 6),
              Wrap(
                spacing: 6,
                runSpacing: 4,
                children: [
                  for (final e in insight.evidence)
                    _EvidenceChip(fact: e.fact, value: e.value),
                ],
              ),
            ],
          ],
        ),
      ),
    );
  }
}

class _EvidenceChip extends StatelessWidget {
  const _EvidenceChip({required this.fact, required this.value});

  final String fact;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(
        color: Theme.of(context).colorScheme.surfaceContainerHighest,
        borderRadius: BorderRadius.circular(6),
      ),
      child: Text(
        value.isEmpty ? fact : '$fact: $value',
        style: Theme.of(context).textTheme.labelSmall,
      ),
    );
  }
}

/// Live day-trade signals for the session. The learn loop only produces samples
/// when signals actually fire, so this panel is how a stall becomes visible
/// instead of silent.
class SignalsPanel extends StatefulWidget {
  const SignalsPanel(
      {super.key, required this.accountId, required this.refreshTick});

  final String accountId;
  final int refreshTick;

  @override
  State<SignalsPanel> createState() => _SignalsPanelState();
}

class _SignalsPanelState extends State<SignalsPanel> {
  late Future<List<DayTradeSignal>> _future;

  @override
  void initState() {
    super.initState();
    _future = _load();
  }

  @override
  void didUpdateWidget(covariant SignalsPanel old) {
    super.didUpdateWidget(old);
    if (old.accountId != widget.accountId ||
        old.refreshTick != widget.refreshTick) {
      _future = _load();
    }
  }

  Future<List<DayTradeSignal>> _load() =>
      DayTradeRepository(context.read<ApiClient>())
          .listSignals(widget.accountId);

  @override
  Widget build(BuildContext context) {
    final store = maybeWatchStore(context);
    return FutureBuilder<List<DayTradeSignal>>(
      future: _future,
      builder: (context, snap) {
        if (snap.connectionState == ConnectionState.waiting) {
          return const Center(child: CircularProgressIndicator());
        }
        if (snap.hasError) {
          return _panelMessage(context, formatApiError(snap.error!),
              icon: Icons.error_outline);
        }
        return SignalsPanelBody(
          signals: snap.data ?? const [],
          gatedRules: _gatedRulesFromPulse(store?.pulse),
        );
      },
    );
  }
}

/// Stateless body so the layout can be widget-tested without a live API.
List<String> _gatedRulesFromPulse(IntelligencePulse? pulse) {
  final raw = pulse?.dtGates['rules'];
  if (raw is! List) return const [];
  return raw.map((e) => e.toString()).where((e) => e.isNotEmpty).toList();
}

class SignalsPanelBody extends StatelessWidget {
  const SignalsPanelBody({
    super.key,
    required this.signals,
    this.gatedRules = const [],
  });

  final List<DayTradeSignal> signals;
  final List<String> gatedRules;

  @override
  Widget build(BuildContext context) {
    if (signals.isEmpty) {
      if (gatedRules.isEmpty) {
        return _panelMessage(
          context,
          'Nenhum sinal day trade ainda. O streamer gera sinais durante o pregão.',
          icon: Icons.bolt_outlined,
        );
      }
      return ListView(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
        children: [
          Text(
            'regra cortada: soma R — ${gatedRules.join(', ')}',
            style: Theme.of(context).textTheme.labelSmall?.copyWith(
                  color: Colors.red.shade700,
                  fontWeight: FontWeight.w600,
                ),
          ),
          const SizedBox(height: 8),
          Text(
            'Nenhum sinal day trade ainda. O streamer gera sinais durante o pregão.',
            style: Theme.of(context).textTheme.bodySmall,
          ),
        ],
      );
    }

    final sorted = [...signals]
      ..sort((a, b) => b.createdAt.compareTo(a.createdAt));
    final latestSession = sorted.first.sessionDate;
    final open = sorted.where((s) => s.status == 'open').toList();
    final closed = sorted.where((s) => s.status == 'closed').toList();
    final totalPnl = closed.fold<double>(
        0, (sum, s) => sum + (s.simulatedPnlUsd ?? 0));

    return ListView(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      children: [
        Row(
          children: [
            _Badge(
              label: '${open.length} abertos',
              color: open.isEmpty ? Colors.blueGrey.shade500 : Colors.blue.shade700,
            ),
            const SizedBox(width: 6),
            _Badge(
              label: '${closed.length} fechados',
              color: Colors.blueGrey.shade500,
            ),
            const SizedBox(width: 6),
            _Badge(
              label: formatUsd(totalPnl),
              color: totalPnl >= 0 ? Colors.green.shade700 : Colors.red.shade700,
            ),
          ],
        ),
        if (gatedRules.isNotEmpty) ...[
          const SizedBox(height: 6),
          Text(
            'regra cortada: soma R — ${gatedRules.join(', ')}',
            style: Theme.of(context).textTheme.labelSmall?.copyWith(
                  color: Colors.red.shade700,
                  fontWeight: FontWeight.w600,
                ),
          ),
        ],
        const SizedBox(height: 4),
        Text(
          'Sessão mais recente: ${_sessionLabel(latestSession)}',
          style: Theme.of(context).textTheme.labelSmall?.copyWith(
              color: Theme.of(context).colorScheme.onSurfaceVariant),
        ),
        const Divider(),
        for (final s in sorted.take(40)) _SignalRow(signal: s),
      ],
    );
  }
}

String _sessionLabel(DateTime d) =>
    '${d.day.toString().padLeft(2, '0')}/${d.month.toString().padLeft(2, '0')}';

Color _signalStatusColor(DayTradeSignal s) {
  switch (s.status) {
    case 'open':
      return Colors.blue.shade700;
    case 'expired':
      return Colors.blueGrey.shade500;
    case 'closed':
      return (s.simulatedPnlUsd ?? 0) >= 0
          ? Colors.green.shade700
          : Colors.red.shade700;
    default:
      return Colors.blueGrey.shade500;
  }
}

class _SignalRow extends StatelessWidget {
  const _SignalRow({required this.signal});

  final DayTradeSignal signal;

  @override
  Widget build(BuildContext context) {
    final s = signal;
    final isShort = s.side.toLowerCase().contains('short');
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(
                isShort ? Icons.south_east : Icons.north_east,
                size: 14,
                color: isShort ? Colors.red.shade700 : Colors.green.shade700,
              ),
              const SizedBox(width: 4),
              Expanded(
                child: Text(
                  s.ticker,
                  style: Theme.of(context)
                      .textTheme
                      .titleSmall
                      ?.copyWith(fontWeight: FontWeight.w700),
                ),
              ),
              _Badge(label: s.status, color: _signalStatusColor(s)),
              if (s.status == 'closed' && s.simulatedPnlUsd != null) ...[
                const SizedBox(width: 6),
                _Badge(
                  label: formatUsd(s.simulatedPnlUsd),
                  color: _signalStatusColor(s),
                ),
              ],
            ],
          ),
          const SizedBox(height: 2),
          Text(
            '${s.ruleId} · ${_sessionLabel(s.sessionDate)} · '
            'entrada ${formatPrice(s.entryPrice)} · '
            'stop ${formatPrice(s.stopPrice)} · '
            'alvo ${formatPrice(s.targetPrice)}',
            style: Theme.of(context).textTheme.labelSmall?.copyWith(
                color: Theme.of(context).colorScheme.onSurfaceVariant),
          ),
        ],
      ),
    );
  }
}

class AssertivenessPanel extends StatelessWidget {
  const AssertivenessPanel(
      {super.key, required this.accountId, required this.refreshTick});

  final String accountId;
  final int refreshTick;

  @override
  Widget build(BuildContext context) {
    final store = maybeWatchStore(context);
    if (store != null) {
      if (store.loading && store.pulse == null) {
        return const Center(child: CircularProgressIndicator());
      }
      if (store.error != null && store.pulse == null) {
        return _panelMessage(context, formatApiError(store.error!),
            icon: Icons.error_outline);
      }
      return AssertivenessPanelBody(
        pulse: store.pulse ?? IntelligencePulse.unavailable(),
      );
    }
    return _AssertivenessPanelFetch(refreshTick: refreshTick);
  }
}

class _AssertivenessPanelFetch extends StatefulWidget {
  const _AssertivenessPanelFetch({required this.refreshTick});

  final int refreshTick;

  @override
  State<_AssertivenessPanelFetch> createState() =>
      _AssertivenessPanelFetchState();
}

class _AssertivenessPanelFetchState extends State<_AssertivenessPanelFetch> {
  late Future<IntelligencePulse> _future;

  @override
  void initState() {
    super.initState();
    _future = _load();
  }

  @override
  void didUpdateWidget(covariant _AssertivenessPanelFetch old) {
    super.didUpdateWidget(old);
    if (old.refreshTick != widget.refreshTick) {
      _future = _load();
    }
  }

  Future<IntelligencePulse> _load() {
    return IntelligenceRepository(context.read<ApiClient>()).getPulse();
  }

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<IntelligencePulse>(
      future: _future,
      builder: (context, snap) {
        if (snap.connectionState == ConnectionState.waiting) {
          return const Center(child: CircularProgressIndicator());
        }
        if (snap.hasError) {
          return _panelMessage(context, formatApiError(snap.error!),
              icon: Icons.error_outline);
        }
        return AssertivenessPanelBody(
          pulse: snap.data ?? IntelligencePulse.unavailable(),
        );
      },
    );
  }
}

class AssertivenessPanelBody extends StatelessWidget {
  const AssertivenessPanelBody({super.key, required this.pulse});

  final IntelligencePulse pulse;

  @override
  Widget build(BuildContext context) {
    final by = pulse.assertiveness['by_source'];
    final curves = pulse.assertiveness['curves'];
    final calibratorsRaw = pulse.assertiveness['calibrators'];
    final calibrators = <String, dynamic>{
      if (pulse.platt.isNotEmpty)
        ...pulse.platt.map((k, v) => MapEntry(k.toString(), v)),
      if (calibratorsRaw is Map)
        ...calibratorsRaw.map((k, v) => MapEntry(k.toString(), v)),
    };
    final byMap = by is Map ? by : const {};
    final hasAnySource = byMap.values.any((v) {
      if (v is! Map) return false;
      final n = (v['n'] as num?)?.toInt() ?? 0;
      final resolved = (v['resolved'] as num?)?.toInt() ?? 0;
      return n > 0 || resolved > 0;
    });
    if (!hasAnySource && calibrators.isEmpty) {
      return _panelMessage(
        context,
        'Ainda sem previsões resolvidas. Quando o ledger pontuar, '
        'este painel mostra: “quando digo 60%, acerto 60%?”.',
        icon: Icons.insights_outlined,
      );
    }
    final newsPlatt = calibrators.entries
        .where((e) => e.key.startsWith('news'))
        .toList();
    return ListView(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      children: [
        Text(
          'Quando o desk diz 60%, acerta 60%?',
          style: Theme.of(context)
              .textTheme
              .bodySmall
              ?.copyWith(fontWeight: FontWeight.w600),
        ),
        const SizedBox(height: 8),
        if (newsPlatt.isNotEmpty) ...[
          Text(
            'Platt (notícia) — sigmoid, sem isotonic.',
            style: Theme.of(context)
                .textTheme
                .labelMedium
                ?.copyWith(fontWeight: FontWeight.w700),
          ),
          ...newsPlatt.map((e) {
            final calMap = e.value is Map ? e.value as Map : const {};
            return Padding(
              padding: const EdgeInsets.symmetric(vertical: 2),
              child: Text(
                '${e.key} · n ${_fmtValue(calMap['n'])} · '
                'brier cru ${_fmtValue(calMap['brier_raw'])} · '
                'calibrado ${_fmtValue(calMap['brier_calibrated'])}',
                style: Theme.of(context).textTheme.bodySmall,
              ),
            );
          }),
          const Divider(),
        ],
        ...byMap.entries.where((e) {
          final stats = e.value is Map ? e.value as Map : const {};
          final n = (stats['n'] as num?)?.toInt() ?? 0;
          final resolved = (stats['resolved'] as num?)?.toInt() ?? 0;
          return n > 0 || resolved > 0;
        }).map((e) {
          final stats = e.value is Map ? e.value as Map : const {};
          final cal = calibrators[e.key];
          final calMap = cal is Map ? cal : const {};
          return Padding(
            padding: const EdgeInsets.symmetric(vertical: 4),
            child: Text(
              '${e.key} · n ${_fmtValue(stats['n'])} · '
              'resolvidas ${_fmtValue(stats['resolved'])} · '
              'acerto ${_fmtValue(stats['hit_rate'])} · '
              'brier cru ${_fmtValue(calMap['brier_raw'] ?? stats['brier'])} · '
              'calibrado ${_fmtValue(calMap['brier_calibrated'] ?? '—')}',
              style: Theme.of(context).textTheme.bodySmall,
            ),
          );
        }),
        if (curves is Map && curves.isNotEmpty) ...[
          const Divider(),
          Text(
            'Curva de confiabilidade: p médio vs frequência real (diagonal = perfeito). Sem isotonic.',
            style: Theme.of(context).textTheme.labelSmall,
          ),
          ...curves.entries.map((e) {
            final raw = e.value;
            final list = raw is List
                ? raw.whereType<Map>().map((m) => m.map((k, v) => MapEntry(k.toString(), v))).toList()
                : const <Map<String, dynamic>>[];
            return Padding(
              padding: const EdgeInsets.only(top: 8),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(e.key.toString(),
                      style: Theme.of(context).textTheme.labelMedium),
                  ReliabilityChart(buckets: list),
                  Text(
                    list
                        .map((b) =>
                            'n=${_fmtValue(b['n'])} p=${_fmtValue(b['p_mean'])} f=${_fmtValue(b['freq'])}')
                        .join(' · '),
                    style: Theme.of(context).textTheme.labelSmall,
                  ),
                ],
              ),
            );
          }),
        ],
        if (pulse.memory['n'] != null)
          Text(
            'Memória: ${pulse.memory['n']} lições',
            style: Theme.of(context).textTheme.bodySmall,
          ),
        if (pulse.research.isNotEmpty)
          Text(
            'Pesquisa: ${pulse.research}',
            style: Theme.of(context).textTheme.bodySmall,
          ),
      ],
    );
  }
}
