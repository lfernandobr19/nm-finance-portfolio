import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../app/selected_account.dart';
import '../../core/api_client.dart';
import '../../core/format.dart';
import '../../core/market_hours.dart';
import '../../data/models/order.dart';
import '../../data/models/suggestion.dart';
import '../../data/models/watchlist_item.dart';
import '../../data/repositories/orders_repository.dart';
import '../../data/repositories/suggestions_repository.dart';
import '../../data/repositories/watchlist_repository.dart';
import 'master_detail.dart';
import 'suggestion_detail_pane.dart';

/// Desktop Mesa: split-view with grouped master (Fila / Pendentes / Decididas)
/// and an inline full-detail pane (no "Detalhes" navigation). Requires a
/// selected account.
class DeskScreen extends StatefulWidget {
  const DeskScreen({super.key});

  @override
  State<DeskScreen> createState() => _DeskScreenState();
}

class _DeskScreenState extends State<DeskScreen> {
  List<Suggestion> _suggestions = [];
  List<Order> _queue = [];
  List<WatchlistItem> _watchlist = [];
  Suggestion? _selected;
  bool _loading = false;
  bool _cancelling = false;
  bool _watchBusy = false;
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
    final accountId = _accountId;
    if (accountId.isEmpty) {
      setState(() {
        _suggestions = [];
        _queue = [];
        _watchlist = [];
        _selected = null;
        _error = null;
      });
      return;
    }
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final api = context.read<ApiClient>();
      final suggestions = await SuggestionsRepository(api).list(accountId);
      suggestions.sort((a, b) {
        final aPending = a.status == 'pending' ? 0 : 1;
        final bPending = b.status == 'pending' ? 0 : 1;
        if (aPending != bPending) return aPending - bPending;
        return b.createdAt.compareTo(a.createdAt);
      });
      final orders = await OrdersRepository(api).list(accountId);
      final watchlist = await WatchlistRepository(api).list(accountId);
      _suggestions = suggestions;
      _watchlist = watchlist;
      _queue = orders
          .where((o) =>
              o.status == 'submitted' ||
              o.status == 'queued' ||
              o.status == 'awaiting_broker')
          .toList();
      _queue.sort((a, b) => b.createdAt.compareTo(a.createdAt));
      if (_selected != null) {
        final updated =
            suggestions.where((s) => s.id == _selected!.id).toList();
        _selected = updated.isEmpty ? null : updated.first;
      }
    } catch (e) {
      _error = formatApiError(e);
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _cancelQueue(Order o) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Cancelar ordem?'),
        content: Text(
            'Remove ${o.ticker} · ${formatQty(o.quantity)} da fila e cancela na corretora (se já enviada).'),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(ctx, false),
              child: const Text('Voltar')),
          FilledButton(
              onPressed: () => Navigator.pop(ctx, true),
              child: const Text('Cancelar ordem')),
        ],
      ),
    );
    if (ok != true || !mounted) return;
    setState(() => _cancelling = true);
    try {
      await OrdersRepository(context.read<ApiClient>())
          .markCancelled(o.accountId, o.id);
      await _reload();
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Falha ao cancelar: $e')),
        );
      }
    } finally {
      if (mounted) setState(() => _cancelling = false);
    }
  }

  Future<void> _toggleWatch(Suggestion s) async {
    if (_watchBusy) return;
    setState(() => _watchBusy = true);
    try {
      final repo = WatchlistRepository(context.read<ApiClient>());
      final watched = _watchlist.any((w) => w.ticker == s.ticker);
      if (watched) {
        await repo.remove(s.accountId, s.ticker);
      } else {
        await repo.add(s.accountId, s.ticker, note: s.strategyKind);
      }
      await _reload();
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Falha na observação: $e')),
        );
      }
    } finally {
      if (mounted) setState(() => _watchBusy = false);
    }
  }

  Future<void> _removeWatch(WatchlistItem w) async {
    if (_watchBusy) return;
    setState(() => _watchBusy = true);
    try {
      await WatchlistRepository(context.read<ApiClient>())
          .remove(w.accountId, w.ticker);
      await _reload();
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Falha ao remover: $e')),
        );
      }
    } finally {
      if (mounted) setState(() => _watchBusy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final account = context.watch<SelectedAccount>().current;
    final myRole = account?.myRole ?? '';
    return Scaffold(
      appBar: AppBar(
        title: Text(account == null ? 'Mesa' : 'Mesa · ${account.name}'),
        actions: [
          if (account != null)
            IconButton(
              tooltip: 'Atualizar',
              onPressed: _reload,
              icon: const Icon(Icons.refresh),
            ),
        ],
      ),
      body: account == null
          ? const PaneEmpty(
              message: 'Selecione uma conta na aba Contas para abrir a mesa.',
              icon: Icons.space_dashboard_outlined,
            )
          : _loading
              ? const PaneLoading()
              : _error != null
                  ? PaneError(message: _error!, onRetry: _reload)
                  : MasterDetail(
                      master: _DeskMasterList(
                        queue: _queue,
                        suggestions: _suggestions,
                        watchlist: _watchlist,
                        selectedId: _selected?.id,
                        cancelling: _cancelling,
                        watchBusy: _watchBusy,
                        onSelect: (s) => setState(() => _selected = s),
                        onCancelQueue: _cancelQueue,
                        onToggleWatch: _toggleWatch,
                        onRemoveWatch: _removeWatch,
                      ),
                      detail: _selected == null
                          ? const PaneEmpty(
                              message: 'Selecione uma sugestão.',
                              icon: Icons.lightbulb_outline,
                            )
                          : SuggestionDetailPane(
                              accountId: _accountId,
                              suggestion: _selected!,
                              myRole: myRole,
                              onChanged: _reload,
                            ),
                    ),
    );
  }
}

