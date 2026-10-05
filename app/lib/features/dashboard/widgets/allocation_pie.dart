import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/material.dart';

import '../../../core/format.dart';
import '../dashboard_data.dart';

const _palette = [
  Color(0xFF1B4D3E),
  Color(0xFF2E7D32),
  Color(0xFF1565C0),
  Color(0xFF6A1B9A),
  Color(0xFFEF6C00),
  Color(0xFF00838F),
  Color(0xFFC62828),
  Color(0xFF827717),
];
const _othersColor = Color(0xFF9E9E9E);

/// Pizza de alocação por ativo (top 5 + "Outros"), em card, com total no centro
/// e tooltip em moeda.
class AllocationPieChart extends StatefulWidget {
  const AllocationPieChart({
    super.key,
    required this.slices,
    required this.currency,
  });

  final List<AllocationSlice> slices;
  final String currency;

  @override
  State<AllocationPieChart> createState() => _AllocationPieChartState();
}

class _AllocationPieChartState extends State<AllocationPieChart> {
  int _touched = -1;

  List<AllocationSlice> get _top => widget.slices.take(5).toList();

  double get _othersValue {
    if (widget.slices.length <= 5) return 0;
    return widget.slices.skip(5).fold<double>(0, (s, x) => s + x.value);
  }

  double get _othersPct {
    if (widget.slices.length <= 5) return 0;
    return widget.slices.skip(5).fold<double>(0, (s, x) => s + x.pct);
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final ccy = widget.currency.toUpperCase();

    return Card(
      margin: EdgeInsets.zero,
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              'Alocação por ativo',
              style: theme.textTheme.titleMedium
                  ?.copyWith(fontWeight: FontWeight.w700),
            ),
            const SizedBox(height: 12),
            if (widget.slices.isEmpty)
              SizedBox(
                height: 140,
                width: double.infinity,
                child: Center(
                  child: Text(
                    'Sem posições abertas para alocar.',
                    style: theme.textTheme.bodySmall,
                  ),
                ),
              )
            else
              _chart(theme, ccy),
          ],
        ),
      ),
    );
  }

  Widget _chart(ThemeData theme, String ccy) {
    final sections = <PieChartSectionData>[
      for (var i = 0; i < _top.length; i++)
        PieChartSectionData(
          value: _top[i].value,
          title: '',
          color: _palette[i % _palette.length],
          radius: 56,
        ),
      if (_othersValue > 0)
        PieChartSectionData(
          value: _othersValue,
          title: '',
          color: _othersColor,
          radius: 56,
        ),
    ];

    final total = widget.slices.fold<double>(0, (s, x) => s + x.value);
    final selected = _selectedInfo();

    return Column(
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        SizedBox(
          height: 180,
          child: Row(
            children: [
              Expanded(
                flex: 5,
                child: Stack(
                  alignment: Alignment.center,
                  children: [
                    PieChart(
                      PieChartData(
                        sections: sections,
                        centerSpaceRadius: 40,
                        sectionsSpace: 2,
                        startDegreeOffset: -90,
                        pieTouchData: PieTouchData(
                          touchCallback: (event, response) {
                            final idx = response
                                ?.touchedSection?.touchedSectionIndex;
                            if (idx == null || !mounted) return;
                            setState(
                                () => _touched = _touched == idx ? -1 : idx);
                          },
                        ),
                      ),
                    ),
                    SizedBox(
                      width: 72,
                      child: FittedBox(
                        fit: BoxFit.scaleDown,
                        child: Column(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            Text(
                              'Total',
                              style: theme.textTheme.labelSmall?.copyWith(
                                color: theme.colorScheme.onSurfaceVariant,
                              ),
                            ),
                            Text(
                              formatMoney(total, currency: ccy),
                              style: theme.textTheme.labelLarge?.copyWith(
                                fontWeight: FontWeight.w800,
                              ),
                            ),
                          ],
                        ),
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(width: 16),
              Expanded(
                flex: 4,
                child: _Legend(
                  entries: _legendEntries(),
                  selectedIndex: _touched,
                ),
              ),
            ],
          ),
        ),
        if (selected != null) ...[
          const SizedBox(height: 8),
          Text(
            selected,
            style: theme.textTheme.bodySmall?.copyWith(
              color: theme.colorScheme.onSurfaceVariant,
              fontWeight: FontWeight.w600,
            ),
          ),
        ],
      ],
    );
  }

  List<(String, String, Color)> _legendEntries() {
    return [
      for (var i = 0; i < _top.length; i++)
        (
          _top[i].ticker,
          formatPct(_top[i].pct),
          _palette[i % _palette.length],
        ),
      if (_othersValue > 0) ('Outros', formatPct(_othersPct), _othersColor),
    ];
  }

  String? _selectedInfo() {
    if (_touched < 0) return null;
    final ccy = widget.currency.toUpperCase();
    if (_touched < _top.length) {
      final s = _top[_touched];
      return '${s.ticker} · ${formatMoney(s.value, currency: ccy)} · ${formatPct(s.pct)}';
    }
    return 'Outros · ${formatMoney(_othersValue, currency: ccy)}';
  }
}

class _Legend extends StatelessWidget {
  const _Legend({
    required this.entries,
    required this.selectedIndex,
  });

  final List<(String, String, Color)> entries;
  final int selectedIndex;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Column(
      mainAxisAlignment: MainAxisAlignment.center,
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        for (var i = 0; i < entries.length; i++)
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 3),
            child: Row(
              children: [
                Container(
                  width: 10,
                  height: 10,
                  decoration: BoxDecoration(
                    color: entries[i].$3,
                    borderRadius: BorderRadius.circular(2),
                  ),
                ),
                const SizedBox(width: 6),
                Expanded(
                  child: Text(
                    entries[i].$1,
                    style: theme.textTheme.labelMedium?.copyWith(
                      fontWeight: i == selectedIndex
                          ? FontWeight.w700
                          : FontWeight.w500,
                    ),
                    overflow: TextOverflow.ellipsis,
                  ),
                ),
                const SizedBox(width: 8),
                Text(
                  entries[i].$2,
                  style: theme.textTheme.labelMedium?.copyWith(
                    color: theme.colorScheme.onSurfaceVariant,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ],
            ),
          ),
      ],
    );
  }
}
