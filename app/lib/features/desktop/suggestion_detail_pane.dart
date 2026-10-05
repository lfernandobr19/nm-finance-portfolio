import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../core/api_client.dart';
import '../../core/candlestick_chart.dart';
import '../../core/format.dart';
import '../../core/ohlc_chart.dart';
import '../../data/models/suggestion.dart';
import '../../data/repositories/suggestions_repository.dart';

/// Detalhe completo de uma sugestão, renderizado inline no painel de detalhe
/// da Mesa (sem navegação para outra página). Inclui gráfico, motivos,
/// métricas, catalisador, notícias e ações de aprovar/rejeitar.
class SuggestionDetailPane extends StatefulWidget {
  const SuggestionDetailPane({
    super.key,
    required this.accountId,
    required this.suggestion,
    required this.myRole,
    required this.onChanged,
  });

  final String accountId;
  final Suggestion suggestion;
  final String myRole;
  final VoidCallback onChanged;

  @override
  State<SuggestionDetailPane> createState() => _SuggestionDetailPaneState();
}

class _SuggestionDetailPaneState extends State<SuggestionDetailPane> {
  bool _loading = true;
  bool _acting = false;
  String? _error;

  Map<String, dynamic>? _data;
  Map<String, dynamic>? _approveOptions;
  List<dynamic> _news = [];
  List<OhlcBar> _bars = [];

  double? _selectedAmountUsd;
  final _amountController = TextEditingController();
  String? _amountError;

