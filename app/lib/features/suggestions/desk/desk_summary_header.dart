import 'package:flutter/material.dart';

import '../../../core/format.dart';
import '../../../core/market_hours.dart';

/// Compact header shown in SliverAppBar flexible / collapsed title area.
class DeskSummaryHeader extends StatelessWidget {
  const DeskSummaryHeader({
    super.key,
    required this.portfolio,
    required this.isUs,
    required this.moneyCcy,
    required this.openCount,
    required this.waitingCount,
    required this.onTapSummary,
    required this.onTapMarket,
    this.onTapDayTrade,
    this.deskMode,
    this.onDeskChanged,
    this.compact = false,
  });

  final Map<String, dynamic>? portfolio;
  final bool isUs;
  final String moneyCcy;
  final int openCount;
  final int waitingCount;
  final VoidCallback onTapSummary;
  final VoidCallback onTapMarket;
  final VoidCallback? onTapDayTrade;
  final String? deskMode;
  final ValueChanged<String>? onDeskChanged;
  final bool compact;

  String _money(dynamic v) => formatMoney(v, currency: moneyCcy);

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final p = portfolio;
    final activeMarket = MarketHours.forMarket(isUs ? 'us' : 'br');
    final dayPnl = p != null ? (asNum(p['realized_pnl_day_brl']) ?? 0) : 0.0;
    final dayColor = dayPnl > 0
        ? Colors.green.shade700
        : dayPnl < 0
            ? Colors.red.shade700
            : scheme.onSurfaceVariant;

    final equityStyle = compact
        ? Theme.of(context).textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w700)
        : Theme.of(context).textTheme.titleLarge?.copyWith(fontWeight: FontWeight.w700);
    final chipStyle = Theme.of(context).textTheme.labelSmall?.copyWith(fontSize: 11);

    return Material(
      color: Colors.transparent,
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          if (isUs && onTapDayTrade != null)
            Padding(
              padding: const EdgeInsets.only(bottom: 4),
              child: Align(
                alignment: Alignment.centerLeft,
                child: ActionChip(
                  visualDensity: VisualDensity.compact,
                  label: const Text('Estudo DT', style: TextStyle(fontSize: 12)),
                  avatar: const Icon(Icons.insights_outlined, size: 16),
                  onPressed: onTapDayTrade,
                ),
              ),
            ),
          if (!isUs && deskMode != null && onDeskChanged != null)
            Padding(
              padding: const EdgeInsets.only(bottom: 4),
              child: SegmentedButton<String>(
                style: ButtonStyle(
                  visualDensity: VisualDensity.compact,
                  tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                ),
                segments: const [
                  ButtonSegment(value: 'swing', label: Text('Swing', style: TextStyle(fontSize: 12))),
                  ButtonSegment(value: 'income', label: Text('Income', style: TextStyle(fontSize: 12))),
                ],
                selected: {deskMode!},
                onSelectionChanged: (s) => onDeskChanged!(s.first),
              ),
            ),
          Row(
            crossAxisAlignment: CrossAxisAlignment.center,
            children: [
              Expanded(
                child: InkWell(
                  onTap: p != null ? onTapSummary : null,
                  borderRadius: BorderRadius.circular(8),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Text(
                        p != null ? _money(p['equity_brl']) : '—',
                        style: equityStyle,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                      ),
                      const SizedBox(height: 2),
                      Wrap(
                        spacing: 6,
                        runSpacing: 0,
                        children: [
                          if (p != null)
                            Text('Caixa ${_money(p['cash_brl'])}', style: chipStyle),
                          Text(
                            'P&L ${_money(dayPnl)}',
                            style: chipStyle?.copyWith(color: dayColor),
                          ),
                          Text('$openCount abr · $waitingCount fila', style: chipStyle),
                        ],
                      ),
                    ],
                  ),
                ),
              ),
              InkWell(
                onTap: onTapMarket,
                borderRadius: BorderRadius.circular(20),
                child: Container(
                  padding: EdgeInsets.symmetric(
                    horizontal: compact ? 8 : 10,
                    vertical: compact ? 4 : 6,
                  ),
                    decoration: BoxDecoration(
                      color: activeMarket.isOpen
                          ? Colors.green.withValues(alpha: 0.15)
                          : Colors.orange.withValues(alpha: 0.12),
                      borderRadius: BorderRadius.circular(20),
                      border: Border.all(
                        color: activeMarket.isOpen
                            ? Colors.green.shade700.withValues(alpha: 0.4)
                            : Colors.orange.shade700.withValues(alpha: 0.4),
                      ),
                    ),
                    child: Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Icon(
                          Icons.schedule,
                          size: 14,
                          color: activeMarket.isOpen ? Colors.green.shade700 : Colors.orange.shade900,
                        ),
                        const SizedBox(width: 4),
                        Text(
                          isUs ? 'Nasdaq' : 'B3',
                          style: Theme.of(context).textTheme.labelSmall?.copyWith(
                                fontWeight: FontWeight.w600,
                              ),
                        ),
                        const SizedBox(width: 4),
                        Text(
                          activeMarket.statusLabel,
                          style: Theme.of(context).textTheme.labelSmall?.copyWith(
                                color: activeMarket.isOpen
                                    ? Colors.green.shade700
                                    : Colors.orange.shade900,
                                fontWeight: FontWeight.w600,
                              ),
                        ),
                      ],
                    ),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

/// Tab label with optional count badge.
class DeskTabLabel extends StatelessWidget {
  const DeskTabLabel({super.key, required this.label, this.count});

  final String label;
  final int? count;

  @override
  Widget build(BuildContext context) {
    if (count == null || count! <= 0) return Tab(text: label);
    return Tab(
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(label),
          const SizedBox(width: 4),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 1),
            decoration: BoxDecoration(
              color: Theme.of(context).colorScheme.primaryContainer,
              borderRadius: BorderRadius.circular(10),
            ),
            child: Text(
              '$count',
              style: Theme.of(context).textTheme.labelSmall?.copyWith(
                    fontWeight: FontWeight.w700,
                    fontSize: 10,
                  ),
            ),
          ),
        ],
      ),
    );
  }
}
