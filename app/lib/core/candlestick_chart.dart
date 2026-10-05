import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import 'format.dart';
import 'ohlc_chart.dart';

const _up = Color(0xFF2E7D32);
const _down = Color(0xFFC62828);

/// Time-window presets for the candlestick chart (client-side slicing).
enum CandlestickPeriod {
  m1('1M', 30),
  m3('3M', 90),
  m6('6M', 180),
  ytd('YTD', null),
  all('Tudo', null);

  const CandlestickPeriod(this.label, this.days);

  final String label;
  final int? days;
}

/// Interactive OHLC candlestick chart (fl_chart).
///
/// Adds what the old `CustomPaint` chart lacked: hover/tap tooltip with
/// date + OHLC + volume, crosshair, horizontal zoom/pan and a period filter.
/// Level lines (entry/stop/target/piso) are drawn via `rangeAnnotations`.
class InteractiveCandlestickChart extends StatefulWidget {
  const InteractiveCandlestickChart({
    super.key,
    required this.bars,
    this.entry,
    this.stop,
    this.target,
    this.setupLow,
    this.showStopTarget = false,
    this.showVolume = true,
    this.height = 260,
  });

  final List<OhlcBar> bars;
  final double? entry;
  final double? stop;
  final double? target;
  final double? setupLow;

  /// Whether to draw stop/target levels (day-trade) vs hide them (swing).
  final bool showStopTarget;

  /// Render a subtle volume histogram below the candles.
  final bool showVolume;

  final double height;

  @override
  State<InteractiveCandlestickChart> createState() =>
      _InteractiveCandlestickChartState();
}

class _InteractiveCandlestickChartState extends State<InteractiveCandlestickChart> {
  CandlestickPeriod _period = CandlestickPeriod.m3;
  final TransformationController _transform = TransformationController();

  @override
  void dispose() {
    _transform.dispose();
    super.dispose();
  }

  List<OhlcBar> get _sliced {
    final bars = widget.bars;
    final days = _period.days;
    if (days == null) {
      if (_period == CandlestickPeriod.ytd) {
        final start = DateTime(DateTime.now().year);
        return bars.where((b) => !b.date.isBefore(start)).toList();
      }
      return bars;
    }
    final cutoff = DateTime.now().subtract(Duration(days: days));
    final filtered = bars.where((b) => !b.date.isBefore(cutoff)).toList();
    return filtered.isEmpty ? bars : filtered;
  }

  void _resetZoom() {
    _transform.value = Matrix4.identity();
  }

