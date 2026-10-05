import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../core/api_client.dart';
import '../../core/candlestick_chart.dart';
import '../../core/format.dart';
import '../../core/market_hours.dart';
import '../../core/ohlc_chart.dart';

class SuggestionDetailPage extends StatefulWidget {
  const SuggestionDetailPage({
    super.key,
    required this.accountId,
    required this.suggestionId,
    required this.myRole,
    this.waitingOrder,
  });

  final String accountId;
  final String suggestionId;
  final String myRole;
  /// When opened from Aguardando, includes queue order for status + cancel.
  final Map<String, dynamic>? waitingOrder;

  @override
  State<SuggestionDetailPage> createState() => _SuggestionDetailPageState();
}

class _SuggestionDetailPageState extends State<SuggestionDetailPage> {
  Map<String, dynamic>? data;
  Map<String, dynamic>? approveOptions;
  List<dynamic> news = [];
  List<OhlcBar> bars = [];
  bool loading = true;
  bool acting = false;
  String? error;
  double? selectedAmountUsd;
  final _amountController = TextEditingController();
  String? amountError;

  bool get canAct =>
      widget.myRole == 'owner' || widget.myRole == 'operator';

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _amountController.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    final api = context.read<ApiClient>();
    debugPrint('[detail] _load accountId="${widget.accountId}" suggestionId="${widget.suggestionId}"');
    try {
      data = await api.getMap(
        '/accounts/${widget.accountId}/suggestions/${widget.suggestionId}',
      );
    } catch (e) {
      debugPrint('[detail] _load getMap FAILED: $e');
      if (mounted) {
        setState(() {
          loading = false;
          error = 'Não foi possível carregar esta sugestão ($e). '
              'Ela pode ter sido aprovada, rejeitada ou removida.';
        });
      }
      return;
    }
    final ticker = data!['ticker'] as String;
    news = await api.getList(
      '/accounts/${widget.accountId}/news',
      {'ticker': ticker},
    );
    if ((data!['strategy_kind'] as String?) == 'swing' ||
        (data!['strategy_kind'] as String?) == 'hv_dip') {
      try {
        final raw = await api.getList(
          '/accounts/${widget.accountId}/tickers/$ticker/bars',
        );
        bars = raw.map(OhlcBar.fromJson).whereType<OhlcBar>().toList();
      } catch (_) {
        bars = [];
      }
    }
    if (data!['status'] == 'pending' &&
        (data!['strategy_kind'] as String?) == 'hv_dip') {
      try {
        approveOptions = await api.getMap(
          '/accounts/${widget.accountId}/suggestions/${widget.suggestionId}/approve-options',
        );
        final def = asNum(approveOptions?['default_amount_usd']);
        selectedAmountUsd = def;
        if (approveOptions?['fractional_allowed'] == true && def != null) {
          _amountController.text = def.toStringAsFixed(2);
        }
      } catch (_) {
        approveOptions = null;
      }
    }
    if (mounted) setState(() => loading = false);
  }

  bool get _approvable => approveOptions?['approvable'] != false;

  String? get _blockReason =>
      approveOptions?['block_reason'] as String?;

  bool get _fractionalAllowed =>
      approveOptions?['fractional_allowed'] == true;

  List<Map<String, dynamic>> get _wholeShareOptions {
    final opts = (approveOptions?['options'] as List<dynamic>?) ?? [];
    return opts.map((o) => Map<String, dynamic>.from(o as Map)).toList();
  }

  void _validateAmountInput(String raw) {
    if (!_fractionalAllowed) return;
    final max = asNum(approveOptions?['max_amount_usd']);
    final val = double.tryParse(raw.replaceAll(',', '.'));
    setState(() {
      selectedAmountUsd = val;
      if (val == null || val < 0.01) {
        amountError = 'Informe um valor válido';
      } else if (max != null && val > max + 0.01) {
        amountError = 'Máximo ${formatUsd(max)}';
      } else {
        amountError = null;
      }
    });
  }

  bool get _canApproveAmount {
    if (data?['status'] != 'pending') return false;
    if ((data?['strategy_kind'] as String?) != 'hv_dip') return true;
    if (approveOptions == null) return true;
    if (!_approvable) return false;
    if (_fractionalAllowed) {
      return amountError == null &&
          selectedAmountUsd != null &&
          selectedAmountUsd! >= 0.01;
    }
    return selectedAmountUsd != null;
  }

  Future<void> _act(bool approve) async {
    setState(() => acting = true);
    final api = context.read<ApiClient>();
    final path = approve ? 'approve' : 'reject';
    final body = <String, dynamic>{'note': null};
    if (approve &&
        (data?['strategy_kind'] as String?) == 'hv_dip' &&
        selectedAmountUsd != null) {
      body['amount_usd'] = selectedAmountUsd;
    }
    try {
      final res = await api.post(
        '/accounts/${widget.accountId}/suggestions/${widget.suggestionId}/$path',
        body,
        timeout: approve ? const Duration(seconds: 60) : const Duration(seconds: 20),
      );
      if (!mounted) return;
      if (approve) {
        final orderStatus = res['order_status'] as String?;
        final orderError = res['order_error'] as String?;
        if (orderStatus == 'rejected') {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
              content: Text(
                orderError?.isNotEmpty == true
                    ? 'Ordem rejeitada: $orderError'
                    : 'Ordem rejeitada pela corretora — não entrou na fila.',
              ),
              duration: const Duration(seconds: 8),
            ),
          );
        } else if (orderStatus == 'submitted' || orderStatus == 'awaiting_broker') {
          final hint = res['fill_hint'] as String?;
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
              content: Text(hint ?? 'Ordem enviada — aguardando execução.'),
            ),
          );
        } else if (orderStatus == 'filled') {
          final live = asNum(res['live_price']);
          final hint = res['fill_hint'] as String?;
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
              content: Text(
                hint ??
                    (live != null
                        ? 'Executado a ~${formatUsd(live)} (cotação ao vivo)'
                        : 'Ordem executada — posição aberta.'),
              ),
            ),
          );
        }
      }
      Navigator.of(context).pop();
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Falha: $e')),
        );
        setState(() => acting = false);
      }
    }
  }

  Future<void> _cancelWaitingOrder() async {
    final order = widget.waitingOrder;
    if (order == null) return;
    final ticker = order['ticker'] as String? ?? data?['ticker'] as String? ?? '?';
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Cancelar ordem?'),
        content: Text('Remove $ticker da fila e cancela na corretora (se já enviada).'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Voltar')),
          FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Cancelar ordem')),
        ],
      ),
    );
    if (ok != true || !mounted) return;
    setState(() => acting = true);
    try {
      await context.read<ApiClient>().post(
        '/accounts/${widget.accountId}/orders/${order['id']}/mark-cancelled',
        {},
      );
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Ordem $ticker removida da fila')),
        );
        Navigator.of(context).pop(true);
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Falha ao cancelar: $e')),
        );
        setState(() => acting = false);
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    if (loading) {
      return const Scaffold(body: Center(child: CircularProgressIndicator()));
    }
    if (error != null || data == null) {
      return Scaffold(
        appBar: AppBar(title: const Text('Sugestão')),
        body: Center(
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                const Icon(Icons.error_outline, size: 40),
                const SizedBox(height: 12),
                Text(
                  error ?? 'Sugestão indisponível.',
                  textAlign: TextAlign.center,
                ),
              ],
            ),
          ),
        ),
      );
    }
    final reasons = (data!['reasons'] as List<dynamic>?) ?? [];
    final metrics = (data!['metrics'] as Map<String, dynamic>?) ?? {};
    final catalyst = metrics['catalyst'] as Map<String, dynamic>?;
    final pending = data!['status'] == 'pending';
    final waitingOrder = widget.waitingOrder;
    final queueActive = waitingOrder != null &&
        const {'submitted', 'queued', 'awaiting_broker'}.contains(waitingOrder['status']);
    final llm = data!['llm_summary'] as String?;
    final assetClass = data!['asset_class'] as String? ?? 'fii';
    final freq = data!['dividend_frequency'] as String? ?? '';
    final kind = data!['strategy_kind'] as String? ?? 'income';
    final h1Label =
        kind == 'swing' ? h1ChipLabel(metrics['h1_status']?.toString()) : null;
    final isSwing = kind == 'swing' || kind == 'hv_dip';
    final isHv = kind == 'hv_dip';
    final letter = data!['swing_score_letter'] as String?;
    final review = data!['review_required'] == true;
    final currency = isHv ? 'USD' : 'BRL';
    final setupLow = asNum(data!['setup_low'] ?? metrics['setup_low']);
    final dipPct = asNum(metrics['dip_pct']);
    final dipLive = asNum(metrics['dip_pct_live']);
    final refreshedAt = metrics['refreshed_at'];
    final tranche = metrics['tranche_index'];

    return Scaffold(
      appBar: AppBar(title: Text(data!['ticker'] as String)),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          if (queueActive) ...[
            Card(
              color: Theme.of(context).colorScheme.primaryContainer.withValues(alpha: 0.35),
              child: Padding(
                padding: const EdgeInsets.all(12),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Text('Na fila', style: Theme.of(context).textTheme.titleMedium),
                    const SizedBox(height: 4),
                    Text(
                      '${waitingOrder['ticker']} · ${formatQty(waitingOrder['quantity'])} · '
                      'limit ${formatPrice(waitingOrder['limit_price'])}',
                    ),
                    Text(orderWaitingLabel(waitingOrder)),
                    if (orderWaitingDetail(waitingOrder) != null)
                      Text(
                        orderWaitingDetail(waitingOrder)!,
                        style: Theme.of(context).textTheme.bodySmall,
                      ),
                    if (canAct) ...[
                      const SizedBox(height: 12),
                      OutlinedButton.icon(
                        onPressed: acting ? null : _cancelWaitingOrder,
                        icon: const Icon(Icons.cancel_outlined),
                        label: const Text('Cancelar da fila'),
                      ),
                    ],
                  ],
                ),
              ),
            ),
            const SizedBox(height: 8),
          ],
          if (review)
            Card(
              color: Theme.of(context).colorScheme.errorContainer,
              child: ListTile(
                leading: const Icon(Icons.warning_amber),
                title: const Text('REVIEW NM'),
                subtitle: Text(
                  (data!['review_reason'] as String?) ??
                      'Confirme notícias/decisão antes de aprovar (mesmo com auto).',
                ),
              ),
            ),
          Wrap(
            spacing: 8,
            children: [
              Chip(
                label: Text(
                  kind == 'hv_dip'
                      ? 'HIGH-VOL NM'
                      : (isSwing ? 'SWING' : 'INCOME'),
                ),
              ),
              Chip(label: Text(assetClass.toUpperCase())),
              if (!isSwing) Chip(label: Text(freq)),
              if (letter != null) Chip(label: Text('Score $letter')),
              if (review) const Chip(label: Text('REVIEW')),
              if (isHv && isLiveSuggestion(metrics))
                const Chip(label: Text('VIVA')),
              if (catalyst != null)
                Chip(label: Text('CATALISTA ${catalyst['event_type'] ?? ''}')),
              if (h1Label != null) Chip(label: Text(h1Label)),
            ],
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
          Text(
            isSwing
                ? 'Score $letter (${formatScore(data!['score'])})'
                : 'Score: ${formatScore(data!['score'])}',
            style: Theme.of(context).textTheme.headlineSmall,
          ),
          Text(
            'Status: ${data!['status']} · Valor proposto: ${formatMoney(data!['proposed_amount_brl'], currency: currency)}',
          ),
          if (isSwing) ...[
            const SizedBox(height: 8),
            Text('Entrada: ${formatPrice(data!['entry_price'])}'),
            Text('Stop: ${formatPrice(data!['stop_price'])}'),
            Text('Alvo: ${formatPrice(data!['target_price'])}'),
            Text('R:R: ${formatRatio(data!['r_multiple'])}'),
            if (isHv && setupLow != null) Text('Piso setup: ${formatPrice(setupLow)}'),
            if (isHv && dipPct != null) Text('Dip (D-1): ${formatPct(dipPct)}'),
            if (isHv && dipLive != null)
              Text(
                'Dip ao vivo: ${formatPct(dipLive)}'
                '${refreshedAt != null ? ' · atualizado ${formatRefreshedAt(refreshedAt)}' : ''}',
              ),
            if (isHv && tranche != null) Text('Tranche: $tranche'),
            if (letter == 'C' && !isHv)
              const Padding(
                padding: EdgeInsets.only(top: 8),
                child: Text(
                  'Score C: só paper. Live Inter bloqueado pelos freios.',
                  style: TextStyle(fontSize: 13),
                ),
              ),
            const SizedBox(height: 16),
            Text('Gráfico (diário)', style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: 8),
            InteractiveCandlestickChart(
              bars: bars,
              entry: asNum(data!['entry_price']),
              setupLow: setupLow,
            ),
          ],
          if (metrics['effective_yield'] != null)
            Text(
              'Yield efetivo: ${formatPct(metrics['effective_yield'])}'
              '${metrics['gross_yield'] != null ? ' (bruto ${formatPct(metrics['gross_yield'])})' : ''}',
            ),
          if (llm != null && llm.isNotEmpty) ...[
            const SizedBox(height: 16),
            Text('Resumo (LLM)', style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: 8),
            SelectableText(llm),
          ],
          const SizedBox(height: 16),
          Text('Explicação do preço', style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: 8),
          SelectableText(data!['price_explanation'] as String? ?? ''),
          const SizedBox(height: 16),
          Text('Métricas', style: Theme.of(context).textTheme.titleMedium),
          ...metrics.entries
              .where((e) => !isSwing || !swingHeaderMetricKeys.contains(e.key))
              .map((e) => Padding(
                    padding: const EdgeInsets.only(top: 4),
                    child: Text('${metricLabel(e.key)}: ${formatMetricValue(e.key, e.value)}'),
                  )),
          const SizedBox(height: 16),
          Text('Motivos (regras)', style: Theme.of(context).textTheme.titleMedium),
          ...reasons.map((r) {
            final m = r as Map<String, dynamic>;
            final ok = m['passed'] == true;
            return ListTile(
              leading: Icon(ok ? Icons.check_circle : Icons.cancel,
                  color: ok ? Colors.green : Colors.red),
              title: Text(m['rule'] as String? ?? ''),
              subtitle: Text(m['detail'] as String? ?? ''),
            );
          }),
          const SizedBox(height: 16),
          Text('Notícias relacionadas', style: Theme.of(context).textTheme.titleMedium),
          if (news.isEmpty) const Text('Nenhuma notícia vinculada a este ticker.'),
          ...news.map((n) {
            final m = n as Map<String, dynamic>;
            return ListTile(
              title: Text(m['title'] as String? ?? ''),
              subtitle: Text(m['source'] as String? ?? ''),
            );
          }),
          if (pending && canAct) ...[
            if (isHv && approveOptions != null) ...[
              const SizedBox(height: 16),
              Text('Valor da ordem', style: Theme.of(context).textTheme.titleMedium),
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
                  keyboardType: const TextInputType.numberWithOptions(decimal: true),
                  decoration: InputDecoration(
                    labelText: 'Valor US\$',
                    prefixText: 'US\$ ',
                    errorText: amountError,
                    helperText: approveOptions?['max_amount_usd'] != null
                        ? 'Máx ${formatUsd(asNum(approveOptions!['max_amount_usd'])!)} · '
                            'preço ${formatUsd(asNum(approveOptions!['live_price']) ?? asNum(data!['entry_price']))}'
                        : null,
                  ),
                  onChanged: _validateAmountInput,
                ),
              ] else ...[
                DropdownButtonFormField<double>(
                  initialValue: selectedAmountUsd,
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
                  onChanged: (v) => setState(() => selectedAmountUsd = v),
                ),
                if (_wholeShareOptions.isEmpty)
                  Text(
                    _blockReason ?? 'Nenhuma opção de ações inteiras disponível.',
                    style: TextStyle(color: Theme.of(context).colorScheme.error),
                  ),
              ],
            ],
            const SizedBox(height: 24),
            Row(
              children: [
                Expanded(
                  child: OutlinedButton(
                    onPressed: acting ? null : () => _act(false),
                    child: const Text('Rejeitar'),
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: FilledButton(
                    onPressed: (acting || !_canApproveAmount) ? null : () => _act(true),
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
      ),
    );
  }
}
