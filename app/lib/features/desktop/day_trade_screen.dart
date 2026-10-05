import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../app/selected_account.dart';
import '../../core/api_client.dart';
import '../../core/candlestick_chart.dart';
import '../../core/format.dart';
import '../../core/ohlc_chart.dart';
import '../../data/models/day_trade.dart';
import '../../data/repositories/day_trade_repository.dart';
import 'master_detail.dart';

/// Desktop Day Trade: master list of signals + detail with OHLC intraday chart.
class DayTradeScreen extends StatefulWidget {
  const DayTradeScreen({super.key});

  @override
  State<DayTradeScreen> createState() => _DayTradeScreenState();
}

class _DayTradeScreenState extends State<DayTradeScreen> {
  List<DayTradeSignal> _signals = [];
  DayTradeSignal? _selected;
  bool _loading = false;
  String? _error;
  String _accountId = '';

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final accountId = context.watch<SelectedAccount>().accountId;
    if (_accountId != accountId) {
      _accountId = accountId;
      _selected = null;
      _reload();
    }
  }

  Future<void> _reload() async {
    if (_accountId.isEmpty) {
      setState(() {
        _signals = [];
        _selected = null;
      });
      return;
    }
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final repo = DayTradeRepository(context.read<ApiClient>());
      _signals = await repo.listSignals(_accountId);
      _signals.sort((a, b) => b.createdAt.compareTo(a.createdAt));
    } catch (e) {
      _error = formatApiError(e);
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  double get _totalPnl {
    var total = 0.0;
    for (final s in _signals) {
      if (s.status == 'closed') total += s.simulatedPnlUsd ?? 0;
    }
    return total;
  }

  @override
  Widget build(BuildContext context) {
    final account = context.watch<SelectedAccount>().current;
    final openCount = _signals.where((s) => s.status == 'open').length;
    final pnlColor =
        _totalPnl >= 0 ? Colors.green.shade700 : Colors.red.shade700;
    return Scaffold(
      appBar: AppBar(
        title:
            Text(account == null ? 'Day Trade' : 'Day Trade · ${account.name}'),
        actions: [
          if (account != null)
            IconButton(onPressed: _reload, icon: const Icon(Icons.refresh)),
        ],
      ),
      body: account == null
          ? const PaneEmpty(
              message: 'Selecione uma conta na aba Contas.',
              icon: Icons.candlestick_chart_outlined,
            )
          : _loading
              ? const PaneLoading()
              : _error != null
                  ? PaneError(message: _error!, onRetry: _reload)
                  : Column(
                      children: [
                        _HeaderBar(
                          signalCount: _signals.length,
                          openCount: openCount,
                          totalPnl: _totalPnl,
                          pnlColor: pnlColor,
                        ),
                        const Divider(height: 1),
                        Expanded(
                          child: MasterDetail(
                            master: _SignalList(
                              signals: _signals,
                              selectedId: _selected?.id,
                              onSelect: (s) => setState(() => _selected = s),
                            ),
                            detail: _selected == null
                                ? const PaneEmpty(
                                    message: 'Selecione um sinal.')
                                : _SignalPane(
                                    accountId: _accountId,
                                    signal: _selected!,
                                  ),
                          ),
                        ),
                      ],
                    ),
    );
  }
}

class _HeaderBar extends StatelessWidget {
  const _HeaderBar({
    required this.signalCount,
    required this.openCount,
    required this.totalPnl,
    required this.pnlColor,
  });

  final int signalCount;
  final int openCount;
  final double totalPnl;
  final Color pnlColor;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 12),
      child: Row(
        children: [
          Expanded(
            child: Text(
              '$signalCount sinais · $openCount abertos',
              style: Theme.of(context)
                  .textTheme
                  .titleMedium
                  ?.copyWith(fontWeight: FontWeight.w700),
            ),
          ),
          Text(
            'P&L simulado ${formatUsd(totalPnl)}',
            style: Theme.of(context)
                .textTheme
                .titleMedium
                ?.copyWith(fontWeight: FontWeight.w700, color: pnlColor),
          ),
        ],
      ),
    );
  }
}

class _SignalList extends StatelessWidget {
  const _SignalList({
    required this.signals,
    required this.selectedId,
    required this.onSelect,
  });

  final List<DayTradeSignal> signals;
  final String? selectedId;
  final void Function(DayTradeSignal) onSelect;