  bool get _canAct =>
      widget.myRole == 'owner' || widget.myRole == 'operator';

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void didUpdateWidget(covariant SuggestionDetailPane oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.suggestion.id != widget.suggestion.id) {
      _load();
    }
  }

  @override
  void dispose() {
    _amountController.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    final api = context.read<ApiClient>();
    try {
      _data = await api.getMap(
        '/accounts/${widget.accountId}/suggestions/${widget.suggestion.id}',
      );
      final ticker = _data!['ticker'] as String? ?? widget.suggestion.ticker;
      try {
        _news = await api.getList(
          '/accounts/${widget.accountId}/news',
          {'ticker': ticker},
        );
      } catch (_) {
        _news = [];
      }
      final kind = _data!['strategy_kind'] as String? ?? 'income';
      if (kind == 'swing' || kind == 'hv_dip') {
        try {
          final raw = await api.getList(
            '/accounts/${widget.accountId}/tickers/$ticker/bars',
          );
          _bars = raw.map(OhlcBar.fromJson).whereType<OhlcBar>().toList();
        } catch (_) {
          _bars = [];
        }
      }
      if (_data!['status'] == 'pending' && kind == 'hv_dip') {
        try {
          _approveOptions = await api.getMap(
            '/accounts/${widget.accountId}/suggestions/${widget.suggestion.id}/approve-options',
          );
          final def = asNum(_approveOptions?['default_amount_usd']);
          _selectedAmountUsd = def;
          if (_approveOptions?['fractional_allowed'] == true && def != null) {
            _amountController.text = def.toStringAsFixed(2);
          }
        } catch (_) {
          _approveOptions = null;
        }
      }
    } catch (e) {
      _error = formatApiError(e);
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  bool get _approvable => _approveOptions?['approvable'] != false;

  String? get _blockReason => _approveOptions?['block_reason'] as String?;

  bool get _fractionalAllowed =>
      _approveOptions?['fractional_allowed'] == true;

  List<Map<String, dynamic>> get _wholeShareOptions {
    final opts = (_approveOptions?['options'] as List<dynamic>?) ?? [];
    return opts.map((o) => Map<String, dynamic>.from(o as Map)).toList();
  }

  void _validateAmountInput(String raw) {
    if (!_fractionalAllowed) return;
    final max = asNum(_approveOptions?['max_amount_usd']);
    final val = double.tryParse(raw.replaceAll(',', '.'));
    setState(() {
      _selectedAmountUsd = val;
      if (val == null || val < 0.01) {
        _amountError = 'Informe um valor válido';
      } else if (max != null && val > max + 0.01) {
        _amountError = 'Máximo ${formatUsd(max)}';
      } else {
        _amountError = null;
      }
    });
  }

  bool get _canApproveAmount {
    if (_data?['status'] != 'pending') return false;
    if ((_data?['strategy_kind'] as String?) != 'hv_dip') return true;
    if (_approveOptions == null) return true;
    if (!_approvable) return false;
    if (_fractionalAllowed) {
      return _amountError == null &&
          _selectedAmountUsd != null &&
          _selectedAmountUsd! >= 0.01;
    }
    return _selectedAmountUsd != null;
  }

  Future<void> _act(bool approve) async {
    setState(() => _acting = true);
    final repo = SuggestionsRepository(context.read<ApiClient>());
    try {
      if (approve) {
        await repo.approve(
          widget.accountId,
          widget.suggestion.id,
          amountUsd: _selectedAmountUsd,
        );
      } else {
        await repo.reject(widget.accountId, widget.suggestion.id);
      }
      widget.onChanged();
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Falha: $e')),
        );
        setState(() => _acting = false);
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_loading) return const PaneLoadingLite();
    if (_error != null) {
      return Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(_error!, textAlign: TextAlign.center),
            const SizedBox(height: 12),
            FilledButton(onPressed: _load, child: const Text('Tentar de novo')),
          ],
        ),
      );
    }
    final data = _data!;
    final reasons = (data['reasons'] as List<dynamic>?) ?? [];
    final metrics = (data['metrics'] as Map<String, dynamic>?) ?? {};
    final catalyst = metrics['catalyst'] as Map<String, dynamic>?;
    final pending = data['status'] == 'pending';
    final llm = data['llm_summary'] as String?;
    final assetClass = data['asset_class'] as String? ?? 'fii';
    final freq = data['dividend_frequency'] as String? ?? '';
    final kind = data['strategy_kind'] as String? ?? 'income';
    final h1Label =
        kind == 'swing' ? h1ChipLabel(metrics['h1_status']?.toString()) : null;
    final isSwing = kind == 'swing' || kind == 'hv_dip';
    final isHv = kind == 'hv_dip';
    final letter = data['swing_score_letter'] as String?;
    final review = data['review_required'] == true;
    final currency = isHv ? 'USD' : 'BRL';
    final setupLow = asNum(data['setup_low'] ?? metrics['setup_low']);
    final dipPct = asNum(metrics['dip_pct']);
    final dipLive = asNum(metrics['dip_pct_live']);
    final refreshedAt = metrics['refreshed_at'];
    final tranche = metrics['tranche_index'];

    return ListView(
      padding: const EdgeInsets.all(20),
      children: [
        Row(
          children: [
            Expanded(
              child: Text(data['ticker'] as String? ?? widget.suggestion.ticker,
                  style: Theme.of(context).textTheme.headlineMedium),
            ),
            if (review)
              Chip(
                label: const Text('REVIEW'),
                backgroundColor: Theme.of(context).colorScheme.errorContainer,
              ),
          ],
        ),
        const SizedBox(height: 8),
        Wrap(
          spacing: 8,
          runSpacing: 4,
          children: [
            Chip(
              label: Text(isHv
                  ? 'HIGH-VOL NM'
                  : (isSwing ? 'SWING' : 'INCOME')),
            ),
            Chip(label: Text(assetClass.toUpperCase())),
            if (!isSwing) Chip(label: Text(freq)),
            if (letter != null) Chip(label: Text('Score $letter')),
            if (isHv && isLiveSuggestion(metrics))
              const Chip(label: Text('VIVA')),
            if (catalyst != null)
              Chip(label: Text('CATALISTA ${catalyst['event_type'] ?? ''}')),
            if (h1Label != null) Chip(label: Text(h1Label)),
          ],
        ),
        const SizedBox(height: 8),
        if (review)
          Card(
            color: Theme.of(context).colorScheme.errorContainer,
            child: Padding(
              padding: const EdgeInsets.all(12),
              child: Text(
                (data['review_reason'] as String?) ??
                    'Confirme notícias/decisão antes de aprovar (mesmo com auto).',
              ),
            ),
          ),
        if (catalyst != null) ...[
          const SizedBox(height: 8),
          Card(
            child: Padding(
              padding: const EdgeInsets.all(12),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text('Catalisador (notícia)',
                      style: TextStyle(fontWeight: FontWeight.bold)),
                  const SizedBox(height: 4),
                  Text('${catalyst['title'] ?? ''}'),
                  if (catalyst['confidence'] != null)
                    Text(
                      'Sentimento: ${catalyst['sentiment'] ?? '?'} · confiança '
                      '${(((catalyst['confidence'] as num?)?.toDouble() ?? 0) * 100).toStringAsFixed(0)}%',
                      style: const TextStyle(fontSize: 13),
                    ),
                ],
              ),
            ),
          ),
        ],
        const SizedBox(height: 12),
        Text(
          isSwing
              ? 'Score $letter (${formatScore(data['score'])})'
              : 'Score: ${formatScore(data['score'])}',
          style: Theme.of(context).textTheme.titleLarge,
        ),
        const SizedBox(height: 4),
        Text(
          'Status: ${data['status']} · Valor proposto: '
          '${formatMoney(data['proposed_amount_brl'], currency: currency)}',
        ),
        if (isSwing) ...[
          const SizedBox(height: 12),
          _kv(context, 'Entrada', formatPrice(data['entry_price'])),
          _kv(context, 'Stop', formatPrice(data['stop_price'])),
          _kv(context, 'Alvo', formatPrice(data['target_price'])),
          _kv(context, 'R:R', formatRatio(data['r_multiple'])),
          if (isHv && setupLow != null)
            _kv(context, 'Piso setup', formatPrice(setupLow)),
          if (isHv && dipPct != null) _kv(context, 'Dip (D-1)', formatPct(dipPct)),
          if (isHv && dipLive != null)
            _kv(context, 'Dip ao vivo',
                '${formatPct(dipLive)}'
                '${refreshedAt != null ? ' · ${formatRefreshedAt(refreshedAt)}' : ''}'),
          if (isHv && tranche != null) _kv(context, 'Tranche', '$tranche'),
          const SizedBox(height: 16),
          Text('Gráfico (diário)',
              style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: 8),
          InteractiveCandlestickChart(
            bars: _bars,
            entry: asNum(data['entry_price']),
            setupLow: setupLow,
          ),
        ],
        if (metrics['effective_yield'] != null)
          Padding(
            padding: const EdgeInsets.only(top: 8),
            child: Text(
              'Yield efetivo: ${formatPct(metrics['effective_yield'])}'
              '${metrics['gross_yield'] != null ? ' (bruto ${formatPct(metrics['gross_yield'])})' : ''}',
            ),
          ),
        if (llm != null && llm.isNotEmpty) ...[
          const SizedBox(height: 16),
          Text('Resumo (LLM)', style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: 8),
          SelectableText(llm),
        ],
        const SizedBox(height: 16),
        Text('Explicação do preço',
            style: Theme.of(context).textTheme.titleMedium),
        const SizedBox(height: 8),
        SelectableText(data['price_explanation'] as String? ?? ''),
        const SizedBox(height: 16),
        Text('Métricas', style: Theme.of(context).textTheme.titleMedium),
        ...metrics.entries
            .where((e) => !isSwing || !swingHeaderMetricKeys.contains(e.key))
            .map((e) => Padding(
                  padding: const EdgeInsets.only(top: 4),
                  child: Text(
                      '${metricLabel(e.key)}: ${formatMetricValue(e.key, e.value)}'),
                )),
        const SizedBox(height: 16),
        Text('Motivos (regras)', style: Theme.of(context).textTheme.titleMedium),
        ...reasons.map((r) {
          final m = r as Map<String, dynamic>;
          final ok = m['passed'] == true;
          return ListTile(
            dense: true,
            contentPadding: EdgeInsets.zero,
            leading: Icon(ok ? Icons.check_circle : Icons.cancel,
                color: ok ? Colors.green : Colors.red),
            title: Text(m['rule'] as String? ?? ''),
            subtitle: Text(m['detail'] as String? ?? ''),
          );
        }),
        const SizedBox(height: 16),
        Text('Notícias relacionadas',
            style: Theme.of(context).textTheme.titleMedium),
        if (_news.isEmpty) const Text('Nenhuma notícia vinculada a este ticker.'),
        ..._news.map((n) {
          final m = n as Map<String, dynamic>;
          return ListTile(
            dense: true,
            contentPadding: EdgeInsets.zero,
            title: Text(m['title'] as String? ?? ''),
            subtitle: Text(m['source'] as String? ?? ''),
          );
        }),
        if (pending && _canAct) ...[
          const SizedBox(height: 24),
          if (isHv && _approveOptions != null) ...[
            Text('Valor da ordem',
                style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: 8),
            if (!_approvable)
              Card(
                color: Theme.of(context).colorScheme.errorContainer,
                child: Padding(
                  padding: const EdgeInsets.all(12),
                  child: Text(
                    _blockReason ??
                        'Não é possível aprovar este ticker com o ticket atual.',
                  ),
                ),
              )
            else if (_fractionalAllowed) ...[
              TextField(
                controller: _amountController,
                keyboardType:
                    const TextInputType.numberWithOptions(decimal: true),
                decoration: InputDecoration(
                  labelText: 'Valor US\$',
                  prefixText: 'US\$ ',
                  errorText: _amountError,
                  helperText: _approveOptions?['max_amount_usd'] != null
                      ? 'Máx ${formatUsd(asNum(_approveOptions!['max_amount_usd'])!)} · '
                          'preço ${formatUsd(asNum(_approveOptions!['live_price']) ?? asNum(data['entry_price']))}'
                      : null,
                ),
                onChanged: _validateAmountInput,
              ),
            ] else ...[
              DropdownButtonFormField<double>(
                initialValue: _selectedAmountUsd,
                decoration: const InputDecoration(
                  labelText: 'Ações (sem fractional)',
                ),
                items: _wholeShareOptions
                    .map(
                      (o) => DropdownMenuItem<double>(
                        value: asNum(o['amount_usd']),
                        child: Text(o['label'] as String? ?? ''),
                      ),
                    )
                    .toList(),
                onChanged: (v) => setState(() => _selectedAmountUsd = v),
              ),
              if (_wholeShareOptions.isEmpty)
                Text(
                  _blockReason ?? 'Nenhuma opção de ações inteiras disponível.',
                  style: TextStyle(color: Theme.of(context).colorScheme.error),
                ),
            ],
          ],
          const SizedBox(height: 16),
          Row(
            children: [
              Expanded(
                child: OutlinedButton(
                  onPressed: _acting ? null : () => _act(false),
                  child: const Text('Rejeitar'),
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: FilledButton(
                  onPressed: (_acting || !_canApproveAmount) ? null : () => _act(true),
                  child: const Text('Aprovar'),
                ),
              ),
            ],
          ),
          const SizedBox(height: 8),
          Text(
            isHv
                ? 'Ao aprovar, ordem NM usa cotação ao vivo (notional ou limit +0,5%).'
                : 'Ao aprovar, ordem é enviada conforme valor proposto.',
            style: const TextStyle(fontSize: 12),
          ),
        ],
      ],
    );
  }

  Widget _kv(BuildContext context, String label, String value) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 3),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 130,
            child: Text(label, style: Theme.of(context).textTheme.labelMedium),
          ),
          Expanded(child: Text(value)),
        ],
      ),
    );
  }
}

/// Loading state without the full-pane scaffold (used inside a detail pane).
class PaneLoadingLite extends StatelessWidget {
  const PaneLoadingLite({super.key});

  @override
  Widget build(BuildContext context) =>
      const Center(child: CircularProgressIndicator());
}