class _DeskMasterList extends StatelessWidget {
  const _DeskMasterList({
    required this.queue,
    required this.suggestions,
    required this.watchlist,
    required this.selectedId,
    required this.cancelling,
    required this.watchBusy,
    required this.onSelect,
    required this.onCancelQueue,
    required this.onToggleWatch,
    required this.onRemoveWatch,
  });

  final List<Order> queue;
  final List<Suggestion> suggestions;
  final List<WatchlistItem> watchlist;
  final String? selectedId;
  final bool cancelling;
  final bool watchBusy;
  final void Function(Suggestion) onSelect;
  final void Function(Order) onCancelQueue;
  final void Function(Suggestion) onToggleWatch;
  final void Function(WatchlistItem) onRemoveWatch;

  @override
  Widget build(BuildContext context) {
    final pending =
        suggestions.where((s) => s.status == 'pending').toList();
    final decided =
        suggestions.where((s) => s.status != 'pending').toList();
    final watchedTickers = watchlist.map((w) => w.ticker).toSet();

    if (queue.isEmpty && suggestions.isEmpty && watchlist.isEmpty) {
      return const PaneEmpty(message: 'Nenhuma sugestão.');
    }

    final children = <Widget>[];
    if (queue.isNotEmpty) {
      children.add(_sectionHeader(context, 'Fila', count: queue.length));
      children.addAll(queue.map((o) => _QueueTile(
            order: o,
            cancelling: cancelling,
            onCancel: () => onCancelQueue(o),
          )));
    }
    if (pending.isNotEmpty) {
      children.add(_sectionHeader(context, 'Pendentes', count: pending.length));
      children.addAll(pending.map((s) => _SuggestionTile(
            suggestion: s,
            selected: s.id == selectedId,
            watched: watchedTickers.contains(s.ticker),
            watchBusy: watchBusy,
            onTap: () => onSelect(s),
            onToggleWatch: () => onToggleWatch(s),
          )));
    }
    if (decided.isNotEmpty) {
      children.add(_sectionHeader(context, 'Decididas', count: decided.length));
      children.addAll(decided.map((s) => _SuggestionTile(
            suggestion: s,
            selected: s.id == selectedId,
            onTap: () => onSelect(s),
          )));
    }
    if (watchlist.isNotEmpty) {
      children.add(_sectionHeader(context, 'Observação', count: watchlist.length));
      children.addAll(watchlist.map((w) => _WatchlistTile(
            item: w,
            onRemove: () => onRemoveWatch(w),
          )));
    }

    return ListView(
      children: children,
    );
  }

  Widget _sectionHeader(BuildContext context, String title, {int? count}) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
      color: Theme.of(context).colorScheme.surfaceContainerHighest,
      child: Text(
        count != null ? '$title ($count)' : title,
        style: Theme.of(context)
            .textTheme
            .labelLarge
            ?.copyWith(fontWeight: FontWeight.w700),
      ),
    );
  }
}

class _QueueTile extends StatelessWidget {
  const _QueueTile({
    required this.order,
    required this.cancelling,
    required this.onCancel,
  });

