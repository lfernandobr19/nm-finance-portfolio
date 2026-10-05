import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../app/selected_account.dart';
import '../../core/api_client.dart';
import '../../core/format.dart';
import '../../data/models/order.dart';
import '../../data/repositories/orders_repository.dart';
import 'master_detail.dart';

/// Desktop Ordens: master list of broker orders + detail with actions.
class OrdersScreen extends StatefulWidget {
  const OrdersScreen({super.key});

  @override
  State<OrdersScreen> createState() => _OrdersScreenState();
}

class _OrdersScreenState extends State<OrdersScreen> {
  List<Order> _orders = [];
  Order? _selected;
  bool _loading = false;
  String? _error;
  String _accountId = '';

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final accountId = context.watch<SelectedAccount>().accountId;
    if (_accountId != accountId) {
      _accountId = accountId;
      _selected = null;
      _reload();
    }
  }

  Future<void> _reload() async {
    if (_accountId.isEmpty) {
      setState(() {
        _orders = [];
        _selected = null;
      });
      return;
    }
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final repo = OrdersRepository(context.read<ApiClient>());
      _orders = await repo.list(_accountId);
      _orders.sort((a, b) => b.createdAt.compareTo(a.createdAt));
    } catch (e) {
      _error = formatApiError(e);
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final account = context.watch<SelectedAccount>().current;
    return Scaffold(
      appBar: AppBar(
        title: Text(account == null ? 'Ordens' : 'Ordens · ${account.name}'),
        actions: [
          if (account != null)
            IconButton(onPressed: _reload, icon: const Icon(Icons.refresh)),
        ],
      ),
      body: account == null
          ? const PaneEmpty(
              message: 'Selecione uma conta na aba Contas.',
              icon: Icons.receipt_long_outlined,
            )
          : _loading
              ? const PaneLoading()
              : _error != null
                  ? PaneError(message: _error!, onRetry: _reload)
                  : MasterDetail(
                      master: _OrderList(
                        orders: _orders,
                        selectedId: _selected?.id,
                        onSelect: (o) => setState(() => _selected = o),
                      ),
                      detail: _selected == null
                          ? const PaneEmpty(message: 'Selecione uma ordem.')
                          : _OrderPane(
                              order: _selected!,
                              onChanged: _reload,
                            ),
                    ),
    );
  }
}

class _OrderList extends StatelessWidget {
  const _OrderList({
    required this.orders,
    required this.selectedId,
    required this.onSelect,
  });

  final List<Order> orders;
  final String? selectedId;
  final void Function(Order) onSelect;

  @override
  Widget build(BuildContext context) {
    if (orders.isEmpty) {
      return const PaneEmpty(message: 'Nenhuma ordem.');
    }
    return ListView.separated(
      itemCount: orders.length,
      separatorBuilder: (_, __) => const Divider(height: 1),
      itemBuilder: (context, i) {
        final o = orders[i];
        return ListTile(
          selected: o.id == selectedId,
          dense: true,
          title: Text('${o.ticker} · ${o.status}'),
          subtitle: Text(
            '${o.side} ${formatQty(o.quantity)} @ ${formatPrice(o.limitPrice)} · ${o.executionMode}',
          ),
          onTap: () => onSelect(o),
        );
      },
    );
  }
}

class _OrderPane extends StatefulWidget {
  const _OrderPane({required this.order, required this.onChanged});

  final Order order;
  final VoidCallback onChanged;

  @override
  State<_OrderPane> createState() => _OrderPaneState();
}

class _OrderPaneState extends State<_OrderPane> {
  bool _acting = false;

  bool get _cancellable =>
      widget.order.executionMode == 'live' &&
          widget.order.status == 'awaiting_broker' ||
      const {'submitted', 'queued', 'awaiting_broker'}
          .contains(widget.order.status);

  Future<void> _markFilled() async {
    setState(() => _acting = true);
    try {
      await OrdersRepository(context.read<ApiClient>())
          .markFilled(widget.order.accountId, widget.order.id);
      widget.onChanged();
    } catch (e) {
      _snack('Falha: $e');
    } finally {
      if (mounted) setState(() => _acting = false);
    }
  }

  Future<void> _markCancelled() async {
    setState(() => _acting = true);
    try {
      await OrdersRepository(context.read<ApiClient>())
          .markCancelled(widget.order.accountId, widget.order.id);
      widget.onChanged();
    } catch (e) {
      _snack('Falha: $e');
    } finally {
      if (mounted) setState(() => _acting = false);
    }
  }

  void _snack(String msg) {
    if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(msg)));
    }
  }

  @override
  Widget build(BuildContext context) {
    final o = widget.order;
    return ListView(
      padding: const EdgeInsets.all(20),
      children: [
        Text(o.ticker, style: Theme.of(context).textTheme.headlineMedium),
        const SizedBox(height: 8),
        _kv(context, 'Status', o.status),
        _kv(context, 'Lado', o.side),
        _kv(context, 'Quantidade', formatQty(o.quantity)),
        _kv(context, 'Preço limite', formatPrice(o.limitPrice)),
        _kv(context, 'Valor', formatBrl(o.amountBrl)),
        _kv(context, 'Modo', o.executionMode),
        _kv(context, 'Corretora', o.broker),
        if (o.filledPrice != null)
          _kv(context, 'Executado', formatPrice(o.filledPrice)),
        if (o.brokerOrderId != null)
          _kv(context, 'ID corretora', o.brokerOrderId!),
        if (o.errorMessage != null) _kv(context, 'Erro', o.errorMessage!),
        const SizedBox(height: 16),
        if (_cancellable) ...[
          if (widget.order.executionMode == 'live' &&
              widget.order.status == 'awaiting_broker')
            FilledButton(
              onPressed: _acting ? null : _markFilled,
              child: const Text('Marquei como executada'),
            ),
          const SizedBox(height: 8),
          OutlinedButton.icon(
            onPressed: _acting ? null : _markCancelled,
            icon: const Icon(Icons.cancel_outlined),
            label: const Text('Cancelar da fila'),
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
