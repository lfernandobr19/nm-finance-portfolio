import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import 'format.dart';

class PnlPoint {
  const PnlPoint({
    required this.date,
    required this.cumulativePnl,
    this.dayPnl = 0,
    this.targetCumulativePnl,
    this.dayTargetPnl,
    this.dayPnlPct,
    this.dayTargetPct,
  });

  final DateTime date;
  final double cumulativePnl;
  final double dayPnl;
  final double? targetCumulativePnl;
  final double? dayTargetPnl;
  final double? dayPnlPct;
  final double? dayTargetPct;

  static PnlPoint? fromJson(dynamic raw) {
    if (raw is! Map) return null;
    final cum = asNum(raw['cumulative_pnl']);
    if (cum == null) return null;
    final d = DateTime.tryParse(raw['date']?.toString() ?? '') ?? DateTime.now();
    return PnlPoint(
      date: d,
      cumulativePnl: cum,
      dayPnl: asNum(raw['day_pnl']) ?? 0,
      targetCumulativePnl: asNum(raw['target_cumulative_pnl']),
      dayTargetPnl: asNum(raw['day_target_pnl']),
      dayPnlPct: asNum(raw['day_pnl_pct']),
      dayTargetPct: asNum(raw['day_target_pct']),
    );
  }
}

/// Meta vs atingido (usado no diário e acima do gráfico).
class PnlGoalBanner extends StatelessWidget {
  const PnlGoalBanner({
    super.key,
    required this.goals,
    required this.currency,
  });

