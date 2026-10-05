import 'package:flutter/material.dart';

import '../../../core/format.dart';
import '../dashboard_data.dart';

/// Cabeçalho de resultado de um bloco (Brasil/EUA): lucro em destaque
/// (verde/vermelho) + chips de patrimônio, caixa, investido, P&L dia e posições.
class CurrencyBucketCard extends StatelessWidget {
  const CurrencyBucketCard({super.key, required this.bucket});

  final CurrencyBucket bucket;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final ccy = bucket.currency.toUpperCase();
    final isUsd = ccy == 'USD';
    final total = bucket.totalPnl;
    final positive = total >= 0;
    final accent = positive ? Colors.green.shade700 : Colors.red.shade700;

    return Card(
      margin: EdgeInsets.zero,
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(
                  isUsd ? Icons.attach_money : Icons.currency_exchange,
                  size: 18,
                  color: theme.colorScheme.primary,
                ),
                const SizedBox(width: 8),
                Text(
                  bucket.label,
                  style: theme.textTheme.titleMedium
                      ?.copyWith(fontWeight: FontWeight.w700),
                ),
                const Spacer(),
                Text(
                  isUsd ? 'USD' : 'BRL',
                  style: theme.textTheme.labelSmall?.copyWith(
                    color: theme.colorScheme.onSurfaceVariant,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 14),
            Row(
              crossAxisAlignment: CrossAxisAlignment.center,
              children: [
                Icon(
                  positive ? Icons.arrow_upward : Icons.arrow_downward,
                  size: 24,
                  color: accent,
                ),
                const SizedBox(width: 6),
                Expanded(
                  child: Text(
                    formatMoney(total.abs(), currency: ccy),
                    style: theme.textTheme.headlineMedium?.copyWith(
                      fontWeight: FontWeight.w800,
                      color: accent,
                    ),
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                  ),
                ),
                Text(
                  positive ? 'Lucro' : 'Prejuízo',
                  style: theme.textTheme.labelMedium?.copyWith(
                    color: accent,
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 2),
            Text(
              'Realizado ${formatMoney(bucket.realizedPnl, currency: ccy)} · '
              'Não realizado ${formatMoney(bucket.unrealizedPnl, currency: ccy)}',
              style: theme.textTheme.bodySmall
                  ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
            ),
            const SizedBox(height: 14),
            Wrap(
              spacing: 10,
              runSpacing: 10,
              children: [
                _chip(context, 'Patrimônio',
                    formatMoney(bucket.equity, currency: ccy)),
                _chip(context, 'Caixa', formatMoney(bucket.cash, currency: ccy)),
                _chip(context, 'Investido',
                    formatMoney(bucket.invested, currency: ccy)),
                _chip(context, 'P&L dia',
                    formatMoney(bucket.realizedPnlDay, currency: ccy)),
                _chip(context, 'Posições', '${bucket.openPositions}'),
              ],
            ),
          ],
        ),
      ),
    );
  }

  Widget _chip(BuildContext context, String label, String value) {
    final theme = Theme.of(context);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
      decoration: BoxDecoration(
        color: theme.colorScheme.surfaceContainerHighest.withValues(alpha: 0.5),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(
            '$label ',
            style: theme.textTheme.labelSmall
                ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
          ),
          Text(
            value,
            style: theme.textTheme.labelMedium?.copyWith(fontWeight: FontWeight.w700),
          ),
        ],
      ),
    );
  }
}
