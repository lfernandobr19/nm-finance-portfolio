import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';

import '../../core/api_client.dart';
import '../../core/format.dart';

class OrdersPage extends StatefulWidget {
  const OrdersPage({super.key, required this.accountId});

  final String accountId;

  @override
  State<OrdersPage> createState() => _OrdersPageState();
}

class _OrdersPageState extends State<OrdersPage> {
  List<dynamic> orders = [];
  bool loading = true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() => loading = true);
    orders = await context.read<ApiClient>().getList('/accounts/${widget.accountId}/orders');
    if (mounted) setState(() => loading = false);
  }

  Future<void> _openDetail(Map<String, dynamic> order) async {
    await Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) => OrderDetailPage(
          accountId: widget.accountId,
          orderId: order['id'] as String,
        ),
      ),
    );
    await _load();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Ordens')),
      body: loading
          ? const Center(child: CircularProgressIndicator())
          : RefreshIndicator(
              onRefresh: _load,
              child: ListView.builder(
                itemCount: orders.length,
                itemBuilder: (context, i) {
                  final o = orders[i] as Map<String, dynamic>;
                  return Card(
                    margin: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                    child: ListTile(
                      title: Text('${o['ticker']} · ${o['status']}'),
                      subtitle: Text(
                        '${o['execution_mode']} · ${formatQty(o['quantity'])} cotas @ ${formatBrl(o['limit_price'])}\n'
                        '${formatBrl(o['amount_brl'])} · ${o['broker']}',
                      ),
                      isThreeLine: true,
                      trailing: const Icon(Icons.chevron_right),
                      onTap: () => _openDetail(o),
                    ),
                  );
                },
              ),
            ),
    );
  }
}

class OrderDetailPage extends StatefulWidget {
  const OrderDetailPage({
    super.key,
    required this.accountId,
    required this.orderId,
    this.canCancel = false,
  });

  final String accountId;
  final String orderId;
  final bool canCancel;

  @override
  State<OrderDetailPage> createState() => _OrderDetailPageState();
}

class _OrderDetailPageState extends State<OrderDetailPage> {
  Map<String, dynamic>? order;
  bool loading = true;
  bool acting = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    order = await context.read<ApiClient>().getMap(
          '/accounts/${widget.accountId}/orders/${widget.orderId}',
        );
    if (mounted) setState(() => loading = false);
  }

  Future<void> _markFilled() async {
    setState(() => acting = true);
    await context.read<ApiClient>().post(
      '/accounts/${widget.accountId}/orders/${widget.orderId}/mark-filled',
      {},
    );
    await _load();
    setState(() => acting = false);
  }

  Future<void> _markCancelled() async {
    final ticker = order?['ticker'] as String? ?? 'ordem';
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Cancelar ordem?'),
        content: Text('Remove $ticker da fila e cancela na corretora.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Voltar')),
          FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Cancelar')),
        ],
      ),
    );
    if (ok != true || !mounted) return;

    setState(() => acting = true);
    try {
      await context.read<ApiClient>().post(
        '/accounts/${widget.accountId}/orders/${widget.orderId}/mark-cancelled',
        {},
      );
      await _load();
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('$ticker removida da fila')),
        );
        Navigator.of(context).pop();
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Falha: $e')),
        );
      }
    } finally {
      if (mounted) setState(() => acting = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    if (loading || order == null) {
      return const Scaffold(body: Center(child: CircularProgressIndicator()));
    }
    final payload = (order!['execution_payload'] as Map<String, dynamic>?) ?? {};
    final hbText = payload['hb_text'] as String?;
    final liveAwaiting =
        order!['execution_mode'] == 'live' && order!['status'] == 'awaiting_broker';
    final cancellable = widget.canCancel ||
        liveAwaiting ||
        const {'submitted', 'queued', 'awaiting_broker'}.contains(order!['status']);

    return Scaffold(
      appBar: AppBar(title: Text(order!['ticker'] as String)),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Text('Status: ${order!['status']}', style: Theme.of(context).textTheme.titleMedium),
          Text('Modo: ${order!['execution_mode']} · Corretora: ${order!['broker']}'),
          Text('Qtd: ${formatQty(order!['quantity'])} @ ${formatBrl(order!['limit_price'])}'),
          Text('Valor: ${formatBrl(order!['amount_brl'])}'),
          if (order!['broker_order_id'] != null)
            Text('ID corretora: ${order!['broker_order_id']}'),
          if (order!['filled_price'] != null)
            Text('Preço executado: ${formatBrl(order!['filled_price'])}'),
          if (order!['error_message'] != null)
            Text('Erro: ${order!['error_message']}',
                style: TextStyle(color: Theme.of(context).colorScheme.error)),
          if (payload['instructions'] != null) ...[
            const SizedBox(height: 16),
            Text('Instruções', style: Theme.of(context).textTheme.titleMedium),
            Text(payload['instructions'] as String),
          ],
          if (hbText != null) ...[
            const SizedBox(height: 12),
            SelectableText(hbText),
            const SizedBox(height: 8),
            OutlinedButton.icon(
              onPressed: () async {
                await Clipboard.setData(ClipboardData(text: hbText));
                if (context.mounted) {
                  ScaffoldMessenger.of(context).showSnackBar(
                    const SnackBar(content: Text('Copiado para colar no Inter HB')),
                  );
                }
              },
              icon: const Icon(Icons.copy),
              label: const Text('Copiar para o Inter'),
            ),
          ],
          if (cancellable) ...[
            const SizedBox(height: 24),
            if (liveAwaiting)
              FilledButton(
                onPressed: acting ? null : _markFilled,
                child: const Text('Marquei como executada no Inter'),
              ),
            if (liveAwaiting) const SizedBox(height: 8),
            OutlinedButton.icon(
              onPressed: acting ? null : _markCancelled,
              icon: const Icon(Icons.cancel_outlined),
              label: const Text('Cancelar da fila'),
            ),
          ],
        ],
      ),
    );
  }
}
