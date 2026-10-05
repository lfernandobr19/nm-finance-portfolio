import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../core/api_client.dart';
import '../../core/format.dart';
import '../../data/models/position.dart';
import '../../data/repositories/portfolio_repository.dart';

/// Detalhe completo de uma posição aberta + ações de venda (mercado ou preço
/// manual). Retorna `true` via pop quando a posição é fechada.
class PositionDetailDialog extends StatefulWidget {
  const PositionDetailDialog({
    super.key,
    required this.position,
    required this.isUs,
    required this.canAct,
  });

  final Position position;
  final bool isUs;
  final bool canAct;

  @override
  State<PositionDetailDialog> createState() => _PositionDetailDialogState();
}

class _PositionDetailDialogState extends State<PositionDetailDialog> {
  bool _acting = false;
  bool _manualMode = false;
  final _priceController = TextEditingController();

  String get _ccy => widget.isUs ? 'USD' : 'BRL';

  @override
  void dispose() {
    _priceController.dispose();
    super.dispose();
  }

  Future<void> _close({required String reason, double? price}) async {
    final p = widget.position;
    setState(() => _acting = true);
    try {
      await PortfolioRepository(context.read<ApiClient>()).closePosition(
        p.accountId,
        p.id,
        reason: reason,
        price: price,
      );
      if (mounted) Navigator.of(context).pop(true);
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Falha ao vender: $e')),
        );
        setState(() => _acting = false);
      }
    }
  }

  Future<void> _suggestMore() async {
    final p = widget.position;
    setState(() => _acting = true);
    try {
      final sug = await PortfolioRepository(context.read<ApiClient>())
          .suggestMore(p.accountId, p.id);
      if (mounted) {
        final tranche = sug['tranche_index'] ?? '?';
        final auto = sug['status'] == 'auto_approved';
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(
              'Sugestão de compra gerada (tranche $tranche) — '
              '${auto ? 'aprovada automaticamente' : 'aguardando revisão'}',
            ),
          ),
        );
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Falha ao comprar mais: $e')),
        );
      }
    } finally {
      if (mounted) setState(() => _acting = false);
    }
  }

  Future<void> _confirmMarket() async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Vender a mercado?'),
        content: Text(
          'Fechar ${widget.position.ticker} à cotação ao vivo '
          '($_ccy).',
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Voltar')),
          FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Vender')),
        ],
      ),
    );
    if (ok != true || !mounted) return;
    await _close(reason: 'market');
  }

  Future<void> _confirmManual() async {
    final price = double.tryParse(_priceController.text.replaceAll(',', '.'));
    if (price == null || price <= 0) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Informe um preço de saída válido.')),
      );
      return;
    }
    await _close(reason: 'manual', price: price);
  }

  @override
  Widget build(BuildContext context) {
    final p = widget.position;
    return AlertDialog(
      title: Text(p.ticker),
      content: SizedBox(
        width: 420,
        child: ListView(
          shrinkWrap: true,
          children: [
            Wrap(
              spacing: 8,
              runSpacing: 4,
              children: [
                Chip(label: Text(p.strategyKind.toUpperCase())),
                if (p.priceAlert != null) Chip(label: Text(p.priceAlert!)),
                if (p.exitState != null && p.exitState != 'normal')
                  Chip(label: Text(p.exitState!)),
                if (p.latched5 == true) const Chip(label: Text('LATCH +5%')),
                if (p.protectActive == true) const Chip(label: Text('PROTECT')),
              ],
            ),
            const SizedBox(height: 8),
            _kv('Quantidade', formatQty(p.quantity)),
            _kv('Entrada', formatPrice(p.entryPrice)),
            if (p.avgEntryPrice != null)
              _kv('Entrada média', formatPrice(p.avgEntryPrice)),
            if (p.markPrice != null) _kv('Mark', formatPrice(p.markPrice)),
            if (p.stopPrice != null) _kv('Stop', formatPrice(p.stopPrice)),
            if (p.targetPrice != null) _kv('Alvo', formatPrice(p.targetPrice)),
            if (p.setupLow != null) _kv('Piso setup', formatPrice(p.setupLow)),
            _kv('Tranche', '${p.trancheIndex}'),
            if (p.costBrl != null)
              _kv('Custo', formatMoney(p.costBrl, currency: _ccy)),
            if (p.marketValueBrl != null)
              _kv('Valor a mercado', formatMoney(p.marketValueBrl, currency: _ccy)),
            if (p.unrealizedPnlBrl != null)
              _kv(
                'P&L não realizado',
                '${formatMoney(p.unrealizedPnlBrl, currency: _ccy)}'
                '${p.unrealizedPnlPct != null ? ' (${formatPct(p.unrealizedPnlPct)})' : ''}',
              ),
            if (p.peakUnrealizedPct != null)
              _kv('Pico não realizado', formatPct(p.peakUnrealizedPct)),
            _kv('Aberta em', _date(p.openedAt)),
            if (p.mustReviewBy != null) _kv('Review até', p.mustReviewBy!),
            if (p.daysUntilReview != null)
              _kv('Dias p/ review', '${p.daysUntilReview}'),
            if (widget.canAct) ...[
              const SizedBox(height: 16),
              if (p.strategyKind.toUpperCase() == 'HV_DIP') ...[
                FilledButton.tonalIcon(
                  onPressed: _acting ? null : _suggestMore,
                  icon: const Icon(Icons.add_shopping_cart_outlined),
                  label: const Text('Comprar mais (nova tranche)'),
                ),
                const SizedBox(height: 8),
              ],
              if (!_manualMode) ...[
                FilledButton.icon(
                  onPressed: _acting ? null : _confirmMarket,
                  icon: const Icon(Icons.sell_outlined),
                  label: const Text('Vender a mercado'),
                ),
                const SizedBox(height: 8),
                TextButton(
                  onPressed: _acting
                      ? null
                      : () => setState(() => _manualMode = true),
                  child: const Text('Vender com preço manual'),
                ),
              ] else ...[
                TextField(
                  controller: _priceController,
                  autofocus: true,
                  keyboardType:
                      const TextInputType.numberWithOptions(decimal: true),
                  decoration: InputDecoration(
                    labelText: 'Preço de saída ($_ccy)',
                    prefixText: '$_ccy ',
                  ),
                  onSubmitted: (_) => _acting ? null : _confirmManual(),
                ),
                const SizedBox(height: 8),
                Row(
                  children: [
                    TextButton(
                      onPressed: _acting
                          ? null
                          : () => setState(() => _manualMode = false),
                      child: const Text('Voltar'),
                    ),
                    const SizedBox(width: 8),
                    Expanded(
                      child: FilledButton(
                        onPressed: _acting ? null : _confirmManual,
                        child: const Text('Confirmar venda'),
                      ),
                    ),
                  ],
                ),
              ],
            ],
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: _acting ? null : () => Navigator.of(context).pop(false),
          child: const Text('Fechar'),
        ),
      ],
    );
  }

  String _date(DateTime dt) {
    final local = dt.toLocal();
    return '${local.day.toString().padLeft(2, '0')}/'
        '${local.month.toString().padLeft(2, '0')}/'
        '${local.year} ${local.hour.toString().padLeft(2, '0')}:'
        '${local.minute.toString().padLeft(2, '0')}';
  }

  Widget _kv(String label, String value) {
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