  final Map<String, dynamic> goals;
  final String currency;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final targetPct = asNum(goals['daily_target_pct']) ?? 7;
    final periodPnl = asNum(goals['period_pnl']) ?? 0;
    final periodPct = asNum(goals['period_pnl_pct']) ?? 0;
    final targetPnl = asNum(goals['period_target_pnl']) ?? 0;
    final targetPeriodPct = asNum(goals['period_target_pct']) ?? targetPct;
    final progress = ((asNum(goals['progress_pct']) ?? 0) / 100).clamp(0.0, 1.5);
    final hit = goals['hit'] == true;
    final days = goals['days_in_period'] ?? 1;
    final color = hit
        ? Colors.green.shade700
        : periodPnl < 0
            ? Colors.red.shade700
            : scheme.primary;

    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: scheme.surfaceContainerHighest.withValues(alpha: 0.55),
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: scheme.outlineVariant.withValues(alpha: 0.6)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  days == 1
                      ? 'Meta diária · ${formatPct(targetPct)}'
                      : 'Meta · ${formatPct(targetPct)}/dia × $days = ${formatPct(targetPeriodPct)}',
                  style: Theme.of(context).textTheme.titleSmall,
                ),
              ),
              Text(
                hit ? 'ATINGIDA' : 'EM CURSO',
                style: Theme.of(context).textTheme.labelSmall?.copyWith(
                      color: color,
                      fontWeight: FontWeight.w700,
                    ),
              ),
            ],
          ),
          const SizedBox(height: 8),
          ClipRRect(
            borderRadius: BorderRadius.circular(4),
            child: LinearProgressIndicator(
              value: progress > 1 ? 1 : progress,
              minHeight: 8,
              color: color,
              backgroundColor: scheme.surfaceContainerHighest,
            ),
          ),
          const SizedBox(height: 8),
          Row(
            children: [
              Expanded(
                child: Text(
                  'Atingido ${formatMoney(periodPnl, currency: currency)}'
                  ' (${formatPct(periodPct)})',
                  style: Theme.of(context).textTheme.bodySmall?.copyWith(
                        color: color,
                        fontWeight: FontWeight.w600,
                      ),
                ),
              ),
              Text(
                'Meta ${formatMoney(targetPnl, currency: currency)}',
                style: Theme.of(context).textTheme.bodySmall,
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class StretchScorecardCard extends StatelessWidget {
  const StretchScorecardCard({
    super.key,
    required this.scorecard,
    required this.currency,
  });

  final Map<String, dynamic> scorecard;
  final String currency;

  Widget _row(BuildContext context, String label, String now, String target, {bool? ok}) {
    final color = ok == true
        ? Colors.green.shade700
        : ok == false
            ? Colors.orange.shade800
            : null;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 3),
      child: Row(
        children: [
          Expanded(child: Text(label, style: Theme.of(context).textTheme.bodySmall)),
          Text(
            now,
            style: Theme.of(context).textTheme.bodySmall?.copyWith(
                  fontWeight: FontWeight.w700,
                  color: color,
                ),
          ),
          SizedBox(
            width: 72,
            child: Text(
              '→ $target',
              textAlign: TextAlign.right,
              style: Theme.of(context).textTheme.labelSmall?.copyWith(
                    color: Theme.of(context).colorScheme.onSurfaceVariant,
                  ),
            ),
          ),
        ],
      ),
    );
  }

  bool? _cmp(num? a, num? b, {bool higherBetter = true}) {
    if (a == null || b == null) return null;
    if (higherBetter) return a >= b;
    return a <= b;
  }

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final n = scorecard['closed_trades'] ?? 0;
    final horizon = scorecard['horizon_trades'] ?? 40;
    final days = scorecard['horizon_days'] ?? 60;
    final eqNow = asNum(scorecard['equity_now']) ?? 0;
    final eqT = asNum(scorecard['equity_target']) ?? 130;
    final avg = asNum(scorecard['avg_return_pct']) ?? 0;
    final avgT = asNum(scorecard['avg_return_target_pct']) ?? 11;
    final pnl = asNum(scorecard['realized_pnl']) ?? 0;
    final pnlT = asNum(scorecard['realized_pnl_target']) ?? 25;
    final latch = asNum(scorecard['latched_pct']) ?? 0;
    final latchT = asNum(scorecard['latched_target_pct']) ?? 55;
    final prot = asNum(scorecard['protect_or_2r_pct']) ?? 0;
    final protT = asNum(scorecard['protect_or_2r_target_pct']) ?? 40;
    final wr = asNum(scorecard['win_rate_pct']) ?? 0;
    final wrT = asNum(scorecard['win_rate_target_pct']) ?? 58;
    final exp = asNum(scorecard['expectancy_r']);
    final expT = asNum(scorecard['expectancy_r_target']) ?? 0.45;

    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: scheme.outlineVariant.withValues(alpha: 0.6)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            'Scorecard stretch · $n/$horizon trades · ${days}d',
            style: Theme.of(context).textTheme.titleSmall,
          ),
          const SizedBox(height: 6),
          _row(
            context,
            'Equity',
            formatMoney(eqNow, currency: currency),
            formatMoney(eqT, currency: currency),
            ok: _cmp(eqNow, eqT),
          ),
          _row(
            context,
            'Retorno médio',
            formatPct(avg),
            formatPct(avgT),
            ok: _cmp(avg, avgT),
          ),
          _row(
            context,
            'P&L realizado',
            formatMoney(pnl, currency: currency),
            formatMoney(pnlT, currency: currency),
            ok: _cmp(pnl, pnlT),
          ),
          _row(
            context,
            'LATCHED (+5%)',
            formatPct(latch),
            formatPct(latchT),
            ok: _cmp(latch, latchT),
          ),
          _row(
            context,
            'Saídas 2R/PROT',
            formatPct(prot),
            formatPct(protT),
            ok: _cmp(prot, protT),
          ),
          _row(
            context,
            'Win rate',
            formatPct(wr),
            '≥ ${formatPct(wrT)}',
            ok: _cmp(wr, wrT),
          ),
          _row(
            context,
            'Expectancy R',
            exp == null ? '—' : formatRatio(exp),
            '≥ ${formatRatio(expT)}',
            ok: exp == null ? null : _cmp(exp, expT),
          ),
        ],
      ),
    );
  }
}

/// Simple cumulative PnL line chart with optional daily-target curve.
class PnlLineChart extends StatelessWidget {
  const PnlLineChart({
    super.key,
    required this.points,
    this.currency = 'BRL',
    this.height = 160,
    this.dailyTargetPct = 7,
  });

  final List<PnlPoint> points;
  final String currency;
  final double height;
  final double dailyTargetPct;