  @override
  Widget build(BuildContext context) {
    final bars = _sliced;
    if (bars.length < 2) {
      return const Padding(
        padding: EdgeInsets.symmetric(vertical: 12),
        child: Text('Gráfico indisponível (sem histórico em cache).'),
      );
    }

    final levels = <double>[
      if (widget.entry != null) widget.entry!,
      if (widget.showStopTarget && widget.stop != null) widget.stop!,
      if (widget.showStopTarget && widget.target != null) widget.target!,
      if (widget.setupLow != null) widget.setupLow!,
    ];

    var minY = bars.map((b) => b.low).reduce((a, b) => a < b ? a : b);
    var maxY = bars.map((b) => b.high).reduce((a, b) => a > b ? a : b);
    for (final l in levels) {
      if (l < minY) minY = l;
      if (l > maxY) maxY = l;
    }
    final pad = (maxY - minY) * 0.06;
    minY -= pad == 0 ? 1 : pad;
    maxY += pad == 0 ? 1 : pad;

    final spots = <CandlestickSpot>[
      for (var i = 0; i < bars.length; i++)
        CandlestickSpot(
          x: i.toDouble(),
          open: bars[i].open,
          high: bars[i].high,
          low: bars[i].low,
          close: bars[i].close,
        ),
    ];

    final hasVolume = widget.showVolume && bars.any((b) => b.volume > 0);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _PeriodBar(
          selected: _period,
          onChanged: (p) => setState(() {
            _period = p;
            _resetZoom();
          }),
          onReset: _resetZoom,
        ),
        const SizedBox(height: 4),
        SizedBox(
          height: widget.height,
          width: double.infinity,
          child: CandlestickChart(
            CandlestickChartData(
              candlestickSpots: spots,
              minY: minY,
              maxY: maxY,
              candlestickPainter: DefaultCandlestickPainter(
                candlestickStyleProvider: (spot, _) => CandlestickStyle(
                  lineColor: spot.isUp ? _up : _down,
                  lineWidth: 1.2,
                  bodyStrokeColor: spot.isUp ? _up : _down,
                  bodyStrokeWidth: 0,
                  bodyFillColor: spot.isUp ? _up : _down,
                  bodyWidth: 4,
                  bodyRadius: 0,
                ),
              ),
              candlestickTouchData: CandlestickTouchData(
                handleBuiltInTouches: true,
                touchTooltipData: CandlestickTouchTooltipData(
                  maxContentWidth: 172,
                  fitInsideHorizontally: true,
                  fitInsideVertically: true,
                  tooltipBorderRadius: BorderRadius.circular(8),
                  getTooltipColor: (spot) => const Color(0xEE2B2B2B),
                  getTooltipItems: (painter, spot, index) =>
                      _tooltip(bars, index),
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
                        style: Theme.of(context).textTheme.labelSmall,
                      );
                    },
                  ),
                ),
                bottomTitles: AxisTitles(
                  sideTitles: SideTitles(
                    showTitles: true,
                    reservedSize: 22,
                    interval: _bottomInterval(bars.length),
                    getTitlesWidget: (value, meta) {
                      final i = value.round();
                      if (i < 0 || i >= bars.length) return const SizedBox.shrink();
                      return Text(
                        _dateLabel(bars[i].date),
                        style: Theme.of(context).textTheme.labelSmall,
                      );
                    },
                  ),
                ),
              ),
              rangeAnnotations: RangeAnnotations(
                horizontalRangeAnnotations: _levelAnnotations(minY, maxY),
              ),
            ),
            transformationConfig: FlTransformationConfig(
              scaleAxis: FlScaleAxis.horizontal,
              minScale: 1.0,
              maxScale: 8.0,
              panEnabled: true,
              scaleEnabled: true,
              transformationController: _transform,
            ),
          ),
        ),
        if (hasVolume) ...[
          const SizedBox(height: 4),
          SizedBox(
            height: 44,
            width: double.infinity,
            child: _VolumeStrip(bars: bars),
          ),
        ],
        const SizedBox(height: 6),
        Wrap(
          spacing: 12,
          runSpacing: 4,
          children: [
            if (widget.entry != null)
              _legend(const Color(0xFF1565C0), 'Entrada ${formatPrice(widget.entry)}'),
            if (widget.showStopTarget && widget.stop != null)
              _legend(const Color(0xFFC62828), 'Stop ${formatPrice(widget.stop)}'),
            if (widget.showStopTarget && widget.target != null)
              _legend(const Color(0xFF2E7D32), 'Alvo ${formatPrice(widget.target)}'),
            if (widget.setupLow != null)
              _legend(const Color(0xFF6A1B9A), 'Piso ${formatPrice(widget.setupLow)}'),
          ],
        ),
      ],
    );
  }

  CandlestickTooltipItem? _tooltip(List<OhlcBar> bars, int index) {
    if (index < 0 || index >= bars.length) return null;
    final b = bars[index];
    final label = const TextStyle(color: Colors.white70, fontSize: 11);
    final value = TextStyle(
      color: Colors.white,
      fontWeight: FontWeight.w700,
      fontSize: 12,
    );
    String vol(OhlcBar b) => b.volume > 0 ? formatQty(b.volume) : '—';
    return CandlestickTooltipItem(
      '',
      textStyle: const TextStyle(color: Colors.white, fontSize: 12),
      children: [
        TextSpan(
          text: '${_dateLabel(b.date)}\n',
          style: const TextStyle(
            color: Colors.white,
            fontWeight: FontWeight.w800,
            fontSize: 12,
          ),
        ),
        TextSpan(text: 'Abertura  ', style: label),
        TextSpan(text: '${formatPrice(b.open)}\n', style: value),
        TextSpan(text: 'Máxima    ', style: label),
        TextSpan(text: '${formatPrice(b.high)}\n', style: value),
        TextSpan(text: 'Mínima    ', style: label),
        TextSpan(text: '${formatPrice(b.low)}\n', style: value),
        TextSpan(text: 'Fechamento', style: label),
        TextSpan(text: '${formatPrice(b.close)}\n', style: value),
        TextSpan(text: 'Volume    ', style: label),
        TextSpan(text: vol(b), style: value),
      ],
    );
  }

  double _bottomInterval(int n) {
    if (n <= 6) return 1;
    return (n / 5).ceilToDouble();
  }

  String _dateLabel(DateTime d) {
    final local = d.toLocal();
    final hasTime = local.hour != 0 || local.minute != 0;
    return DateFormat(hasTime ? 'dd/MM HH:mm' : 'dd/MM/yy').format(local);
  }

  List<HorizontalRangeAnnotation> _levelAnnotations(double minY, double maxY) {
    final eps = (maxY - minY) * 0.004;
    final out = <HorizontalRangeAnnotation>[];
    void line(double? price, Color color) {
      if (price == null) return;
      out.add(HorizontalRangeAnnotation(
        y1: price - eps,
        y2: price + eps,
        color: color,
      ));
    }

    line(widget.entry, const Color(0xFF1565C0));
    if (widget.showStopTarget) {
      line(widget.stop, const Color(0xFFC62828));
      line(widget.target, const Color(0xFF2E7D32));
    }
    line(widget.setupLow, const Color(0xFF6A1B9A));
    return out;
  }

  Widget _legend(Color color, String text) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Container(width: 12, height: 3, color: color),
        const SizedBox(width: 6),
        Text(text, style: const TextStyle(fontSize: 12)),
      ],
    );
  }
}

