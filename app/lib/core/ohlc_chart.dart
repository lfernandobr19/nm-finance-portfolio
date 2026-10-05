import 'package:flutter/material.dart';

import 'format.dart';

class OhlcBar {
  const OhlcBar({
    required this.date,
    required this.open,
    required this.high,
    required this.low,
    required this.close,
    this.volume = 0,
  });

  final DateTime date;
  final double open;
  final double high;
  final double low;
  final double close;
  final double volume;

  static OhlcBar? fromJson(dynamic raw) {
    if (raw is! Map) return null;
    final open = asNum(raw['open']);
    final high = asNum(raw['high']);
    final low = asNum(raw['low']);
    final close = asNum(raw['close']);
    if (open == null || high == null || low == null || close == null) {
      return null;
    }
    DateTime date;
    final rawDate = raw['date'] ?? raw['ts'];
    if (rawDate is num) {
      date = DateTime.fromMillisecondsSinceEpoch(rawDate.round() * 1000, isUtc: true);
    } else {
      date = DateTime.tryParse(rawDate?.toString() ?? '') ?? DateTime.now();
    }
    return OhlcBar(
      date: date,
      open: open,
      high: high,
      low: low,
      close: close,
      volume: asNum(raw['volume']) ?? 0,
    );
  }
}

class OhlcChart extends StatelessWidget {
  const OhlcChart({
    super.key,
    required this.bars,
    this.entry,
    this.stop,
    this.target,
    this.setupLow,
    this.showStopTarget = false,
    this.height = 240,
  });

  final List<OhlcBar> bars;
  final double? entry;
  final double? stop;
  final double? target;
  final double? setupLow;

  /// Whether to draw the stop/target levels. Swing/sugestão hide them
  /// (exits are managed by LATCH/PROTECT/review); day-trade keeps them.
  final bool showStopTarget;
  final double height;

  @override
  Widget build(BuildContext context) {
    if (bars.length < 2) {
      return const Padding(
        padding: EdgeInsets.symmetric(vertical: 12),
        child: Text('Gráfico indisponível (sem histórico em cache).'),
      );
    }
    final slice = bars.length > 90 ? bars.sublist(bars.length - 90) : bars;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SizedBox(
          height: height,
          width: double.infinity,
          child: CustomPaint(
            painter: _OhlcPainter(
              bars: slice,
              entry: entry,
              stop: showStopTarget ? stop : null,
              target: showStopTarget ? target : null,
              setupLow: setupLow,
              labelStyle: Theme.of(context).textTheme.labelSmall ??
                  const TextStyle(fontSize: 10),
            ),
          ),
        ),
        const SizedBox(height: 8),
        Wrap(
          spacing: 12,
          runSpacing: 4,
          children: [
            if (entry != null) _legend(const Color(0xFF1565C0), 'Entrada ${formatPrice(entry)}'),
            if (showStopTarget && stop != null)
              _legend(const Color(0xFFC62828), 'Stop ${formatPrice(stop)}'),
            if (showStopTarget && target != null)
              _legend(const Color(0xFF2E7D32), 'Alvo ${formatPrice(target)}'),
            if (setupLow != null)
              _legend(const Color(0xFF6A1B9A), 'Piso ${formatPrice(setupLow)}'),
          ],
        ),
      ],
    );
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

class _OhlcPainter extends CustomPainter {
  _OhlcPainter({
    required this.bars,
    required this.entry,
    required this.stop,
    required this.target,
    required this.setupLow,
    required this.labelStyle,
  });

  final List<OhlcBar> bars;
  final double? entry;
  final double? stop;
  final double? target;
  final double? setupLow;
  final TextStyle labelStyle;

