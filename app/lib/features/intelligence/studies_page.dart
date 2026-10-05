import 'dart:async';

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../core/api_client.dart';
import '../../core/format.dart';
import '../../data/models/intelligence_pulse.dart';
import '../../data/repositories/intelligence_repository.dart';

/// Tela mobile de Estudos Ativos: acompanha a progressão do aprendizado
/// (n amostras vs piso 30 por loop) e os estudos de padrão/tendência/chance.
class StudiesPage extends StatefulWidget {
  const StudiesPage({super.key});

  @override
  State<StudiesPage> createState() => _StudiesPageState();
}

class _StudiesPageState extends State<StudiesPage> {
  IntelligencePulse? _data;
  List<Map<String, dynamic>> _evolution = const [];
  Object? _error;
  bool _loading = true;
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    _load();
    _timer = Timer.periodic(
      const Duration(seconds: 60),
      (_) => _load(silent: true),
    );
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Future<void> _load({bool silent = false}) async {
    if (!silent) {
      setState(() {
        _loading = true;
        _error = null;
      });
    }
    try {
      final repo = IntelligenceRepository(context.read<ApiClient>());
      final pulse = await repo.getPulse();
      List<Map<String, dynamic>> evo = const [];
      try {
        evo = await repo.getEvolution(limit: 8);
      } catch (_) {}
      if (!mounted) return;
      setState(() {
        _data = pulse;
        _evolution = evo;
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
    return Scaffold(
      appBar: AppBar(title: const Text('Estudos Ativos')),
      body: RefreshIndicator(
        onRefresh: () => _load(),
        child: _buildBody(),
      ),
    );
  }

  Widget _buildBody() {
    if (_loading) {
      return const Center(child: CircularProgressIndicator());
    }
    if (_error != null) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Text(
            formatApiError(_error!),
            textAlign: TextAlign.center,
          ),
        ),
      );
    }
    return StudiesBody(
      pulse: _data ?? IntelligencePulse.unavailable(),
      evolution: _evolution,
    );
  }
}

/// Presentational body (testável sem [ApiClient]).
class StudiesBody extends StatelessWidget {
  const StudiesBody({super.key, required this.pulse, this.evolution = const []});

  final IntelligencePulse pulse;
  final List<Map<String, dynamic>> evolution;

  static const _learnFloor = 30;

  static const _learnLabels = {
    'hv_dip': 'High-Vol Dip',
    'desk': 'Desk (orçamento)',
    'day_trade': 'Day Trade',
  };

  String _statusLabel(String? status) {
    switch (status) {
      case 'applied':
        return 'aplicado';
      case 'skipped':
        return 'pulado';
      case 'disabled':
        return 'desligado';
      case 'no_data':
        return 'sem dados';
      case 'insufficient_data':
        return 'dados insuficientes';
      default:
        return '—';
    }
  }

  double? _pTarget(StudyResult r) {
    // The desk's ruler: P(close above entry after the horizon) — "does it
    // appreciate again in ~2 weeks?" — not the tighter target-before-stop ratio.
    if (r.n == 0 || r.pRecover == null) return null;
    return r.pRecover;
  }