  @override
  Widget build(BuildContext context) {
    if (signals.isEmpty) {
      return const PaneEmpty(
        message:
            'Nenhum setup registrado hoje.\nO observador roda no pregão US (5m).',
        icon: Icons.candlestick_chart_outlined,
      );
    }
    return ListView.separated(
      itemCount: signals.length,
      separatorBuilder: (_, __) => const Divider(height: 1),
      itemBuilder: (context, i) {
        final s = signals[i];
        final pnl = s.simulatedPnlUsd;
        return ListTile(
          selected: s.id == selectedId,
          dense: true,
          title: Text('${s.ticker} · ${_ruleLabel(s.ruleId)}'),
          subtitle: Text(
            '${s.side == 'short' ? 'Short' : 'Long'} · ${s.status} · ${formatPrice(s.entryPrice)}',
          ),
          trailing: pnl != null
              ? Text(
                  formatUsd(pnl),
                  style: TextStyle(
                    fontWeight: FontWeight.w600,
                    color:
                        pnl >= 0 ? Colors.green.shade700 : Colors.red.shade700,
                  ),
                )
              : const Icon(Icons.chevron_right, size: 16),
          onTap: () => onSelect(s),
        );
      },
    );
  }

  static String _ruleLabel(String? id) {
    switch (id) {
      case 'opening_range_break':
        return 'Opening range';
      case 'vwap_reclaim':
        return 'VWAP reclaim';
      default:
        return id ?? '—';
    }
  }
}

class _SignalPane extends StatefulWidget {
  const _SignalPane({required this.accountId, required this.signal});

  final String accountId;
  final DayTradeSignal signal;

  @override
  State<_SignalPane> createState() => _SignalPaneState();
}

class _SignalPaneState extends State<_SignalPane> {
  List<OhlcBar> _bars = [];
  bool _loadingBars = true;

  @override
  void initState() {
    super.initState();
    _loadBars();
  }

  @override
  void didUpdateWidget(covariant _SignalPane oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.signal.ticker != widget.signal.ticker) {
      _loadBars();
    }
  }

  Future<void> _loadBars() async {
    setState(() => _loadingBars = true);
    try {
      final repo = DayTradeRepository(context.read<ApiClient>());
      final bars =
          await repo.intradayBars(widget.accountId, widget.signal.ticker);
      _bars = bars
          .map((b) => OhlcBar(
                date: b.ts,
                open: b.open,
                high: b.high,
                low: b.low,
                close: b.close,
              ))
          .toList();
    } catch (_) {
      _bars = [];
    } finally {
      if (mounted) setState(() => _loadingBars = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final s = widget.signal;
    return ListView(
      padding: const EdgeInsets.all(20),
      children: [
        Text(
          s.ticker,
          style: Theme.of(context).textTheme.headlineMedium,
        ),
        const SizedBox(height: 8),
        _kv(context, 'Regra', _ruleLabel(s.ruleId)),
        _kv(context, 'Lado', s.side == 'short' ? 'Short' : 'Long'),
        _kv(context, 'Status', s.status),
        _kv(context, 'Entrada', formatPrice(s.entryPrice)),
        _kv(context, 'Stop', formatPrice(s.stopPrice)),
        _kv(context, 'Alvo', formatPrice(s.targetPrice)),
        if (s.simulatedPnlUsd != null)
          _kv(context, 'P&L simulado', formatUsd(s.simulatedPnlUsd)),
        const SizedBox(height: 16),
        Text('Intraday (5m)', style: Theme.of(context).textTheme.titleMedium),
        const SizedBox(height: 8),
        if (_loadingBars)
          const SizedBox(
            height: 200,
            child: Center(child: CircularProgressIndicator()),
          )
        else
          InteractiveCandlestickChart(
            bars: _bars,
            entry: s.entryPrice,
            stop: s.stopPrice,
            target: s.targetPrice,
            showStopTarget: true,
            height: 260,
          ),
      ],
    );
  }

  static String _ruleLabel(String? id) {
    switch (id) {
      case 'opening_range_break':
        return 'Opening range';
      case 'vwap_reclaim':
        return 'VWAP reclaim';
      default:
        return id ?? '—';
    }
  }

  Widget _kv(BuildContext context, String label, String value) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 3),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 130,
            child: Text(label, style: Theme.of(context).textTheme.labelMedium),
          ),
          Expanded(child: Text(value)),
        ],
      ),
    );
  }
}
