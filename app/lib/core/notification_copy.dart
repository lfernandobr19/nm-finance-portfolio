import 'format.dart';
import 'suggestion_poller.dart';

/// Title, collapsed summary, and expanded body for a suggestion notification.
class NotificationCopy {
  const NotificationCopy({
    required this.title,
    required this.summary,
    required this.bigBody,
  });

  final String title;
  final String summary;
  final String bigBody;
}

/// Build desk-specific notification text (Income vs Swing vs NM).
NotificationCopy buildSuggestionNotificationCopy(NewSuggestionEvent e) {
  if (e.strategyKind == 'hv_dip') {
    if (e.isAuto) {
      return _autoBuyCopy(e);
    }
    if (e.catalyst != null) {
      return _catalystCopy(e);
    }
    final tag = (e.letter != null && e.letter!.isNotEmpty) ? ' · ${e.letter}' : '';
    return _tradeDeskCopy(
      e,
      titlePrefix: 'NM Finance$tag',
      reviewSuffix: e.reviewRequired ? ' · REVIEW' : '',
    );
  }
  if (e.strategyKind == 'swing') {
    final tag = (e.letter != null && e.letter!.isNotEmpty) ? ' · ${e.letter}' : '';
    return _tradeDeskCopy(e, titlePrefix: 'NM Finance · Swing$tag');
  }
  return _incomeCopy(e);
}

const _catalystLabels = <String, String>{
  'partnership': 'parceria',
  'guidance_up': 'guidance positiva',
  'guidance_down': 'guidance negativa',
  'upgrade': 'upgrade',
  'downgrade': 'downgrade',
  'm_and_a': 'fusão/aquisição',
  'contract': 'contrato',
  'product_launch': 'lançamento',
  'earnings': 'resultado',
  'litigation': 'litígio',
  'regulation': 'regulação',
  'buyback': 'recompra',
  'restructuring': 'reestruturação',
  'new_leadership': 'nova liderança',
  'turnaround': 'turnaround',
  'other': 'notícia',
};

String _catalystLabel(String eventType) =>
    _catalystLabels[eventType] ?? eventType;

List<String> _catalystFactors(CatalystInfo c) {
  final f = <String>[];
  if (c.eventType != null && c.eventType!.isNotEmpty) {
    f.add(_catalystLabel(c.eventType!));
  }
  if (c.sentiment != null && c.sentiment!.isNotEmpty) f.add(c.sentiment!);
  if (c.confidence != null) f.add('conf ${(c.confidence! * 100).round()}%');
  if (c.impactScore != null) f.add('imp ${c.impactScore!.round()}');
  return f;
}

NotificationCopy _catalystCopy(NewSuggestionEvent e) {
  final c = e.catalyst!;
  final factors = _catalystFactors(c);
  final tag = (e.letter != null && e.letter!.isNotEmpty) ? ' · ${e.letter}' : '';
  final lines = <String>[
    'Nome da ação: ${_actionLabel(e)}',
    if (c.title != null && c.title!.isNotEmpty) 'Catalisador: ${c.title}',
    if (factors.isNotEmpty) 'Fatores: ${factors.join(' · ')}',
  ];
  if (e.entry != null) lines.add('Entrada: ${formatPrice(e.entry)}');
  if (e.stop != null) lines.add('Stop: ${formatPrice(e.stop)}');
  if (e.target != null) lines.add('Alvo: ${formatPrice(e.target)}');
  if (e.dipLive != null) lines.add('Dip vivo: ${formatPct(e.dipLive)}');
  final summaryParts = <String>[
    if (factors.isNotEmpty) factors.join(' · '),
    if (e.dipLive != null) 'Dip vivo ${formatPct(e.dipLive)}',
  ];
  final summary = summaryParts.isEmpty
      ? '${e.ticker} — confirme no app'
      : summaryParts.join(' · ');
  return NotificationCopy(
    title: 'NM Finance · Compra sugerida · ${e.ticker}$tag',
    summary: summary,
    bigBody: lines.join('\n'),
  );
}

