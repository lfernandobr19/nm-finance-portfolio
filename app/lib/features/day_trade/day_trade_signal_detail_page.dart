import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../core/api_client.dart';
import '../../core/candlestick_chart.dart';
import '../../core/format.dart';
import '../../core/ohlc_chart.dart';

class DayTradeSignalDetailPage extends StatefulWidget {
  const DayTradeSignalDetailPage({
    super.key,
    required this.accountId,
    required this.signalId,
    this.initial,
  });

  final String accountId;
  final String signalId;
  final Map<String, dynamic>? initial;

  @override
  State<DayTradeSignalDetailPage> createState() => _DayTradeSignalDetailPageState();
}

class _DayTradeSignalDetailPageState extends State<DayTradeSignalDetailPage> {
  Map<String, dynamic>? signal;
  List<OhlcBar> bars = [];
  bool loading = true;

  @override
  void initState() {
    super.initState();
    signal = widget.initial;
    _load();
  }

  Future<void> _load() async {
    setState(() => loading = true);
    final api = context.read<ApiClient>();
    try {
      signal = await api.getMap(
        '/accounts/${widget.accountId}/day-trade/signals/${widget.signalId}',
      );
      final ticker = signal?['ticker'] as String? ?? '';
      if (ticker.isNotEmpty) {
        final rawBars = await api.getList(
          '/accounts/${widget.accountId}/tickers/$ticker/bars/intraday',
          {'timeframe': '5m'},
        );
        bars = rawBars.map(OhlcBar.fromJson).whereType<OhlcBar>().toList();
      }
    } catch (_) {
      // keep initial signal if detail fetch fails
    }
    if (mounted) setState(() => loading = false);
  }

  @override
  Widget build(BuildContext context) {
    final s = signal;
    if (loading && s == null) {
      return const Scaffold(body: Center(child: CircularProgressIndicator()));
    }
    if (s == null) {
      return Scaffold(
        appBar: AppBar(),
        body: const Center(child: Text('Sinal não encontrado')),
      );
    }

    final entry = asNum(s['entry_price']);
    final stop = asNum(s['stop_price']);
    final target = asNum(s['target_price']);
    final metrics = (s['metrics'] as Map<String, dynamic>?) ?? {};

    return Scaffold(
      appBar: AppBar(title: Text('${s['ticker']} · ${s['rule_id']}')),
      body: ListView(
        padding: const EdgeInsets.all(12),
        children: [
          Card(
            child: Padding(
              padding: const EdgeInsets.all(14),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    '${s['side'] == 'short' ? 'Short' : 'Long'} · ${s['status']}',
                    style: Theme.of(context).textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w700),
                  ),
                  const SizedBox(height: 8),
                  Wrap(
                    spacing: 12,
                    runSpacing: 6,
                    children: [
                      Text('Entrada ${formatPrice(entry)}'),
                      Text('Stop ${formatPrice(stop)}'),
                      Text('Alvo ${formatPrice(target)}'),
                      if (s['simulated_pnl_usd'] != null)
                        Text('P&L ${formatMoney(s['simulated_pnl_usd'], currency: 'USD')}'),
                    ],
                  ),
                  if (metrics.isNotEmpty) ...[
                    const SizedBox(height: 10),
                    Text('Métricas', style: Theme.of(context).textTheme.labelLarge),
                    const SizedBox(height: 4),
                    ...metrics.entries.map(
                      (e) => Text('${e.key}: ${e.value}', style: Theme.of(context).textTheme.bodySmall),
                    ),
                  ],
                ],
              ),
            ),
          ),
          const SizedBox(height: 12),
          Text('Gráfico 5m', style: Theme.of(context).textTheme.titleSmall),
          const SizedBox(height: 8),
          InteractiveCandlestickChart(
            bars: bars,
            entry: entry,
            stop: stop,
            target: target,
            showStopTarget: true,
            height: 220,
          ),
        ],
      ),
    );
  }
}