  @override
  void paint(Canvas canvas, Size size) {
    const left = 52.0;
    const right = 8.0;
    const top = 10.0;
    const bottom = 22.0;
    final plot = Rect.fromLTRB(left, top, size.width - right, size.height - bottom);
    if (plot.width <= 0 || plot.height <= 0) return;

    var minP = bars.first.low;
    var maxP = bars.first.high;
    for (final b in bars) {
      if (b.low < minP) minP = b.low;
      if (b.high > maxP) maxP = b.high;
    }
    for (final extra in [entry, stop, target, setupLow]) {
      if (extra == null) continue;
      if (extra < minP) minP = extra;
      if (extra > maxP) maxP = extra;
    }
    final pad = (maxP - minP) * 0.08;
    minP -= pad == 0 ? 1 : pad;
    maxP += pad == 0 ? 1 : pad;
    final range = maxP - minP;

    double yOf(double price) =>
        plot.bottom - ((price - minP) / range) * plot.height;

    final grid = Paint()
      ..color = const Color(0x22000000)
      ..strokeWidth = 1;
    for (var i = 0; i <= 4; i++) {
      final y = plot.top + plot.height * i / 4;
      canvas.drawLine(Offset(plot.left, y), Offset(plot.right, y), grid);
      final price = maxP - range * i / 4;
      _text(canvas, formatPrice(price), Offset(0, y - 6), plot.left - 4);
    }

    final n = bars.length;
    final slot = plot.width / n;
    final bodyW = (slot * 0.62).clamp(1.5, 8.0);
    final up = Paint()..color = const Color(0xFF2E7D32);
    final down = Paint()..color = const Color(0xFFC62828);
    final wickUp = Paint()
      ..color = const Color(0xFF2E7D32)
      ..strokeWidth = 1;
    final wickDown = Paint()
      ..color = const Color(0xFFC62828)
      ..strokeWidth = 1;

    for (var i = 0; i < n; i++) {
      final b = bars[i];
      final cx = plot.left + slot * (i + 0.5);
      final bull = b.close >= b.open;
      final body = bull ? up : down;
      final wick = bull ? wickUp : wickDown;
      canvas.drawLine(Offset(cx, yOf(b.high)), Offset(cx, yOf(b.low)), wick);
      final topY = yOf(b.open > b.close ? b.open : b.close);
      final botY = yOf(b.open < b.close ? b.open : b.close);
      final h = (botY - topY).abs().clamp(1.0, plot.height);
      canvas.drawRect(
        Rect.fromCenter(center: Offset(cx, (topY + botY) / 2), width: bodyW, height: h),
        body,
      );
    }

    void level(double? price, Color color) {
      if (price == null) return;
      final y = yOf(price);
      final paint = Paint()
        ..color = color
        ..strokeWidth = 1.2
        ..style = PaintingStyle.stroke;
      const dash = 5.0;
      var x = plot.left;
      while (x < plot.right) {
        canvas.drawLine(Offset(x, y), Offset((x + dash).clamp(x, plot.right), y), paint);
        x += dash * 2;
      }
    }

    level(entry, const Color(0xFF1565C0));
    level(stop, const Color(0xFFC62828));
    level(target, const Color(0xFF2E7D32));
    level(setupLow, const Color(0xFF6A1B9A));

    _text(
      canvas,
      '${bars.first.date.day.toString().padLeft(2, '0')}/${bars.first.date.month.toString().padLeft(2, '0')}',
      Offset(plot.left, plot.bottom + 4),
      plot.width,
      alignLeft: true,
    );
    _text(
      canvas,
      '${bars.last.date.day.toString().padLeft(2, '0')}/${bars.last.date.month.toString().padLeft(2, '0')}',
      Offset(plot.right - 40, plot.bottom + 4),
      40,
      alignLeft: true,
    );
  }

  void _text(
    Canvas canvas,
    String text,
    Offset offset,
    double maxWidth, {
    bool alignLeft = false,
  }) {
    final tp = TextPainter(
      text: TextSpan(text: text, style: labelStyle.copyWith(color: const Color(0xFF424242))),
      textDirection: TextDirection.ltr,
      maxLines: 1,
    )..layout(maxWidth: maxWidth);
    final dx = alignLeft
        ? offset.dx
        : (offset.dx + maxWidth - tp.width).clamp(0.0, offset.dx + maxWidth);
    tp.paint(canvas, Offset(alignLeft ? offset.dx : dx, offset.dy));
  }

  @override
  bool shouldRepaint(covariant _OhlcPainter old) =>
      old.bars != bars ||
      old.entry != entry ||
      old.stop != stop ||
      old.target != target ||
      old.setupLow != setupLow;
}
