import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../app/selected_account.dart';
import '../../core/api_client.dart';
import '../../core/format.dart';
import '../../data/models/account.dart';
import '../../data/models/position.dart';
import '../../data/repositories/accounts_repository.dart';
import '../../data/repositories/portfolio_repository.dart';
import 'master_detail.dart';
import 'position_detail_dialog.dart';

/// Desktop Contas: master list of accounts + detail with portfolio snapshot.
class AccountsScreen extends StatefulWidget {
  const AccountsScreen({super.key});

  @override
  State<AccountsScreen> createState() => _AccountsScreenState();
}

class _AccountsScreenState extends State<AccountsScreen> {
  List<Account> _accounts = [];
  bool _loading = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    final sel = context.read<SelectedAccount>();
    try {
      final repo = AccountsRepository(context.read<ApiClient>());
      _accounts = await repo.list();
      // Keep the selected account in sync if it still exists.
      if (sel.current != null &&
          !_accounts.any((a) => a.id == sel.current!.id)) {
        sel.select(null);
      }
    } catch (e) {
      _error = formatApiError(e);
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _renameAccount(Account a) async {
    final ctrl = TextEditingController(text: a.name);
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Renomear conta'),
        content: TextField(
          controller: ctrl,
          autofocus: true,
          decoration: const InputDecoration(labelText: 'Nome'),
        ),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(ctx, false),
              child: const Text('Cancelar')),
          FilledButton(
              onPressed: () => Navigator.pop(ctx, true),
              child: const Text('Salvar')),
        ],
      ),
    );
    if (ok != true || !mounted) return;
    final name = ctrl.text.trim();
    if (name.isEmpty) return;
    final sel = context.read<SelectedAccount>();
    try {
      final updated =
          await AccountsRepository(context.read<ApiClient>()).rename(a.id, name);
      if (sel.current?.id == a.id) sel.select(updated);
      await _load();
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Falha ao renomear: $e')),
        );
      }
    }
  }

  Future<void> _deleteAccount(Account a) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text('Excluir "${a.name}"?'),
        content: const Text(
          'Esta ação apaga a conta e todo o histórico (posições, ordens, '
          'sugestões e observação). Não pode ser desfeita.',
        ),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(ctx, false),
              child: const Text('Cancelar')),
          FilledButton(
            style: FilledButton.styleFrom(
              backgroundColor: Theme.of(ctx).colorScheme.error,
            ),
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('Excluir definitivamente'),
          ),
        ],
      ),
    );
    if (ok != true || !mounted) return;
    final sel = context.read<SelectedAccount>();
    try {
      await AccountsRepository(context.read<ApiClient>()).delete(a.id);
      if (sel.current?.id == a.id) sel.select(null);
      await _load();
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Falha ao excluir: $e')),
        );
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final selected = context.watch<SelectedAccount>().current;
    return Scaffold(
      appBar: AppBar(
        title: const Text('Contas'),
        actions: [
          IconButton(
            tooltip: 'Atualizar',
            onPressed: _load,
            icon: const Icon(Icons.refresh),
          ),
        ],
      ),
      body: _loading
          ? const PaneLoading()
          : _error != null
              ? PaneError(message: _error!, onRetry: _load)
              : MasterDetail(
                  master: _AccountList(
                    accounts: _accounts,
                    selectedId: selected?.id,
                    onSelect: (a) => context.read<SelectedAccount>().select(a),
                  ),
                  detail: selected == null
                      ? const PaneEmpty(
                          message: 'Selecione uma conta à esquerda.',
                          icon: Icons.account_balance_wallet_outlined,
                        )
                      : _AccountDetail(
                          account: selected,
                          onRename: () => _renameAccount(selected),
                          onDelete: () => _deleteAccount(selected),
                        ),
                ),
    );
  }
}

class _AccountList extends StatelessWidget {
  const _AccountList({
    required this.accounts,
    required this.selectedId,
    required this.onSelect,
  });

  final List<Account> accounts;
  final String? selectedId;
  final void Function(Account) onSelect;

