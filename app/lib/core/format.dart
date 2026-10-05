import 'package:intl/intl.dart';

final _brl = NumberFormat.currency(locale: 'pt_BR', symbol: r'R$');
final _usd = NumberFormat.currency(locale: 'en_US', symbol: r'US$');
final _price = NumberFormat('#,##0.00', 'pt_BR');
final _qty = NumberFormat('#,##0.###', 'pt_BR');
final _ratio = NumberFormat('0.00', 'pt_BR');
final _pct = NumberFormat('0.00', 'pt_BR');

double? asNum(dynamic value) {
  if (value == null) return null;
  if (value is num) return value.toDouble();
  return double.tryParse(value.toString().replaceAll(',', '.'));
}

String formatBrl(dynamic value) {
  final n = asNum(value);
  if (n == null) return '—';
  return _brl.format(n);
}

String formatUsd(dynamic value) {
  final n = asNum(value);
  if (n == null) return '—';
  return _usd.format(n);
}

String formatMoney(dynamic value, {String currency = 'BRL'}) {
  if (currency.toUpperCase() == 'USD') return formatUsd(value);
  return formatBrl(value);
}

String formatPrice(dynamic value) {
  final n = asNum(value);
  if (n == null) return '—';
  return _price.format(n);
}

String formatScore(dynamic value) {
  final n = asNum(value);
  if (n == null) return '—';
  if (n == n.roundToDouble()) return n.round().toString();
  return n.toStringAsFixed(1);
}

String formatRatio(dynamic value) {
  final n = asNum(value);
  if (n == null) return '—';
  return _ratio.format(n);
}

String formatPct(dynamic value) {
  final n = asNum(value);
  if (n == null) return '—';
  return '${_pct.format(n)}%';
}

String formatQty(dynamic value) {
  final n = asNum(value);
  if (n == null) return '—';
  return _qty.format(n);
}

const _metricLabels = {
  'atr_pct': 'ATR %',
  'volume_ratio': 'Volume / média 20',
  'breakout_level': 'Nível de rompimento',
  'strategy': 'Estratégia',
  'score_letter': 'Score',
  'r_multiple': 'R:R',
  'entry': 'Entrada',
  'stop': 'Stop',
  'target': 'Alvo',
  'price': 'Preço',
  'setup_low': 'Piso do setup',
  'dip_pct': 'Dip %',
  'dip_pct_live': 'Dip vivo %',
  'live_price': 'Preço ao vivo',
  'refreshed_at': 'Atualizado em',
  'entry_at_refresh': 'Entrada (refresh)',
  'weekly_range_pct': 'Range semanal %',
  'tranche_index': 'Tranche',
  'review_required': 'Review',
  'effective_yield': 'Yield efetivo',
  'gross_yield': 'Yield bruto',
  'withholding_rate': 'Retenção',
  'p_vp': 'P/VP',
  'avg_volume': 'Volume médio',
  'change_day_pct': 'Variação no dia',
  'change_month_pct': 'Variação no mês',
  'sector': 'Setor',
  'name': 'Nome',
  'asset_class': 'Classe',
  'dividend_frequency': 'Frequência',
  'currency_exposure': 'Exposição cambial',
  'underlying_ticker': 'Ativo-base',
  'venue': 'Praça',
  'currency': 'Moeda',
  'h1_status': '1h',
};

String metricLabel(String key) => _metricLabels[key] ?? key;

String formatMetricValue(String key, dynamic value) {
  if (value == null) return '—';
  if (value is bool) return value ? 'sim' : 'não';
  if (key == 'strategy') {
    if (value == 'swing_dw_breakout') return 'Swing D+W (rompimento)';
    if (value == 'hv_dip_v1') return 'NM High-Vol Dip';
    return value.toString();
  }
  if (key == 'refreshed_at' && value is String) {
    try {
      final dt = DateTime.parse(value).toLocal();
      return DateFormat('HH:mm').format(dt);
    } catch (_) {
      return value;
    }
  }
  if (value is String) return value;
  if (key.contains('yield') ||
      key.endsWith('_pct') ||
      key == 'withholding_rate' ||
      key == 'atr_pct' ||
      key == 'dip_pct' ||
      key == 'dip_pct_live' ||
      key == 'weekly_range_pct') {
    return formatPct(value);
  }
  if (key == 'avg_volume') return formatQty(value);
  if (key == 'r_multiple' || key == 'volume_ratio' || key == 'p_vp') {
    return formatRatio(value);
  }
  if (key == 'score_letter' || key == 'tranche_index') return value.toString();
  if (asNum(value) != null) return formatPrice(value);
  return value.toString();
}

String formatRefreshedAt(dynamic value) {
  if (value == null) return '';
  try {
    final dt = DateTime.parse(value.toString()).toLocal();
    return DateFormat('HH:mm').format(dt);
  } catch (_) {
    return value.toString();
  }
}

bool isLiveSuggestion(Map<String, dynamic> metrics, {int maxAgeMinutes = 20}) {
  final raw = metrics['refreshed_at'];
  if (raw == null) return false;
  try {
    final dt = DateTime.parse(raw.toString()).toUtc();
    return DateTime.now().toUtc().difference(dt).inMinutes <= maxAgeMinutes;
  } catch (_) {
    return false;
  }
}

/// Compact Swing 1h chip. Unknown / missing status → hide the chip.
String? h1ChipLabel(String? status) {
  switch (status) {
    case 'h1_ok':
      return '1h OK';
    case 'h1_skip':
      return '1h —';
    case 'h1_fail':
      return '1h NÃO';
    default:
      return null;
  }
}

/// Pulse line for last Swing 1h scan counts (includes fails that never become cards).
String h1PulseLine({int ok = 0, int skip = 0, int fail = 0, String? ts}) {
  final base = '1h $ok OK · $skip — · $fail fora';
  final clock = formatRefreshedAt(ts);
  if (clock.isEmpty) return base;
  return '$base · scan $clock';
}

/// HITL line for 7B / Groq. Null when the heartbeat has not reported yet.
String? llmHealthLine({
  String? ollama,
  bool groqCooldown = false,
  String? expiresAt,
}) {
  if (groqCooldown && ollama != 'warm' && ollama != 'cold' && ollama != 'down') {
    return 'groq cooldown';
  }
  switch (ollama) {
    case 'warm':
      final until = formatRefreshedAt(expiresAt);
      if (until.isNotEmpty) {
        final head = '7B warm · até $until';
        return groqCooldown ? '$head · groq cooldown' : head;
      }
      return groqCooldown ? '7B warm · groq cooldown' : '7B warm · groq ok';
    case 'cold':
      return '7B cold';
    case 'down':
      return '7B down';
    default:
      return groqCooldown ? 'groq cooldown' : null;
  }
}

/// Last chat() source from the ARQ process. Fail / empty stay hidden.
String? lastLlmLine(String? source) {
  if (source == 'ollama' || source == 'groq') return 'último: $source';
  return null;
}

const swingHeaderMetricKeys = {
  'entry',
  'stop',
  'target',
  'price',
  'r_multiple',
  'score_letter',
  'setup_low',
  'dip_pct',
  'tranche_index',
  'review_required',
  'h1_status',
};