  @override
  Widget build(BuildContext context) {
    final hasTarget = points.any((p) => p.targetCumulativePnl != null);
    if (points.length < 2) {
      return Padding(
        padding: const EdgeInsets.symmetric(vertical: 8),
        child: Text(
          points.isEmpty
              ? 'Sem trades fechados no período para montar a curva.'
              : 'Precisa de ao menos 2 dias para o gráfico de evolução.',
          style: Theme.of(context).textTheme.bodySmall,
        ),
      );
    }
    final last = points.last.cumulativePnl;
    final color = last >= 0 ? const Color(0xFF2E7D32) : const Color(0xFFC62828);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          'Curva P&L · ${formatMoney(last, currency: currency)}'
          '${hasTarget ? ' · meta ${formatPct(dailyTargetPct)}/dia' : ''}',
          style: Theme.of(context).textTheme.titleSmall,
        ),
        if (hasTarget) ...[
          const SizedBox(height: 4),
          Row(
            children: [
              _legendDot(color),
              const SizedBox(width: 4),
              Text('Realizado', style: Theme.of(context).textTheme.labelSmall),
              const SizedBox(width: 12),
              _legendDot(const Color(0xFF1565C0), dashed: true),
              const SizedBox(width: 4),
              Text('Meta', style: Theme.of(context).textTheme.labelSmall),
            ],
          ),
        ],
        const SizedBox(height: 8),
        SizedBox(
          height: height,
          width: double.infinity,
          child: _PnlLineChartCanvas(
            points: points,
            lineColor: color,
            targetColor: const Color(0xFF1565C0),
            currency: currency,
          ),
        ),
      ],
    );
  }

  Widget _legendDot(Color c, {bool dashed = false}) {
    return Container(
      width: 14,
      height: 3,
      decoration: BoxDecoration(
        color: dashed ? c.withValues(alpha: 0.85) : c,
        borderRadius: BorderRadius.circular(2),
      ),
    );
  }
}

/// fl_chart-backed line chart: tooltip (data + P&L), crosshair, dashed meta.
class _PnlLineChartCanvas extends StatelessWidget {
  const _PnlLineChartCanvas({
    required this.points,
    required this.lineColor,
    required this.targetColor,
    required this.currency,
  });

  final List<PnlPoint> points;
  final Color lineColor;
  final Color targetColor;
  final String currency;

  @override
  Widget build(BuildContext context) {
    final realized = <FlSpot>[
      for (var i = 0; i < points.length; i++)
        FlSpot(i.toDouble(), points[i].cumulativePnl),
    ];
    final target = <FlSpot>[
      for (var i = 0; i < points.length; i++)
        if (points[i].targetCumulativePnl != null)
          FlSpot(i.toDouble(), points[i].targetCumulativePnl!),
    ];
    final hasTarget = target.length >= 2;

    var minY = points.first.cumulativePnl;
    var maxY = points.first.cumulativePnl;
    for (final p in points) {
      if (p.cumulativePnl < minY) minY = p.cumulativePnl;
      if (p.cumulativePnl > maxY) maxY = p.cumulativePnl;
      final t = p.targetCumulativePnl;
      if (t != null) {
        if (t < minY) minY = t;
        if (t > maxY) maxY = t;
      }
    }
    if (minY == maxY) {
      minY -= 1;
      maxY += 1;
    }
    final pad = (maxY - minY) * 0.1;
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
            spots: realized,
            isCurved: false,
            color: lineColor,
            barWidth: 2,
            dotData: const FlDotData(show: false),
            belowBarData: BarAreaData(
              show: true,
              color: lineColor.withValues(alpha: 0.12),
            ),
          ),
          if (hasTarget)
            LineChartBarData(
              spots: target,
              isCurved: false,
              color: targetColor,
              barWidth: 1.6,
              dashArray: const [6, 4],
              dotData: const FlDotData(show: false),
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
              final label = DateFormat('dd/MM/yy').format(p?.date ?? DateTime.now());
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
                color: const Color(0x44000000),
                strokeWidth: 1,
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
                return Text(
                  formatPrice(value),
                  style: labelStyle,
                );
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