NotificationCopy _autoBuyCopy(NewSuggestionEvent e) {
  final c = e.catalyst;
  final factors = c != null ? _catalystFactors(c) : <String>[];
  final tag = (e.letter != null && e.letter!.isNotEmpty) ? ' · ${e.letter}' : '';
  final lines = <String>[
    'Nome da ação: ${_actionLabel(e)}',
    if (c != null && c.title != null && c.title!.isNotEmpty)
      'Catalisador: ${c.title}',
    if (factors.isNotEmpty) 'Fatores: ${factors.join(' · ')}',
  ];
  if (e.entry != null) lines.add('Entrada: ${formatPrice(e.entry)}');
  if (e.stop != null) lines.add('Stop: ${formatPrice(e.stop)}');
  if (e.target != null) lines.add('Alvo: ${formatPrice(e.target)}');
  if (e.dipLive != null) lines.add('Dip vivo: ${formatPct(e.dipLive)}');
  final summaryParts = <String>[
    if (factors.isNotEmpty) factors.join(' · '),
    if (e.dipLive != null) 'Dip vivo ${formatPct(e.dipLive)}',
  ];
  final summary = summaryParts.isEmpty
      ? '${e.ticker} — compra automática'
      : summaryParts.join(' · ');
  return NotificationCopy(
    title: 'NM Finance · Compra automática · ${e.ticker}$tag',
    summary: summary,
    bigBody: lines.join('\n'),
  );
}

NotificationCopy _incomeCopy(NewSuggestionEvent e) {
  final actionName = _actionLabel(e);
  final lines = <String>[
    'Nome da ação: $actionName',
  ];
  if (e.effectiveYield != null) {
    lines.add('Yield efetivo: ${formatPct(e.effectiveYield)}');
  }
  if (e.grossYield != null &&
      (e.effectiveYield == null ||
          (e.grossYield! - e.effectiveYield!).abs() > 0.05)) {
    lines.add('Yield bruto: ${formatPct(e.grossYield)}');
  }
  if (e.proposedAmount != null) {
    lines.add('Valor: ${formatMoney(e.proposedAmount, currency: e.currency)}');
  }

  final bigBody = lines.join('\n');
  final summaryParts = <String>[];
  if (e.effectiveYield != null) {
    summaryParts.add('Yield ${formatPct(e.effectiveYield)}');
  }
  if (e.proposedAmount != null) {
    summaryParts.add(formatMoney(e.proposedAmount, currency: e.currency));
  }
  final summary = summaryParts.isEmpty
      ? 'Nova sugestão de renda'
      : summaryParts.join(' · ');

  return NotificationCopy(
    title: 'NM Finance · Renda · ${e.ticker}',
    summary: summary,
    bigBody: bigBody,
  );
}

NotificationCopy _tradeDeskCopy(
  NewSuggestionEvent e, {
  required String titlePrefix,
  String reviewSuffix = '',
}) {
  final actionName = _actionLabel(e);
  final lines = <String>[
    'Nome da ação: $actionName',
  ];
  if (e.entry != null) lines.add('Entrada: ${formatPrice(e.entry)}');
  if (e.stop != null) lines.add('Stop: ${formatPrice(e.stop)}');
  if (e.target != null) lines.add('Alvo: ${formatPrice(e.target)}');
  if (e.dipLive != null) lines.add('Dip vivo: ${formatPct(e.dipLive)}');
  if (e.proposedAmount != null) {
    lines.add('Valor: ${formatMoney(e.proposedAmount, currency: e.currency)}');
  }

  final bigBody = lines.join('\n');
  final summaryParts = <String>[];
  if (e.entry != null) summaryParts.add('Entrada ${formatPrice(e.entry)}');
  if (e.stop != null) summaryParts.add('Stop ${formatPrice(e.stop)}');
  if (e.dipLive != null) summaryParts.add('Dip vivo ${formatPct(e.dipLive)}');
  if (e.proposedAmount != null) {
    summaryParts.add(formatMoney(e.proposedAmount, currency: e.currency));
  }
  final summary = summaryParts.isEmpty
      ? '${e.ticker} — confirme no app'
      : summaryParts.join(' · ');

  return NotificationCopy(
    title: '$titlePrefix$reviewSuffix',
    summary: summary,
    bigBody: bigBody,
  );
}

String _actionLabel(NewSuggestionEvent e) {
  final name = e.assetName?.trim();
  if (name != null && name.isNotEmpty && name.toUpperCase() != e.ticker.toUpperCase()) {
    return '${e.ticker} ($name)';
  }
  return e.ticker;
}
