import 'package:flutter/material.dart';

import '../../../core/format.dart';
import '../dashboard_data.dart';

/// Últimas movimentações (ordens) em formato compacto: badge de moeda e tempo
/// relativo, linhas densas.
class ActivityFeed extends StatelessWidget {
  const ActivityFeed({super.key, required this.items, this.maxItems = 6});

  final List<ActivityItem> items;
  final int maxItems;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final visible = items.take(maxItems).toList();

    return Card(
      margin: EdgeInsets.zero,
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              'Últimas movimentações',
              style: theme.textTheme.titleSmall
                  ?.copyWith(fontWeight: FontWeight.w700),
            ),
            const SizedBox(height: 6),
            if (visible.isEmpty)
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 8),
                child: Text(
                  'Nenhuma movimentação registrada.',
                  style: theme.textTheme.bodySmall,
                ),
              )
            else
              ...visible.map((i) => _row(context, i)),
          ],
        ),
      ),
    );
  }

  Widget _row(BuildContext context, ActivityItem i) {
    final theme = Theme.of(context);
    final isBuy = i.side.toLowerCase() == 'buy';
    final sideColor = isBuy ? Colors.green.shade700 : Colors.red.shade700;
    final sideLabel = isBuy ? 'Compra' : 'Venda';

    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        children: [
          Container(
            width: 26,
            height: 26,
            decoration: BoxDecoration(
              color: sideColor.withValues(alpha: 0.12),
              shape: BoxShape.circle,
            ),
            child: Icon(
              isBuy ? Icons.arrow_downward : Icons.arrow_upward,
              size: 15,
              color: sideColor,
            ),
          ),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              '${i.ticker} · $sideLabel',
              style: theme.textTheme.bodyMedium
                  ?.copyWith(fontWeight: FontWeight.w700),
              overflow: TextOverflow.ellipsis,
            ),
          ),
          const SizedBox(width: 6),
          Text(
            '${formatQty(i.quantity)} @ ${formatPrice(i.price)}',
            style: theme.textTheme.bodySmall
                ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
          ),
          const SizedBox(width: 8),
          _ccyBadge(theme, i.currency),
          const SizedBox(width: 8),
          SizedBox(
            width: 36,
            child: Text(
              _relative(i.at),
              textAlign: TextAlign.right,
              style: theme.textTheme.labelSmall
                  ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
            ),
          ),
        ],
      ),
    );
  }

  Widget _ccyBadge(ThemeData theme, String currency) {
    final isUsd = currency.toUpperCase() == 'USD';
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 1),
      decoration: BoxDecoration(
        color: theme.colorScheme.surfaceContainerHighest,
        borderRadius: BorderRadius.circular(4),
      ),
      child: Text(
        isUsd ? 'US\$' : 'R\$',
        style: theme.textTheme.labelSmall?.copyWith(fontWeight: FontWeight.w700),
      ),
    );
  }

  String _relative(DateTime at) {
    final diff = DateTime.now().difference(at);
    if (diff.inMinutes < 1) return 'agora';
    if (diff.inMinutes < 60) return '${diff.inMinutes}m';
    if (diff.inHours < 24) return '${diff.inHours}h';
    if (diff.inDays < 7) return '${diff.inDays}d';
    return '${at.day}/${at.month.toString().padLeft(2, '0')}';
  }
}
