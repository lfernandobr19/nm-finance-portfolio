import 'package:flutter/material.dart';

/// Desktop master-detail layout: fixed-width master pane + flexible detail
/// pane, separated by a divider. The detail pane collapses to an empty-state
/// when nothing is selected.
class MasterDetail extends StatelessWidget {
  const MasterDetail({
    super.key,
    required this.master,
    required this.detail,
    this.masterWidth = 340,
    this.emptyDetailMessage = 'Selecione um item para ver os detalhes.',
  });

  final Widget master;
  final Widget detail;
  final double masterWidth;
  final String emptyDetailMessage;

  @override
  Widget build(BuildContext context) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        SizedBox(
          width: masterWidth,
          child: DecoratedBox(
            decoration: BoxDecoration(
              color: Theme.of(context).colorScheme.surfaceContainerLow,
            ),
            child: master,
          ),
        ),
        const VerticalDivider(thickness: 1, width: 1),
        Expanded(
          child: detail,
        ),
      ],
    );
  }
}

/// Standard loading state for a pane.
class PaneLoading extends StatelessWidget {
  const PaneLoading({super.key});

  @override
  Widget build(BuildContext context) =>
      const Center(child: CircularProgressIndicator());
}

/// Standard error + retry state for a pane.
class PaneError extends StatelessWidget {
  const PaneError({super.key, required this.message, required this.onRetry});

  final String message;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.error_outline,
                size: 40, color: Theme.of(context).colorScheme.error),
            const SizedBox(height: 12),
            Text(message, textAlign: TextAlign.center),
            const SizedBox(height: 12),
            FilledButton(
                onPressed: onRetry, child: const Text('Tentar de novo')),
          ],
        ),
      ),
    );
  }
}

/// Standard empty state for a pane.
class PaneEmpty extends StatelessWidget {
  const PaneEmpty({super.key, required this.message, this.icon});

  final String message;
  final IconData? icon;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(icon ?? Icons.inbox_outlined,
                size: 40, color: theme.colorScheme.outline),
            const SizedBox(height: 12),
            Text(
              message,
              textAlign: TextAlign.center,
              style: theme.textTheme.bodyMedium
                  ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
            ),
          ],
        ),
      ),
    );
  }
}
