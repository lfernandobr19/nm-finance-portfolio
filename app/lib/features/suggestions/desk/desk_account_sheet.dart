import 'package:flutter/material.dart';

import '../../../core/format.dart';
import 'desk_market_sheet.dart';

Future<void> showDeskAccountSheet(
  BuildContext context, {
  required Map<String, dynamic> portfolio,
  required bool isUs,
  required String moneyCcy,
}) {
  return showModalBottomSheet<void>(
    context: context,
    showDragHandle: true,
    isScrollControlled: true,
    builder: (ctx) {
      final p = portfolio;
      final dayPnl = asNum(p['realized_pnl_day_brl']) ?? 0;
      final upnl = asNum(p['unrealized_pnl_brl']) ?? 0;
      String money(dynamic v) => formatMoney(v, currency: moneyCcy);

      return SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.fromLTRB(16, 0, 16, 24),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Text('Detalhes da conta', style: Theme.of(ctx).textTheme.titleLarge),
              const SizedBox(height: 8),
              Text(
                money(p['equity_brl']),
                style: Theme.of(ctx).textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.w600),
              ),
              Text('Patrimônio a mercado', style: Theme.of(ctx).textTheme.bodySmall),
              const SizedBox(height: 16),
              _Row(label: 'Caixa', value: money(p['cash_brl'])),
              _Row(label: 'Em aberto', value: money(p['market_value_open_brl'] ?? p['invested_open_brl'])),
              _Row(
                label: 'P&L aberto',
                value: money(upnl),
                valueColor: upnl > 0
                    ? Colors.green.shade700
                    : upnl < 0
                        ? Colors.red.shade700
                        : null,
              ),
              _Row(
                label: 'P&L hoje',
                value: money(dayPnl),
                valueColor: dayPnl > 0
                    ? Colors.green.shade700
                    : dayPnl < 0
                        ? Colors.red.shade700
                        : null,
              ),
              _Row(label: 'Posições abertas', value: '${p['open_positions']}'),
              if (isUs) ...[
                const SizedBox(height: 12),
                _NmLimitsBlock(portfolio: p),
              ],
              const SizedBox(height: 16),
              OutlinedButton.icon(
                onPressed: () {
                  Navigator.pop(ctx);
                  showDeskMarketSheet(context, isUs: isUs);
                },
                icon: const Icon(Icons.schedule),
                label: const Text('Horário de pregão'),
              ),
            ],
          ),
        ),
      );
    },
  );
}

class _Row extends StatelessWidget {
  const _Row({required this.label, required this.value, this.valueColor});

  final String label;
  final String value;
  final Color? valueColor;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Text(label, style: Theme.of(context).textTheme.bodyMedium),
          Text(
            value,
            style: Theme.of(context).textTheme.titleSmall?.copyWith(
                  color: valueColor,
                  fontWeight: FontWeight.w600,
                ),
          ),
        ],
      ),
    );
  }
}

class _NmLimitsBlock extends StatelessWidget {
  const _NmLimitsBlock({required this.portfolio});

  final Map<String, dynamic> portfolio;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final tickers = asNum(portfolio['open_hv_dip_tickers'])?.toInt() ?? 0;
    final maxPos = asNum(portfolio['hv_dip_max_positions'])?.toInt() ?? 4;
    final cashPct = asNum(portfolio['cash_pct_of_equity']) ?? 0;
    final floorPct = asNum(portfolio['hv_dip_cash_floor_pct']) ?? 30;
    final tickerPct = asNum(portfolio['hv_dip_max_ticker_pct']) ?? 80;
    final atFloor = cashPct <= floorPct + 0.5;
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: atFloor
            ? Colors.orange.withValues(alpha: 0.12)
            : scheme.surfaceContainerHighest.withValues(alpha: 0.5),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: atFloor ? Colors.orange.shade700 : scheme.outlineVariant),
      ),
      child: Text(
        'NM · $tickers/$maxPos tickers · caixa ${cashPct.toStringAsFixed(0)}% · '
        'piso ${floorPct.toStringAsFixed(0)}% · teto/ticker ${tickerPct.toStringAsFixed(0)}%'
        '${atFloor ? ' · novas compras B/C pausadas' : ''}',
        style: Theme.of(context).textTheme.bodySmall?.copyWith(
              color: atFloor ? Colors.orange.shade900 : scheme.onSurfaceVariant,
            ),
      ),
    );
  }
}
