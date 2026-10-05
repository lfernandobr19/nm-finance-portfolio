import 'package:flutter/material.dart';

import '../../../core/format.dart';
import '../../../data/models/position.dart';

/// Lista compacta de posições abertas com P&L% e badge de alerta de preço.
class OpenPositionsList extends StatelessWidget {
  const OpenPositionsList({super.key, required this.positions, required this.currency});

  final List<Position> positions;
  final String currency;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final ccy = currency.toUpperCase();

    return Card(
      margin: EdgeInsets.zero,
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              'Posições abertas',
              style:
                  theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w700),
            ),
            const SizedBox(height: 12),
            if (positions.isEmpty)
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 8),
                child: Text(
                  'Nenhuma posição aberta.',
                  style: theme.textTheme.bodySmall,
                ),
              )
            else
              ...positions.map((p) => _row(context, p, ccy)),
          ],
        ),
      ),
    );
  }

  Widget _row(BuildContext context, Position p, String ccy) {
    final theme = Theme.of(context);
    final pnlPct = p.unrealizedPnlPct;
    final pnlColor = pnlPct == null
        ? theme.colorScheme.onSurfaceVariant
        : pnlPct >= 0
            ? Colors.green.shade700
            : Colors.red.shade700;

    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Row(
        children: [
          SizedBox(
            width: 72,
            child: Text(
              p.ticker,
              style: theme.textTheme.bodyMedium?.copyWith(fontWeight: FontWeight.w700),
              overflow: TextOverflow.ellipsis,
            ),
          ),
          Expanded(
            child: Text(
              '${formatQty(p.quantity)} @ ${formatPrice(p.entryPrice)}'
              '${p.markPrice != null ? ' → ${formatPrice(p.markPrice)}' : ''}',
              style: theme.textTheme.bodySmall
                  ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
              overflow: TextOverflow.ellipsis,
            ),
          ),
          const SizedBox(width: 8),
          Text(
            pnlPct == null ? '—' : formatPct(pnlPct),
            style: theme.textTheme.bodyMedium
                ?.copyWith(fontWeight: FontWeight.w700, color: pnlColor),
          ),
          if (p.priceAlert != null && p.priceAlert!.isNotEmpty) ...[
            const SizedBox(width: 8),
            _alertBadge(theme, p.priceAlert!),
          ],
        ],
      ),
    );
  }

  Widget _alertBadge(ThemeData theme, String alert) {
    final (label, color) = switch (alert) {
      'target' => ('Alvo', Colors.green.shade700),
      'stop' => ('Stop', Colors.red.shade700),
      'recovery' => ('Recuperação', Colors.orange.shade800),
      'trailing' => ('Trailing', Colors.blue.shade700),
      _ => (alert, Colors.grey.shade700),
    };
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(6),
      ),
      child: Text(
        label,
        style: theme.textTheme.labelSmall
            ?.copyWith(color: color, fontWeight: FontWeight.w700),
      ),
    );
  }
}