  final Order order;
  final bool cancelling;
  final VoidCallback onCancel;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final o = order;
    final label = orderWaitingLabel(_orderToMap(o));
    final detail = orderWaitingDetail(_orderToMap(o));
    return ListTile(
      leading: CircleAvatar(
        backgroundColor: scheme.primaryContainer,
        child: Icon(Icons.hourglass_top, color: scheme.onPrimaryContainer, size: 20),
      ),
      title: Text('${o.ticker} · ${formatQty(o.quantity)}'),
      subtitle: Text(
        'Limit ${formatPrice(o.limitPrice)} · ${formatMoney(o.amountBrl)}\n$label'
        '${detail != null ? '\n$detail' : ''}',
      ),
      isThreeLine: true,
      trailing: IconButton(
        tooltip: 'Cancelar da fila',
        icon: Icon(Icons.cancel_outlined, color: scheme.error),
        onPressed: cancelling ? null : onCancel,
      ),
    );
  }

  Map<String, dynamic> _orderToMap(Order o) => {
        'status': o.status,
        'error_message': o.errorMessage,
        'execution_payload': o.executionPayload,
      };
}

class _SuggestionTile extends StatelessWidget {
  const _SuggestionTile({
    required this.suggestion,
    required this.selected,
    required this.onTap,
    this.watched = false,
    this.watchBusy = false,
    this.onToggleWatch,
  });

  final Suggestion suggestion;
  final bool selected;
  final VoidCallback onTap;
  final bool watched;
  final bool watchBusy;
  final VoidCallback? onToggleWatch;

  @override
  Widget build(BuildContext context) {
    final s = suggestion;
    final pending = s.status == 'pending';
    return ListTile(
      selected: selected,
      selectedTileColor: Theme.of(context).colorScheme.primaryContainer,
      dense: true,
      title: Row(
        children: [
          Expanded(child: Text(s.ticker)),
          if (s.strategyKind == 'swing' || s.strategyKind == 'hv_dip')
            Text(
              s.swingScoreLetter ?? '?',
              style: Theme.of(context).textTheme.labelLarge,
            ),
        ],
      ),
      subtitle: Text(
        '${formatScore(s.score)} · ${pending ? 'pendente' : s.status}'
        '\n${formatMoney(s.proposedAmountBrl, currency: s.strategyKind == 'hv_dip' ? 'USD' : 'BRL')}',
      ),
      isThreeLine: true,
      trailing: pending
          ? Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                IconButton(
                  tooltip: watched ? 'Remover da observação' : 'Adicionar à observação',
                  visualDensity: VisualDensity.compact,
                  onPressed: watchBusy ? null : onToggleWatch,
                  icon: Icon(
                    watched ? Icons.star : Icons.star_border,
                    size: 20,
                    color: watched ? Colors.amber.shade700 : null,
                  ),
                ),
                const Icon(Icons.circle, size: 10, color: Colors.green),
              ],
            )
          : const Icon(Icons.chevron_right, size: 16),
      onTap: onTap,
    );
  }
}

class _WatchlistTile extends StatelessWidget {
  const _WatchlistTile({
    required this.item,
    required this.onRemove,
  });

  final WatchlistItem item;
  final VoidCallback onRemove;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final price = item.price;
    final change = item.changePct;
    final up = change != null && change >= 0;
    return ListTile(
      dense: true,
      leading: CircleAvatar(
        backgroundColor: scheme.secondaryContainer,
        child: Icon(Icons.visibility_outlined,
            color: scheme.onSecondaryContainer, size: 20),
      ),
      title: Text(item.ticker),
      subtitle: Text(
        price == null
            ? 'Aguardando cotação'
            : '${formatPrice(price)} · ${formatMoney(price, currency: item.currency)}',
      ),
      trailing: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          if (change != null)
            Padding(
              padding: const EdgeInsets.only(right: 4),
              child: Text(
                '${change >= 0 ? '+' : ''}${formatPct(change)}',
                style: TextStyle(
                  color: up ? Colors.green.shade700 : Colors.red.shade700,
                  fontWeight: FontWeight.w700,
                  fontSize: 13,
                ),
              ),
            ),
          IconButton(
            tooltip: 'Remover da observação',
            visualDensity: VisualDensity.compact,
            onPressed: onRemove,
            icon: const Icon(Icons.close, size: 18),
          ),
        ],
      ),
    );
  }
}