  @override
  Widget build(BuildContext context) {
    if (accounts.isEmpty) {
      return const PaneEmpty(message: 'Nenhuma conta.');
    }
    return ListView.separated(
      itemCount: accounts.length,
      separatorBuilder: (_, __) => const Divider(height: 1),
      itemBuilder: (context, i) {
        final a = accounts[i];
        final isUs = a.currency.toUpperCase() == 'USD' ||
            a.brokerCode.toLowerCase() == 'alpaca';
        return ListTile(
          selected: a.id == selectedId,
          selectedTileColor: Theme.of(context).colorScheme.primaryContainer,
          title: Text(a.name),
          subtitle: Text(
              '${isUs ? 'EUA · USD' : 'Brasil · BRL'} · ${a.myRole ?? '—'}'),
          trailing: Text(
            a.executionMode,
            style: Theme.of(context).textTheme.labelSmall,
          ),
          onTap: () => onSelect(a),
        );
      },
    );
  }
}

class _AccountDetail extends StatefulWidget {
  const _AccountDetail({
    required this.account,
    required this.onRename,
    required this.onDelete,
  });

  final Account account;
  final VoidCallback onRename;
  final VoidCallback onDelete;

  @override
  State<_AccountDetail> createState() => _AccountDetailState();
}

class _AccountDetailState extends State<_AccountDetail> {
  Portfolio? _portfolio;
  List<Position> _positions = [];
  bool _loading = true;
  bool _acting = false;
  String? _error;

  bool get _canAct {
    final role = widget.account.myRole;
    return role == 'owner' || role == 'operator';
  }

  bool get _isOwner => widget.account.myRole == 'owner';

