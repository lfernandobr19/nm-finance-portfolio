import 'package:flutter/material.dart';

import '../../../core/market_hours.dart';

Future<void> showDeskMarketSheet(BuildContext context, {required bool isUs}) {
  return showModalBottomSheet<void>(
    context: context,
    showDragHandle: true,
    isScrollControlled: true,
    builder: (ctx) {
      final sessions = MarketHours.all();
      return SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 0, 16, 24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Text('Horário de pregão', style: Theme.of(ctx).textTheme.titleLarge),
              const SizedBox(height: 12),
              ...sessions.map((s) => _MarketRow(session: s, highlight: (isUs && s.id == 'us') || (!isUs && s.id == 'b3'))),
            ],
          ),
        ),
      );
    },
  );
}

class _MarketRow extends StatelessWidget {
  const _MarketRow({required this.session, required this.highlight});

  final MarketSession session;
  final bool highlight;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final color = session.isOpen ? Colors.green.shade700 : scheme.onSurfaceVariant;
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  session.name,
                  style: Theme.of(context).textTheme.titleSmall?.copyWith(
                        fontWeight: highlight ? FontWeight.w700 : FontWeight.w500,
                      ),
                ),
                Text(session.hoursExchange, style: Theme.of(context).textTheme.bodySmall),
                Text('Brasil: ${session.hoursLocalBr}', style: Theme.of(context).textTheme.bodySmall),
                if (session.note != null && highlight && !session.isOpen)
                  Text(
                    session.note!,
                    style: Theme.of(context).textTheme.bodySmall?.copyWith(
                          color: Colors.orange.shade800,
                          fontStyle: FontStyle.italic,
                        ),
                  ),
              ],
            ),
          ),
          Chip(
            label: Text(
              session.statusLabel,
              style: TextStyle(fontSize: 11, color: color, fontWeight: FontWeight.w600),
            ),
            backgroundColor: session.isOpen
                ? Colors.green.withValues(alpha: 0.12)
                : scheme.surfaceContainerHighest,
            visualDensity: VisualDensity.compact,
            side: BorderSide(color: color.withValues(alpha: 0.35)),
          ),
        ],
      ),
    );
  }
}
