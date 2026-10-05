import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../core/api_client.dart';
import '../../core/format.dart';
import 'day_trade_signal_detail_page.dart';

class DayTradeStudyPage extends StatefulWidget {
  const DayTradeStudyPage({
    super.key,
    required this.accountId,
    required this.accountName,
  });

  final String accountId;
  final String accountName;

  @override
  State<DayTradeStudyPage> createState() => _DayTradeStudyPageState();
}

class _DayTradeStudyPageState extends State<DayTradeStudyPage> {
  List<dynamic> signals = [];
  Map<String, dynamic>? analytics;
  Map<String, dynamic>? config;
  bool loading = true;
  String? error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      loading = true;
      error = null;
    });
    final api = context.read<ApiClient>();
    try {
      signals = await api.getList('/accounts/${widget.accountId}/day-trade/signals');
    } catch (e) {
      error = '$e';
      signals = [];
    }
    // Best-effort: analytics + config surface the learn loop but must not block
    // the signal list if the backend is older than these endpoints.
    try {
      analytics = await api.getMap('/accounts/${widget.accountId}/day-trade/analytics');
    } catch (_) {
      analytics = null;
    }
    try {
      config = await api.getMap('/accounts/${widget.accountId}/day-trade/config');
    } catch (_) {
      config = null;
    }
    if (mounted) setState(() => loading = false);
  }

  double get _totalPnl {
    var total = 0.0;
    for (final raw in signals) {
      final m = raw as Map<String, dynamic>;
      if (m['status'] == 'closed') {
        total += asNum(m['simulated_pnl_usd']) ?? 0;
      }
    }
    return total;
  }

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final openCount = signals.where((s) => (s as Map)['status'] == 'open').length;
    final pnlColor = _totalPnl >= 0 ? Colors.green.shade700 : Colors.red.shade700;

    return Scaffold(
      appBar: AppBar(
        title: Text('Estudo DT · ${widget.accountName}'),
      ),
      body: RefreshIndicator(
        onRefresh: _load,
        child: loading
            ? ListView(
                children: [
                  const SizedBox(height: 200, child: Center(child: CircularProgressIndicator())),
                ],
              )
            : error != null
                ? ListView(
                    padding: const EdgeInsets.all(16),
                    children: [
                      Text(error!, style: TextStyle(color: scheme.error)),
                      const SizedBox(height: 12),
                      FilledButton(onPressed: _load, child: const Text('Tentar de novo')),
                    ],
                  )
                : ListView(
                    padding: const EdgeInsets.all(12),
                    children: [
                      Card(
                        child: Padding(
                          padding: const EdgeInsets.all(14),
                          child: Row(
                            children: [
                              Expanded(
                                child: Column(
                                  crossAxisAlignment: CrossAxisAlignment.start,
                                  children: [
                                    Text('Hoje', style: Theme.of(context).textTheme.labelMedium),
                                    Text(
                                      '${signals.length} sinais · $openCount abertos',
                                      style: Theme.of(context).textTheme.titleMedium?.copyWith(
                                            fontWeight: FontWeight.w700,
                                          ),
                                    ),
                                  ],
                                ),
                              ),
                              Column(
                                crossAxisAlignment: CrossAxisAlignment.end,
                                children: [
                                  Text('P&L simulado', style: Theme.of(context).textTheme.labelMedium),
                                  Text(
                                    formatMoney(_totalPnl, currency: 'USD'),
                                    style: Theme.of(context).textTheme.titleMedium?.copyWith(
                                          fontWeight: FontWeight.w700,
                                          color: pnlColor,
                                        ),
                                  ),
                                ],
                              ),
                            ],
                          ),
                        ),
                      ),
                      ..._buildLearningCards(context),
                      const SizedBox(height: 8),
                      if (signals.isEmpty)
                        const Padding(
                          padding: EdgeInsets.all(24),
                          child: Text(
                            'Nenhum setup registrado hoje. O observador roda no pregão US (5m).',
                            textAlign: TextAlign.center,
                          ),
                        )
                      else
                        ...signals.map((raw) {
                          final s = raw as Map<String, dynamic>;
                          final status = s['status'] as String? ?? '';
                          final pnl = asNum(s['simulated_pnl_usd']);
                          return Card(
                            child: ListTile(
                              title: Text('${s['ticker']} · ${_ruleLabel(s['rule_id'] as String?)}'),
                              subtitle: Text(
                                '${_sideLabel(s['side'] as String?)} · ${_statusLabel(status)} · ${formatPrice(s['entry_price'])}',
                              ),
                              trailing: pnl != null
                                  ? Text(
                                      formatMoney(pnl, currency: 'USD'),
                                      style: TextStyle(
                                        fontWeight: FontWeight.w600,
                                        color: pnl >= 0 ? Colors.green.shade700 : Colors.red.shade700,
                                      ),
                                    )
                                  : const Icon(Icons.chevron_right),
                              onTap: () async {
                                await Navigator.of(context).push(
                                  MaterialPageRoute(
                                    builder: (_) => DayTradeSignalDetailPage(
                                      accountId: widget.accountId,
                                      signalId: s['id'] as String,
                                      initial: s,
                                    ),
                                  ),
                                );
                                await _load();
                              },
                            ),
                          );
                        }),
                    ],
                  ),
      ),
    );
  }

  Map<String, dynamic>? _ruleStats(String ruleId) {
    final a = analytics;
    if (a == null) return null;
    final byRule = a['by_rule'] as List<dynamic>?;
    if (byRule == null) return null;
    for (final raw in byRule) {
      final m = raw as Map<String, dynamic>;
      if (m['key'] == ruleId) return m;
    }
    return null;
  }

  List<Widget> _buildLearningCards(BuildContext context) {
    final cards = <Widget>[];
    final scheme = Theme.of(context).colorScheme;
    final labelStyle = Theme.of(context).textTheme.labelMedium;
    final titleStyle = Theme.of(context).textTheme.titleSmall?.copyWith(
          fontWeight: FontWeight.w700,
        );

    if (analytics != null) {
      final total = asNum(analytics!['total_closed']) ?? 0;
      final rows = <Widget>[];
      for (final ruleId in const ['opening_range_break', 'vwap_reclaim']) {
        final s = _ruleStats(ruleId);
        if (s == null) continue;
        final n = s['n'] as int? ?? 0;
        final wr = asNum(s['win_rate']) ?? 0;
        final exp = s['expectancy_r'];
        rows.add(Padding(
          padding: const EdgeInsets.symmetric(vertical: 4),
          child: Row(
            children: [
              Expanded(
                child: Text(
                  _ruleLabel(ruleId),
                  style: titleStyle,
                ),
              ),
              Text(
                '$n fechados · WR ${wr.toStringAsFixed(0)}% · exp ${exp == null ? '—' : '${(exp as num).toStringAsFixed(2)}R'}',
                style: labelStyle,
              ),
            ],
          ),
        ));
      }
      cards.add(Card(
        child: Padding(
          padding: const EdgeInsets.all(14),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text('Aprendizado · performance', style: titleStyle),
              const SizedBox(height: 4),
              Text('$total sinais fechados (amostra)', style: labelStyle),
              if (rows.isEmpty)
                Padding(
                  padding: const EdgeInsets.only(top: 6),
                  child: Text(
                    'Sem amostra fechada ainda. O bot coleta até atingir o mínimo antes de re-tunar.',
                    style: labelStyle?.copyWith(color: scheme.onSurfaceVariant),
                  ),
                )
              else
                ...rows,
            ],
          ),
        ),
      ));
    }

    if (config != null) {
      final version = config!['version'];
      final origin = config!['origin'] as String? ?? 'manual';
      final params = config!['params'] as Map<String, dynamic>? ?? {};
      final validation = config!['validation'] as Map<String, dynamic>? ?? {};
      final paramLines = <String>[];
      params.forEach((ruleId, p) {
        final m = p as Map<String, dynamic>;
        final items = m.entries.map((e) => '${e.key}=${e.value}').join(', ');
        paramLines.add('${_ruleLabel(ruleId)}: $items');
      });
      final valText = validation.isEmpty
          ? ''
          : validation.entries
              .map((e) => '${e.key}: ${e.value}')
              .join('\n');
      cards.add(Card(
        child: Padding(
          padding: const EdgeInsets.all(14),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Expanded(
                    child: Text(
                      'Parâmetros ativos · v$version',
                      style: titleStyle,
                    ),
                  ),
                  Text(
                    origin == 'auto' ? 'auto-tuning' : 'manual',
                    style: labelStyle?.copyWith(
                      color: origin == 'auto' ? Colors.green.shade700 : scheme.onSurfaceVariant,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 6),
              ...paramLines.map(
                (l) => Padding(
                  padding: const EdgeInsets.symmetric(vertical: 2),
                  child: Text(l, style: labelStyle),
                ),
              ),
              if (valText.isNotEmpty) ...[
                const SizedBox(height: 6),
                Text('Validação (walk-forward):', style: labelStyle),
                Text(valText, style: labelStyle),
              ],
            ],
          ),
        ),
      ));
    }

    return cards;
  }

  String _ruleLabel(String? id) {
    switch (id) {
      case 'opening_range_break':
        return 'Opening range';
      case 'vwap_reclaim':
        return 'VWAP reclaim';
      default:
        return id ?? '—';
    }
  }

  String _sideLabel(String? side) => side == 'short' ? 'Short' : 'Long';

  String _statusLabel(String status) {
    switch (status) {
      case 'open':
        return 'Aberto';
      case 'closed':
        return 'Fechado';
      case 'expired':
        return 'Expirado';
      default:
        return status;
    }
  }
}
