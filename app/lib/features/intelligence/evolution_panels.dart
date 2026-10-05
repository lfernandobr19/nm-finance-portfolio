import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import 'intelligence_store.dart';

class EvolutionPanel extends StatelessWidget {
  const EvolutionPanel(
      {super.key, required this.accountId, required this.refreshTick});

  final String accountId;
  final int refreshTick;

  @override
  Widget build(BuildContext context) {
    final store = context.watch<IntelligenceStore>();
    final items = store.evolution;
    if (store.loading && items.isEmpty) {
      return const Center(child: CircularProgressIndicator());
    }
    if (items.isEmpty) {
      return const Padding(
        padding: EdgeInsets.all(12),
        child: Text('Ainda sem eventos. O worker preenche a linha do tempo.'),
      );
    }
    return ListView.separated(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      itemCount: items.length,
      separatorBuilder: (_, __) => const Divider(height: 1),
      itemBuilder: (context, i) {
        final e = items[i];
        return ListTile(
          dense: true,
          contentPadding: EdgeInsets.zero,
          title: Text('${e['kind'] ?? ''} · ${e['title'] ?? ''}'),
          subtitle: Text(
            '${e['ts'] ?? ''}\n${e['detail'] ?? ''}',
            maxLines: 3,
            overflow: TextOverflow.ellipsis,
          ),
        );
      },
    );
  }
}

class MemoryPanel extends StatefulWidget {
  const MemoryPanel(
      {super.key, required this.accountId, required this.refreshTick});

  final String accountId;
  final int refreshTick;

  @override
  State<MemoryPanel> createState() => _MemoryPanelState();
}

class _MemoryPanelState extends State<MemoryPanel> {
  String _query = '';

  @override
  Widget build(BuildContext context) {
    final store = context.watch<IntelligenceStore>();
    final items = store.memories.where((m) {
      if (_query.isEmpty) return true;
      final q = _query.toLowerCase();
      return '${m['text']}'.toLowerCase().contains(q) ||
          '${m['scope']}'.toLowerCase().contains(q) ||
          (m['refuted'] == true ? 'refutada' : 'válida').contains(q);
    }).toList();
    if (store.loading && store.memories.isEmpty) {
      return const Center(child: CircularProgressIndicator());
    }
    if (store.memories.isEmpty) {
      return const Padding(
        padding: EdgeInsets.all(12),
        child: Text('Memória vazia. Lições aparecem após FDR, review ou notícia.'),
      );
    }
    return Column(
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(12, 8, 12, 0),
          child: TextField(
            decoration: const InputDecoration(
              isDense: true,
              hintText: 'Buscar lição, escopo, REFUTADA…',
              border: OutlineInputBorder(),
            ),
            onChanged: (v) => setState(() => _query = v),
          ),
        ),
        Expanded(
          child: ListView.builder(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
            itemCount: items.length,
            itemBuilder: (context, i) {
              final m = items[i];
              final refuted = m['refuted'] == true;
              return Padding(
                padding: const EdgeInsets.symmetric(vertical: 6),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      '${refuted ? 'REFUTADA' : 'válida'} · ${m['scope'] ?? ''}',
                      style: Theme.of(context)
                          .textTheme
                          .labelMedium
                          ?.copyWith(fontWeight: FontWeight.w700),
                    ),
                    Text(
                      '${m['text'] ?? ''}',
                      style: Theme.of(context).textTheme.bodySmall,
                    ),
                  ],
                ),
              );
            },
          ),
        ),
      ],
    );
  }
}

/// Reliability diagram: predicted mean vs observed frequency + diagonal.
class ReliabilityChart extends StatelessWidget {
  const ReliabilityChart({super.key, required this.buckets});

  final List<Map<String, dynamic>> buckets;

  @override
  Widget build(BuildContext context) {
    if (buckets.isEmpty) return const SizedBox.shrink();
    final color = Theme.of(context).colorScheme.primary;
    return SizedBox(
      height: 140,
      child: CustomPaint(
        painter: _ReliabilityPainter(buckets: buckets, color: color),
        child: const SizedBox.expand(),
      ),
    );
  }
}

class _ReliabilityPainter extends CustomPainter {
  _ReliabilityPainter({required this.buckets, required this.color});

  final List<Map<String, dynamic>> buckets;
  final Color color;

  @override
  void paint(Canvas canvas, Size size) {
    final axis = Paint()
      ..color = color.withValues(alpha: 0.3)
      ..strokeWidth = 1;
    canvas.drawLine(Offset(0, size.height), Offset(size.width, 0), axis);
    final line = Paint()
      ..color = color
      ..strokeWidth = 2
      ..style = PaintingStyle.stroke;
    final path = Path();
    for (var i = 0; i < buckets.length; i++) {
      final p = (buckets[i]['p_mean'] as num?)?.toDouble() ?? 0;
      final f = (buckets[i]['freq'] as num?)?.toDouble() ?? 0;
      final x = p.clamp(0.0, 1.0) * size.width;
      final y = (1 - f.clamp(0.0, 1.0)) * size.height;
      if (i == 0) {
        path.moveTo(x, y);
      } else {
        path.lineTo(x, y);
      }
      canvas.drawCircle(Offset(x, y), 3, Paint()..color = color);
    }
    canvas.drawPath(path, line);
  }

  @override
  bool shouldRepaint(covariant _ReliabilityPainter old) =>
      old.buckets != buckets;
}

/// Compact timeline for the mobile Estudos tab.
class EvolutionTimeline extends StatelessWidget {
  const EvolutionTimeline({super.key, required this.items});

  final List<Map<String, dynamic>> items;

  @override
  Widget build(BuildContext context) {
    if (items.isEmpty) {
      return const Text('Sem eventos recentes.');
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        for (final e in items.take(8))
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 3),
            child: Text(
              '${e['kind'] ?? ''} · ${e['title'] ?? ''}',
              style: Theme.of(context).textTheme.bodySmall,
            ),
          ),
      ],
    );
  }
}