class _PeriodBar extends StatelessWidget {
  const _PeriodBar({
    required this.selected,
    required this.onChanged,
    required this.onReset,
  });

  final CandlestickPeriod selected;
  final ValueChanged<CandlestickPeriod> onChanged;
  final VoidCallback onReset;

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        Expanded(
          child: SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            child: Row(
              children: [
                for (final p in CandlestickPeriod.values)
                  Padding(
                    padding: const EdgeInsets.only(right: 6),
                    child: ChoiceChip(
                      label: Text(p.label),
                      selected: selected == p,
                      visualDensity: VisualDensity.compact,
                      onSelected: (_) => onChanged(p),
                    ),
                  ),
              ],
            ),
          ),
        ),
        IconButton(
          tooltip: 'Resetar zoom',
          visualDensity: VisualDensity.compact,
          onPressed: onReset,
          icon: const Icon(Icons.zoom_out_map, size: 18),
        ),
      ],
    );
  }
}

/// Subtle volume histogram aligned under the candles (no zoom sync).
class _VolumeStrip extends StatelessWidget {
  const _VolumeStrip({required this.bars});

  final List<OhlcBar> bars;

  @override
  Widget build(BuildContext context) {
    var maxV = 0.0;
    for (final b in bars) {
      if (b.volume > maxV) maxV = b.volume;
    }
    if (maxV <= 0) return const SizedBox.shrink();
    return BarChart(
      BarChartData(
        barGroups: [
          for (var i = 0; i < bars.length; i++)
            BarChartGroupData(
              x: i,
              barRods: [
                BarChartRodData(
                  toY: bars[i].volume,
                  width: 3,
                  color: (bars[i].close >= bars[i].open ? _up : _down)
                      .withValues(alpha: 0.35),
                  borderRadius: BorderRadius.zero,
                ),
              ],
            ),
        ],
        maxY: maxV * 1.05,
        barTouchData: BarTouchData(enabled: false),
        gridData: const FlGridData(show: false),
        borderData: FlBorderData(show: false),
        titlesData: const FlTitlesData(
          leftTitles: AxisTitles(sideTitles: SideTitles(showTitles: false)),
          rightTitles: AxisTitles(sideTitles: SideTitles(showTitles: false)),
          topTitles: AxisTitles(sideTitles: SideTitles(showTitles: false)),
          bottomTitles: AxisTitles(sideTitles: SideTitles(showTitles: false)),
        ),
      ),
    );
  }
}
