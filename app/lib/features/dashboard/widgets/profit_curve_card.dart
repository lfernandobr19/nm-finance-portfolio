import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../../../core/format.dart';
import '../../../core/pnl_line_chart.dart';

/// Curva de lucro (realizado + não realizado) começando em 0, verde/vermelha.
class ProfitCurveCard extends StatelessWidget {
  const ProfitCurveCard({
    super.key,
    required this.points,
    required this.currency,
    required this.period,
    required this.onPeriodChanged,
  });

  final List<PnlPoint> points;
  final String currency;
  final String period;
  final ValueChanged<String> onPeriodChanged;

  static const _periods = [
    ('day', '1D'),
    ('week', '1S'),
    ('month', '1M'),
    ('year', '1A'),
  ];

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final ccy = currency.toUpperCase();
    final last = points.isEmpty ? 0.0 : points.last.cumulativePnl;

    return Card(
      margin: EdgeInsets.zero,
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(
                  child: Text(
                    'Lucro no período',
                    style: theme.textTheme.titleMedium
                        ?.copyWith(fontWeight: FontWeight.w700),
                  ),
                ),
                SegmentedButton<String>(
                  segments: [
                    for (final p in _periods)
                      ButtonSegment(value: p.$1, label: Text(p.$2)),
                  ],
                  selected: {period},
                  onSelectionChanged: (s) => onPeriodChanged(s.first),
                  showSelectedIcon: false,
                  style: const ButtonStyle(
                    visualDensity: VisualDensity.compact,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 8),
            Text(
              formatMoney(last, currency: ccy),
              style: theme.textTheme.headlineSmall?.copyWith(
                fontWeight: FontWeight.w800,
                color: last >= 0
                    ? Colors.green.shade700
                    : Colors.red.shade700,
              ),
            ),
            const SizedBox(height: 12),
            SizedBox(
              height: 180,
              width: double.infinity,
              child: _ProfitCanvas(points: points, currency: ccy),
            ),
          ],
        ),
      ),
    );
  }
}

class _ProfitCanvas extends StatelessWidget {
  const _ProfitCanvas({required this.points, required this.currency});

  final List<PnlPoint> points;
  final String currency;

  @override
  Widget build(BuildContext context) {
    if (points.length < 2) {
      return Center(
        child: Text(
          'Sem dados de lucro no período.',
          style: Theme.of(context).textTheme.bodySmall,
        ),
      );
    }

    final last = points.last.cumulativePnl;
    final color = last >= 0 ? const Color(0xFF2E7D32) : const Color(0xFFC62828);
    final spots = <FlSpot>[
      for (var i = 0; i < points.length; i++)
        FlSpot(i.toDouble(), points[i].cumulativePnl),
    ];

    var minY = 0.0;
    var maxY = 0.0;
    for (final p in points) {
      if (p.cumulativePnl < minY) minY = p.cumulativePnl;
      if (p.cumulativePnl > maxY) maxY = p.cumulativePnl;
    }
    if (minY == maxY) {
      minY -= 1;
      maxY += 1;
    }
    final pad = (maxY - minY) * 0.15;
    minY -= pad;
    maxY += pad;

    final labelStyle = Theme.of(context).textTheme.labelSmall ??
        const TextStyle(fontSize: 10);

    return LineChart(
      LineChartData(
        minX: 0,
        maxX: (points.length - 1).toDouble(),
        minY: minY,
        maxY: maxY,
        lineBarsData: [
          LineChartBarData(
            spots: spots,
            isCurved: true,
            color: color,
            barWidth: 2.4,
            dotData: const FlDotData(show: false),
            belowBarData: BarAreaData(
              show: true,
              color: color.withValues(alpha: 0.12),
            ),
          ),
        ],
        lineTouchData: LineTouchData(
          handleBuiltInTouches: true,
          touchTooltipData: LineTouchTooltipData(
            fitInsideHorizontally: true,
            fitInsideVertically: true,
            getTooltipColor: (_) => const Color(0xEE2B2B2B),
            getTooltipItems: (touched) => touched.map((s) {
              final i = s.x.round();
              final p = (i >= 0 && i < points.length) ? points[i] : null;
              final label =
                  DateFormat('dd/MM/yy').format(p?.date ?? DateTime.now());
              return LineTooltipItem(
                '$label\n${formatMoney(s.y, currency: currency)}',
                const TextStyle(color: Colors.white, fontSize: 12),
              );
            }).toList(),
          ),
        ),
        gridData: FlGridData(
          show: true,
          drawVerticalLine: false,
          horizontalInterval: (maxY - minY) / 4,
          getDrawingHorizontalLine: (_) => FlLine(
            color: const Color(0x14000000),
            strokeWidth: 1,
          ),
        ),
        borderData: FlBorderData(
          show: true,
          border: Border(
            left: BorderSide(color: const Color(0x22000000)),
            bottom: BorderSide(color: const Color(0x22000000)),
          ),
        ),
        extraLinesData: ExtraLinesData(
          horizontalLines: [
            if (0 >= minY && 0 <= maxY)
              HorizontalLine(
                y: 0,
                color: const Color(0x55000000),
                strokeWidth: 1,
                dashArray: const [4, 4],
              ),
          ],
        ),
        titlesData: FlTitlesData(
          topTitles: const AxisTitles(
            sideTitles: SideTitles(showTitles: false),
          ),
          rightTitles: const AxisTitles(
            sideTitles: SideTitles(showTitles: false),
          ),
          leftTitles: AxisTitles(
            sideTitles: SideTitles(
              showTitles: true,
              reservedSize: 54,
              getTitlesWidget: (value, meta) {
                if (meta.min == meta.max) return const SizedBox.shrink();
                return Text(formatPrice(value), style: labelStyle);
              },
            ),
          ),
          bottomTitles: AxisTitles(
            sideTitles: SideTitles(
              showTitles: true,
              reservedSize: 22,
              interval: points.length <= 6
                  ? 1
                  : (points.length / 5).ceilToDouble(),
              getTitlesWidget: (value, meta) {
                final i = value.round();
                if (i < 0 || i >= points.length) return const SizedBox.shrink();
                return Text(
                  DateFormat('dd/MM').format(points[i].date.toLocal()),
                  style: labelStyle,
                );
              },
            ),
          ),
        ),
      ),
    );
  }
}