  late bool _paused = widget.account.automationPaused;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void didUpdateWidget(covariant _AccountDetail oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.account.id != widget.account.id) {
      _paused = widget.account.automationPaused;
      _load();
    } else if (oldWidget.account.automationPaused != widget.account.automationPaused) {
      _paused = widget.account.automationPaused;
    }
  }

  Future<void> _toggleAutomation(bool paused) async {
    setState(() => _paused = paused);
    try {
      final updated = await AccountsRepository(context.read<ApiClient>())
          .setAutomationPaused(widget.account.id, paused);
      if (mounted) {
        final sel = context.read<SelectedAccount>();
        if (sel.current?.id == widget.account.id) sel.select(updated);
      }
    } catch (e) {
      if (mounted) {
        setState(() => _paused = !paused);
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Falha ao alterar automação: $e')),
        );
      }
    }
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final api = context.read<ApiClient>();
      final pfRepo = PortfolioRepository(api);
      _portfolio = await pfRepo.getPortfolio(widget.account.id);
      _positions =
          await pfRepo.listPositions(widget.account.id, status: 'open');
    } catch (e) {
      _error = formatApiError(e);
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _closeAll() async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Fechar todas as posições?'),
        content: const Text(
          'Vende todas as posições abertas à cotação ao vivo.',
        ),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(ctx, false),
              child: const Text('Voltar')),
          FilledButton(
              onPressed: () => Navigator.pop(ctx, true),
              child: const Text('Fechar todas')),
        ],
      ),
    );
    if (ok != true || !mounted) return;
    setState(() => _acting = true);
    try {
      await PortfolioRepository(context.read<ApiClient>())
          .closeAllPositions(widget.account.id);
      await _load();
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Falha ao fechar: $e')),
        );
      }
    } finally {
      if (mounted) setState(() => _acting = false);
    }
  }

  Future<void> _openPosition(Position p) async {
    final closed = await showDialog<bool>(
      context: context,
      builder: (_) => PositionDetailDialog(
        position: p,
        isUs: widget.account.currency.toUpperCase() == 'USD',
        canAct: _canAct,
      ),
    );
    if (closed == true && mounted) await _load();
  }

  @override
  Widget build(BuildContext context) {
    final a = widget.account;
    final isUs = a.currency.toUpperCase() == 'USD';
    String money(dynamic v) => formatMoney(v, currency: isUs ? 'USD' : 'BRL');
    return ListView(
      padding: const EdgeInsets.all(20),
      children: [
        Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(a.name, style: Theme.of(context).textTheme.headlineSmall),
                  const SizedBox(height: 4),
                  Text(
                    '${isUs ? 'EUA' : 'Brasil'} · ${a.executionMode} · ${a.brokerCode} · papel ${a.myRole ?? '—'}',
                    style: Theme.of(context).textTheme.bodyMedium,
                  ),
                ],
              ),
            ),
            if (_isOwner) ...[
              IconButton(
                tooltip: 'Renomear',
                onPressed: widget.onRename,
                icon: const Icon(Icons.edit_outlined),
              ),
              IconButton(
                tooltip: 'Excluir conta',
                onPressed: widget.onDelete,
                icon: Icon(Icons.delete_outline,
                    color: Theme.of(context).colorScheme.error),
              ),
            ],
          ],
        ),
        const SizedBox(height: 8),
        Card(
          margin: EdgeInsets.zero,
          child: SwitchListTile(
            value: _paused,
            onChanged: _canAct ? _toggleAutomation : null,
            title: const Text('Pausar automação'),
            subtitle: Text(
              _paused
                  ? 'Compras e vendas automáticas suspensas nesta conta.'
                  : 'Compra/venda automáticas ativas (sujeitas às regras).',
            ),
            secondary: Icon(
              _paused ? Icons.pause_circle : Icons.play_circle_outline,
              color: _paused ? Colors.orange.shade800 : Colors.green.shade700,
            ),
          ),
        ),
        const SizedBox(height: 16),
        if (_loading)
          const PaneLoading()
        else if (_error != null)
          PaneError(message: _error!, onRetry: _load)
        else if (_portfolio != null) ...[
          _StatGrid(
            items: [
              _Stat('Equity', money(_portfolio!.equityBrl)),
              _Stat('Caixa', money(_portfolio!.cashBrl)),
              _Stat('Investido', money(_portfolio!.investedOpenBrl)),
              _Stat('P&L dia', money(_portfolio!.realizedPnlDayBrl)),
              _Stat('Não realizado', money(_portfolio!.unrealizedPnlBrl)),
              _Stat('Posições', '${_portfolio!.openPositions}'),
            ],
          ),
          const SizedBox(height: 16),
          Row(
            children: [
              Expanded(
                child: Text('Posições abertas',
                    style: Theme.of(context).textTheme.titleMedium),
              ),
              if (_canAct && _positions.isNotEmpty)
                TextButton.icon(
                  onPressed: _acting ? null : _closeAll,
                  icon: const Icon(Icons.sell_outlined, size: 18),
                  label: const Text('Fechar todas'),
                ),
            ],
          ),
          const SizedBox(height: 8),
          if (_positions.isEmpty)
            const Text('Nenhuma posição aberta.')
          else
            ..._positions.map(
              (p) => Card(
                child: ListTile(
                  onTap: () => _openPosition(p),
                  title: Text('${p.ticker} · ${formatQty(p.quantity)}'),
                  subtitle: Text(
                    '${p.strategyKind} · entrada ${formatPrice(p.entryPrice)}'
                    '${p.markPrice != null ? ' · ${formatPrice(p.markPrice)}' : ''}',
                  ),
                  trailing: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      if (p.unrealizedPnlBrl != null)
                        Text(
                          '${money(p.unrealizedPnlBrl)}'
                          '${p.unrealizedPnlPct != null ? ' (${formatPct(p.unrealizedPnlPct)})' : ''}',
                          style: TextStyle(
                            fontWeight: FontWeight.w700,
                            color: p.unrealizedPnlBrl! >= 0
                                ? Colors.green.shade700
                                : Colors.red.shade700,
                          ),
                        ),
                      const Icon(Icons.chevron_right, size: 16),
                    ],
                  ),
                ),
              ),
            ),
        ],
      ],
    );
  }
}

class _Stat {
  const _Stat(this.label, this.value);
  final String label;
  final String value;
}

class _StatGrid extends StatelessWidget {
  const _StatGrid({required this.items});

  final List<_Stat> items;

  @override
  Widget build(BuildContext context) {
    return Wrap(
      spacing: 12,
      runSpacing: 12,
      children: items
          .map(
            (s) => Card(
              child: SizedBox(
                width: 150,
                child: Padding(
                  padding: const EdgeInsets.all(12),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        s.label,
                        style: Theme.of(context).textTheme.labelMedium,
                      ),
                      const SizedBox(height: 4),
                      Text(
                        s.value,
                        style: Theme.of(context)
                            .textTheme
                            .titleMedium
                            ?.copyWith(fontWeight: FontWeight.w700),
                      ),
                    ],
                  ),
                ),
              ),
            ),
          )
          .toList(),
    );
  }
}