  @override
  Widget build(BuildContext context) {
    final studies = pulse.studies;

    final hasLearn =
        pulse.learn.isNotEmpty || pulse.nClosedUsd > 0 || pulse.available;
    final hasStudies =
        studies != null && (studies.queries.isNotEmpty || studies.results.isNotEmpty);

    if (!pulse.available && studies == null && !hasLearn) {
      return _message(
        context,
        'Nenhum estudo ativo ainda. O worker calcula analogias em tempo real.',
        Icons.query_stats,
      );
    }

    return ListView(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
      children: [
        if (studies?.ts != null) ...[
          Text(
            'Atualizado ${formatRefreshedAt(studies!.ts)}',
            style: Theme.of(context).textTheme.labelSmall?.copyWith(
                color: Theme.of(context).colorScheme.onSurfaceVariant),
          ),
          const SizedBox(height: 8),
        ],

        // ---- Progressão do aprendizado (evidência vs piso) ----
        if (evolution.isNotEmpty) ...[
          _sectionTitle(context, 'O que mudou'),
          const SizedBox(height: 4),
          for (final e in evolution.take(8))
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 2),
              child: Text(
                '${e['kind'] ?? ''} · ${e['title'] ?? ''}',
                style: Theme.of(context).textTheme.bodySmall,
              ),
            ),
          const SizedBox(height: 12),
        ],
        _sectionTitle(context, 'Progressão do aprendizado'),
        const SizedBox(height: 4),
        for (final kind in ['hv_dip', 'desk', 'day_trade']) ...[
          _LearnProgress(
            label: _learnLabels[kind] ?? kind,
            learn: pulse.learn[kind],
            floor: _learnFloor,
            statusLabel: _statusLabel(pulse.learn[kind]?.status),
          ),
        ],
        if (pulse.nClosedUsd > 0)
          Padding(
            padding: const EdgeInsets.only(top: 4),
            child: Text(
              '${pulse.nClosedUsd} posições USD fechadas no histórico',
              style: Theme.of(context).textTheme.bodySmall?.copyWith(
                  color: Theme.of(context).colorScheme.onSurfaceVariant),
            ),
          ),
        const Divider(height: 24),

        // ---- Estudos (padrão / tendência / chance) ----
        _sectionTitle(context, 'Estudos'),
        const SizedBox(height: 4),
        if (!hasStudies)
          _message(context,
              'Nenhum estudo calculado ainda. O worker grava em tempo real.',
              Icons.hourglass_empty)
        else
          for (final q in studies.queries) ...[
            _StudyCardMobile(
              query: q,
              results: (studies.results)
                  .where((r) => r.queryId == q.id)
                  .toList(),
              decision: _decisionFor(studies, q),
              pTarget: _pTargetOf(studies, q),
            ),
            const Divider(height: 12),
          ],

        // ---- Insights fundamentados (LLM) ----
        if ((studies?.insights ?? const []).isNotEmpty) ...[
          _sectionTitle(context, 'Insights'),
          const SizedBox(height: 4),
          for (final ins in studies!.insights)
            _InsightCard(insight: ins),
        ],
      ],
    );
  }

  Map<String, dynamic>? _decisionFor(StudiesSnapshot s, StudyQuery q) {
    for (final d in s.decisions) {
      if (d['key'] == '${q.channel}:${q.fingerprint}') return d;
    }
    return null;
  }

  double? _pTargetOf(StudiesSnapshot s, StudyQuery q) {
    for (final r in s.results) {
      if (r.queryId == q.id && r.ticker == 'UNIVERSE') return _pTarget(r);
    }
    return null;
  }

  Widget _sectionTitle(BuildContext context, String title) {
    return Text(
      title,
      style: Theme.of(context)
          .textTheme
          .titleMedium
          ?.copyWith(fontWeight: FontWeight.w700),
    );
  }

  Widget _message(BuildContext context, String msg, IconData icon) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 24, horizontal: 8),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 40, color: Theme.of(context).colorScheme.outline),
          const SizedBox(height: 12),
          Text(
            msg,
            textAlign: TextAlign.center,
            style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                color: Theme.of(context).colorScheme.onSurfaceVariant),
          ),
        ],
      ),
    );
  }
}

class _LearnProgress extends StatelessWidget {
  const _LearnProgress({
    required this.label,
    required this.learn,
    required this.floor,
    required this.statusLabel,
  });

  final String label;
  final LearnStatus? learn;
  final int floor;
  final String statusLabel;

