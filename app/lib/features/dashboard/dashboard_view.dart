import 'package:flutter/material.dart';

import '../desktop/master_detail.dart';
import 'dashboard_controller.dart';
import 'dashboard_data.dart';
import 'widgets/activity_feed.dart';
import 'widgets/allocation_pie.dart';
import 'widgets/currency_bucket_card.dart';
import 'widgets/open_positions_list.dart';
import 'widgets/profit_curve_card.dart';

/// Visão do dashboard: uma única visão por país, alternável por botão
/// (EUA primeiro/padrão), com cabeçalho de lucro + curva + alocação + posições.
class DashboardView extends StatefulWidget {
  const DashboardView({super.key, required this.controller, this.isWide = false});

  final DashboardController controller;
  final bool isWide;

  @override
  State<DashboardView> createState() => _DashboardViewState();
}

class _DashboardViewState extends State<DashboardView> {
  int _index = 0; // 0 = EUA (padrão), 1 = Brasil

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: widget.controller,
      builder: (context, _) {
        final c = widget.controller;
        final data = c.data;
        if (c.loading && data == null) return const PaneLoading();
        if (c.error != null && data == null) {
          return PaneError(message: c.error!, onRetry: c.load);
        }
        if (data == null || !data.hasAny) {
          return const PaneEmpty(
            message: 'Nenhuma conta com dados. '
                'Crie ou conecte uma conta para ver o resumo.',
            icon: Icons.dashboard_outlined,
          );
        }

        final buckets = [data.usd, data.brl];
        final current = _index < buckets.length ? buckets[_index] : null;

        return Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            _toggle(),
            const SizedBox(height: 16),
            Expanded(
              child: current == null
                  ? const PaneEmpty(
                      message: 'Nenhuma conta neste bloco.',
                      icon: Icons.account_balance_wallet_outlined,
                    )
                  : _content(current, data),
            ),
          ],
        );
      },
    );
  }

  Widget _toggle() {
    return SegmentedButton<int>(
      segments: const [
        ButtonSegment(
          value: 0,
          label: Text('EUA'),
          icon: Icon(Icons.attach_money),
        ),
        ButtonSegment(
          value: 1,
          label: Text('Brasil'),
          icon: Icon(Icons.currency_exchange),
        ),
      ],
      selected: {_index},
      onSelectionChanged: (s) => setState(() => _index = s.first),
    );
  }

  Widget _content(CurrencyBucket bucket, DashboardData data) {
    final children = <Widget>[
      CurrencyBucketCard(bucket: bucket),
      const SizedBox(height: 16),
      _curve(bucket),
      const SizedBox(height: 16),
    ];

    if (widget.isWide) {
      children.addAll([
        Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Expanded(
              child: AllocationPieChart(
                slices: bucket.allocation,
                currency: bucket.currency,
              ),
            ),
            const SizedBox(width: 16),
            Expanded(
              child: OpenPositionsList(
                positions: bucket.positions,
                currency: bucket.currency,
              ),
            ),
          ],
        ),
        const SizedBox(height: 16),
        ActivityFeed(items: data.activity),
      ]);
    } else {
      children.addAll([
        AllocationPieChart(slices: bucket.allocation, currency: bucket.currency),
        const SizedBox(height: 16),
        OpenPositionsList(positions: bucket.positions, currency: bucket.currency),
        const SizedBox(height: 16),
        ActivityFeed(items: data.activity),
      ]);
    }

    return ListView(
      padding: const EdgeInsets.all(16),
      children: children,
    );
  }

  Widget _curve(CurrencyBucket bucket) {
    final points =
        DashboardController.buildProfitCurve(bucket.pnlPoints, bucket.unrealizedPnl);
    return ProfitCurveCard(
      points: points,
      currency: bucket.currency,
      period: widget.controller.period,
      onPeriodChanged: (p) => widget.controller.setPeriod(p),
    );
  }
}