  @override
  Widget build(BuildContext context) {
    final n = learn?.n;
    final progress = (n == null || floor <= 0) ? 0.0 : (n / floor).clamp(0.0, 1.0);
    final color = progress >= 1.0
        ? Colors.green.shade700
        : progress >= 0.5
            ? Colors.orange.shade800
            : Colors.blueGrey.shade500;

    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(label,
                    style: Theme.of(context)
                        .textTheme
                        .bodyMedium
                        ?.copyWith(fontWeight: FontWeight.w600)),
              ),
              Text(
                n == null ? 'n=—' : 'n=$n/$floor · $statusLabel',
                style: Theme.of(context).textTheme.labelSmall?.copyWith(
                    color: Theme.of(context).colorScheme.onSurfaceVariant),
              ),
            ],
          ),
          const SizedBox(height: 4),
          ClipRRect(
            borderRadius: BorderRadius.circular(4),
            child: LinearProgressIndicator(
              value: progress,
              minHeight: 8,
              color: color,
              backgroundColor:
                  Theme.of(context).colorScheme.surfaceContainerHighest,
            ),
          ),
        ],
      ),
    );
  }
}

class _StudyCardMobile extends StatelessWidget {
  const _StudyCardMobile({
    required this.query,
    required this.results,
    required this.decision,
    required this.pTarget,
  });

  final StudyQuery query;
  final List<StudyResult> results;
  final Map<String, dynamic>? decision;
  final double? pTarget;

  @override
  Widget build(BuildContext context) {
    final universe = results.where((r) => r.ticker == 'UNIVERSE').firstOrNull;
    final perTicker =
        results.where((r) => r.ticker != 'UNIVERSE').toList();

    final action = decision?['action'] as String?;
    final reason = decision?['reason'] as String?;

    final badges = <Widget>[];
    if (action == 'force_review' || action == 'suppress') {
      badges.add(_badge(context, 'desk bloqueou', Colors.red.shade700));
    } else if (action == 'skipped') {
      badges.add(_badge(context, 'skipped', Colors.blueGrey.shade600));
    } else if (action == 'hold') {
      badges.add(_badge(context, 'observando', Colors.green.shade700));
    }

    final p = pTarget;
    final color = p == null
        ? Colors.blueGrey.shade600
        : p >= 0.5
            ? Colors.green.shade700
            : Colors.orange.shade800;

    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
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
                      .bodyMedium
                      ?.copyWith(fontWeight: FontWeight.w700),
                ),
              ),
              ...badges,
            ],
          ),
          const SizedBox(height: 4),
          Text(
            universe == null
                ? 'n=0 · sem analogias suficientes'
                : 'n=${universe.n} · P(valorizar ~2 sem) ${formatPct((p ?? 0) * 100)}'
                    ' · tendência ${formatPct((universe.trendUp ?? 0) * 100)}',
            style: Theme.of(context).textTheme.bodySmall?.copyWith(
                fontWeight: FontWeight.w600, color: color),
          ),
          if (reason != null && reason.isNotEmpty) ...[
            const SizedBox(height: 2),
            Text(reason,
                style: Theme.of(context).textTheme.labelSmall?.copyWith(
                    color: Theme.of(context).colorScheme.onSurfaceVariant)),
          ],
          if (perTicker.isNotEmpty) ...[
            const SizedBox(height: 6),
            for (final r in perTicker.take(5))
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 2),
                child: Text(
                  '${r.ticker} · n=${r.n}'
                  '${r.vsUniverse == null ? '' : ' · vs universo ${r.vsUniverse! >= 0 ? '+' : ''}${formatRatio(r.vsUniverse! * 100)}pp'}',
                  style: Theme.of(context).textTheme.labelSmall?.copyWith(
                      color: Theme.of(context).colorScheme.onSurfaceVariant),
                ),
              ),
          ],
        ],
      ),
    );
  }

  Widget _badge(BuildContext context, String label, Color color) {
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
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                _Badge(label: insight.kind, color: color),
                if (insight.ticker.isNotEmpty && insight.ticker != 'UNIVERSE') ...[
                  const SizedBox(width: 6),
                  _Badge(label: insight.ticker, color: Colors.blueGrey.shade600),
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
                  .bodyMedium
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
