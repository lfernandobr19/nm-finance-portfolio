import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../core/api_client.dart';
import '../../core/format.dart';
import '../../core/market_hours.dart';
import '../../core/pnl_line_chart.dart';
import '../../data/models/watchlist_item.dart';
import '../../data/repositories/watchlist_repository.dart';
import '../accounts/members_page.dart';
import '../news/news_page.dart';
import '../orders/orders_page.dart';
import '../settings/settings_page.dart';
import '../day_trade/day_trade_study_page.dart';
import 'desk/desk_account_sheet.dart';
import 'desk/desk_market_sheet.dart';
import 'desk/desk_tab_scaffold.dart';
import 'suggestion_detail_page.dart';

class AccountHomePage extends StatefulWidget {
  const AccountHomePage({
    super.key,
    required this.accountId,
    required this.accountName,
    required this.myRole,
    this.market = 'br',
    this.currency = 'BRL',
  });

  final String accountId;
  final String accountName;
  final String myRole;
  final String market;
  final String currency;

  @override
  State<AccountHomePage> createState() => _AccountHomePageState();
}

class _AccountHomePageState extends State<AccountHomePage> with SingleTickerProviderStateMixin {
  List<dynamic> pending = [];
  List<dynamic> history = [];
  List<dynamic> openPositions = [];
  List<dynamic> waitingOrders = [];
  List<WatchlistItem> _watchlist = [];
  Map<String, dynamic>? portfolio;
  Map<String, dynamic>? pnl;
  List<PnlPoint> pnlSeries = [];
  bool loading = true;
  bool _watchBusy = false;
  late String deskMode;
  late TabController _tabController;
  String pnlPeriod = 'day';

  bool get canAct => widget.myRole == 'owner' || widget.myRole == 'operator';
  bool get isUs => widget.market == 'us' || widget.currency.toUpperCase() == 'USD';
  String get moneyCcy => isUs ? 'USD' : 'BRL';
  String _money(dynamic v) => formatMoney(v, currency: moneyCcy);

  @override
  void initState() {
    super.initState();
    deskMode = isUs ? 'hv_dip' : 'swing';
    _tabController = TabController(length: 4, vsync: this);
    _load();
  }

  @override
  void dispose() {
    _tabController.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    setState(() => loading = true);
    final api = context.read<ApiClient>();
    try {
      portfolio = await api.getMap('/accounts/${widget.accountId}/portfolio');
      pending = await api.getList(
        '/accounts/${widget.accountId}/suggestions',
        {'status': 'pending', 'strategy_kind': deskMode},
      );
      final all = await api.getList(
        '/accounts/${widget.accountId}/suggestions',
        {'strategy_kind': deskMode},
      );
      history = all.where((s) => (s as Map)['status'] != 'pending').toList();
      openPositions = await api.getList(
        '/accounts/${widget.accountId}/positions',
        {'status': 'open', 'strategy_kind': deskMode},
      );
      final allOrders = await api.getList('/accounts/${widget.accountId}/orders');
      waitingOrders = allOrders.where((raw) {
        final o = raw as Map<String, dynamic>;
        if ((o['strategy_kind'] as String?) != deskMode) return false;
        final st = o['status'] as String? ?? '';
        return st == 'submitted' || st == 'queued' || st == 'awaiting_broker';
      }).toList();
      try {
        _watchlist = await WatchlistRepository(api).list(widget.accountId);
      } catch (_) {
        _watchlist = [];
      }
      pnl = await api.getMap(
        '/accounts/${widget.accountId}/pnl',
        {'period': pnlPeriod, 'strategy_kind': deskMode},
      );
      try {
        final series = await api.getMap(
          '/accounts/${widget.accountId}/pnl/series',
          {'period': pnlPeriod, 'strategy_kind': deskMode},
        );
        final rawPts = (series['points'] as List<dynamic>?) ?? [];
        pnlSeries = rawPts.map(PnlPoint.fromJson).whereType<PnlPoint>().toList();
      } catch (_) {
        pnlSeries = [];
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('$e')));
      }
    }
    if (mounted) setState(() => loading = false);
  }

  void _onDeskChanged(String mode) {
    setState(() => deskMode = mode);
    _load();
  }

  void _showAccountSheet() {
    final p = portfolio;
    if (p == null) return;
    showDeskAccountSheet(context, portfolio: p, isUs: isUs, moneyCcy: moneyCcy);
  }

  void _showMarketSheet() {
    showDeskMarketSheet(context, isUs: isUs);
  }

  Future<void> _closePosition(Map<String, dynamic> pos) async {
    final isTradeDesk = (pos['strategy_kind'] as String?) == 'swing' ||
        (pos['strategy_kind'] as String?) == 'hv_dip';
    final mark = asNum(pos['mark_price']);
    final mktVal = asNum(pos['market_value_brl']);
    final upnl = asNum(pos['unrealized_pnl_brl']);
    final reason = await showModalBottomSheet<String>(
      context: context,
      showDragHandle: true,
      builder: (ctx) {
        return SafeArea(
          child: Padding(
            padding: const EdgeInsets.fromLTRB(16, 0, 16, 24),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Text('Fechar ${pos['ticker']}', style: Theme.of(ctx).textTheme.titleLarge),
                const SizedBox(height: 4),
                Text(
                  'Entrada ${formatPrice(pos['entry_price'])}'
                  '${pos['stop_price'] != null ? ' · Stop ${formatPrice(pos['stop_price'])}' : ''}'
                  '${pos['target_price'] != null ? ' · Alvo ${formatPrice(pos['target_price'])}' : ''}',
                ),
                if (mark != null) ...[
                  const SizedBox(height: 4),
                  Text(
                    'Cotação ${formatPrice(mark)}'
                    '${mktVal != null ? ' · Valor ${_money(mktVal)}' : ''}'
                    '${upnl != null ? ' · P&L ${_money(upnl)}' : ''}',
                    style: Theme.of(ctx).textTheme.bodySmall,
                  ),
                ],
                const SizedBox(height: 16),
                if (isTradeDesk && pos['stop_price'] != null)
                  ListTile(
                    leading: const Icon(Icons.south_west, color: Colors.red),
                    title: const Text('Fechar no stop'),
                    subtitle: Text(formatPrice(pos['stop_price'])),
                    onTap: () => Navigator.pop(ctx, 'stop'),
                  ),
                if (isTradeDesk && pos['target_price'] != null)
                  ListTile(
                    leading: const Icon(Icons.north_east, color: Colors.green),
                    title: const Text('Fechar no alvo'),
                    subtitle: Text(formatPrice(pos['target_price'])),
                    onTap: () => Navigator.pop(ctx, 'target'),
                  ),
                ListTile(
                  leading: const Icon(Icons.show_chart),
                  title: const Text('Cotação atual'),
                  subtitle: Text(
                    mark != null
                        ? '${formatPrice(mark)} · ${_money(mktVal)}'
                        : 'Usa preço de mercado (brapi)',
                  ),
                  onTap: () => Navigator.pop(ctx, 'market'),
                ),
                ListTile(
                  leading: const Icon(Icons.edit),
                  title: const Text('Saída manual'),
                  onTap: () => Navigator.pop(ctx, 'manual'),
                ),
                const Divider(),
                ListTile(
                  leading: Icon(Icons.sell, color: Theme.of(ctx).colorScheme.primary),
                  title: const Text('Valor total — fechar todas'),
                  subtitle: const Text('Vende todas as abertas deste desk pela cotação'),
                  onTap: () => Navigator.pop(ctx, 'close_all'),
                ),
              ],
            ),
          ),
        );
      },
    );
    if (reason == null || !mounted) return;

    if (reason == 'close_all') {
      await _closeAllPositions();
      return;
    }

    double? manualPrice;
    if (reason == 'manual') {
      final ctrl = TextEditingController(
        text: mark != null ? mark.toStringAsFixed(2) : '',
      );
      final ok = await showDialog<bool>(
        context: context,
        builder: (ctx) => AlertDialog(
          title: const Text('Preço de saída'),
          content: TextField(
            controller: ctrl,
            keyboardType: const TextInputType.numberWithOptions(decimal: true),
            decoration: const InputDecoration(labelText: 'Preço'),
            autofocus: true,
          ),
          actions: [
            TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancelar')),
            FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Confirmar')),
          ],
        ),
      );
      if (ok != true) return;
      manualPrice = asNum(ctrl.text);
      if (manualPrice == null || manualPrice <= 0) {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(content: Text('Preço inválido')),
          );
        }
        return;
      }
    }

    if (!mounted) return;
    final api = context.read<ApiClient>();
    try {
      await api.post(
        '/accounts/${widget.accountId}/positions/${pos['id']}/close',
        {
          'reason': reason,
          if (manualPrice != null) 'price': manualPrice,
        },
      );
      await _load();
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Posição fechada')),
        );
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Falha: $e')));
      }
    }
  }

  double? _deskMarketValue() {
    double? total;
    for (final raw in openPositions) {
      final v = asNum((raw as Map)['market_value_brl']);
      if (v == null) continue;
      total = (total ?? 0) + v;
    }
    return total ?? asNum(portfolio?['market_value_open_brl']);
  }

  double _deskUnrealized() {
    double total = 0;
    for (final raw in openPositions) {
      total += asNum((raw as Map)['unrealized_pnl_brl']) ?? 0;
    }
    return total;
  }

  Future<void> _closeAllPositions() async {
    final totalMkt = _deskMarketValue();
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Fechar todas as abertas?'),
        content: Text(
          totalMkt != null
              ? 'Vende todas as posições abertas deste desk pela cotação atual (~${_money(totalMkt)}).'
              : 'Vende todas as posições abertas deste desk pela cotação atual.',
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancelar')),
          FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Fechar tudo')),
        ],
      ),
    );
    if (ok != true || !mounted) return;
    final api = context.read<ApiClient>();
    try {
      await api.post(
        '/accounts/${widget.accountId}/positions/close-all',
        {},
        query: {'strategy_kind': deskMode},
      );
      await _load();
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Posições fechadas pela cotação')),
        );
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Falha: $e')));
      }
    }
  }

  Future<void> _suggestMore(Map<String, dynamic> pos) async {
    final api = context.read<ApiClient>();
    try {
      final sug = await api.post(
        '/accounts/${widget.accountId}/positions/${pos['id']}/suggest-more',
        {},
      );
      final tranche = sug['tranche_index'] ?? '?';
      final auto = sug['status'] == 'auto_approved';
      await _load();
      if (mounted) {
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
    }
  }

  Future<void> _toggleWatch(Map<String, dynamic> s) async {
    if (_watchBusy) return;
    final ticker = (s['ticker'] as String?)?.toUpperCase() ?? '';
    if (ticker.isEmpty) return;
    setState(() => _watchBusy = true);
    try {
      final repo = WatchlistRepository(context.read<ApiClient>());
      final watched = _watchlist.any((w) => w.ticker == ticker);
      if (watched) {
        await repo.remove(widget.accountId, ticker);
      } else {
        await repo.add(widget.accountId, ticker,
            note: s['strategy_kind'] as String?);
      }
      await _load();
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
          .remove(widget.accountId, w.ticker);
      await _load();
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
    final isOwner = widget.myRole == 'owner';
    final scheme = Theme.of(context).colorScheme;

    return Scaffold(
      appBar: AppBar(
        title: Text(isUs ? '${widget.accountName} · NM' : widget.accountName),
        actions: [
          IconButton(
            tooltip: 'Ordens',
            onPressed: () {
              Navigator.of(context).push(
                MaterialPageRoute(builder: (_) => OrdersPage(accountId: widget.accountId)),
              );
            },
            icon: const Icon(Icons.receipt_long),
          ),
          IconButton(
            tooltip: 'Notícias',
            onPressed: () {
              Navigator.of(context).push(
                MaterialPageRoute(builder: (_) => NewsPage(accountId: widget.accountId)),
              );
            },
            icon: const Icon(Icons.newspaper),
          ),
          if (isOwner)
            IconButton(
              tooltip: 'Membros',
              onPressed: () {
                Navigator.of(context).push(
                  MaterialPageRoute(builder: (_) => MembersPage(accountId: widget.accountId)),
                );
              },
              icon: const Icon(Icons.group),
            ),
          if (isOwner)
            IconButton(
              tooltip: 'Regras',
              onPressed: () async {
                await Navigator.of(context).push(
                  MaterialPageRoute(builder: (_) => SettingsPage(accountId: widget.accountId)),
                );
                await _load();
              },
              icon: const Icon(Icons.tune),
            ),
        ],
      ),
      body: DeskTabScaffold(
        tabController: _tabController,
        isUs: isUs,
        portfolio: portfolio,
        moneyCcy: moneyCcy,
        openCount: openPositions.length,
        waitingCount: waitingOrders.length,
        pendingCount: pending.length,
        loading: loading,
        onRefresh: _load,
        onTapSummary: _showAccountSheet,
        onTapMarket: _showMarketSheet,
        onTapDayTrade: isUs
            ? () {
                Navigator.of(context).push(
                  MaterialPageRoute(
                    builder: (_) => DayTradeStudyPage(
                      accountId: widget.accountId,
                      accountName: widget.accountName,
                    ),
                  ),
                );
              }
            : null,
        deskMode: isUs ? null : deskMode,
        onDeskChanged: isUs ? null : _onDeskChanged,
        tabBodies: [
          DeskTabScrollBody(storageKey: 'sugestoes', children: _suggestionsSection()),
          DeskTabScrollBody(storageKey: 'aguardando', children: _waitingSection(scheme)),
          DeskTabScrollBody(storageKey: 'posicoes', children: _positionsSection()),
          DeskTabScrollBody(storageKey: 'resultados', children: _resultsSection(scheme)),
        ],
      ),
    );
  }

  Future<void> _cancelWaitingOrder(Map<String, dynamic> order) async {
    final ticker = order['ticker'] as String? ?? '?';
    final qty = formatQty(order['quantity']);
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Cancelar ordem?'),
        content: Text(
          'Remove $ticker · $qty da fila e cancela na corretora (se já enviada).',
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Voltar')),
          FilledButton(
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('Cancelar ordem'),
          ),
        ],
      ),
    );
    if (ok != true || !mounted) return;

    try {
      await context.read<ApiClient>().post(
        '/accounts/${widget.accountId}/orders/${order['id']}/mark-cancelled',
        {},
      );
      await _load();
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Ordem $ticker removida da fila')),
        );
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Falha ao cancelar: $e')),
        );
      }
    }
  }

  List<Widget> _waitingSection(ColorScheme scheme) {
    final activeMarket = MarketHours.forMarket(isUs ? 'us' : 'br');
    return [
      if (!activeMarket.isOpen)
        Padding(
          padding: const EdgeInsets.only(bottom: 8),
          child: Text(
            '${activeMarket.name} fechado — ordens na fila até o pregão abrir.',
            style: Theme.of(context).textTheme.bodySmall?.copyWith(
                  color: Colors.orange.shade800,
                ),
          ),
        ),
      if (waitingOrders.isEmpty)
        const Text('Nenhuma ordem aguardando execução.'),
      ...waitingOrders.map((raw) {
        final o = raw as Map<String, dynamic>;
        final label = orderWaitingLabel(o);
        final detail = orderWaitingDetail(o);
        final payload = o['execution_payload'] as Map<String, dynamic>?;
        final mode = payload?['mode'] as String? ?? o['broker'] as String? ?? '';
        return Card(
          child: ListTile(
            leading: CircleAvatar(
              backgroundColor: scheme.primaryContainer,
              child: Icon(Icons.hourglass_top, color: scheme.onPrimaryContainer, size: 20),
            ),
            title: Text('${o['ticker']} · ${formatQty(o['quantity'])}'),
            subtitle: Text(
              'Limit ${formatPrice(o['limit_price'])} · ~${_money(o['amount_brl'])}'
              '\n$label'
              '${detail != null ? '\n$detail' : ''}'
              '${mode.isNotEmpty ? '\nVia $mode' : ''}',
            ),
            isThreeLine: true,
            trailing: canAct
                ? IconButton(
                    tooltip: 'Cancelar da fila',
                    icon: Icon(Icons.cancel_outlined, color: scheme.error),
                    onPressed: () => _cancelWaitingOrder(o),
                  )
                : null,
            onTap: () async {
              final suggestionId = o['suggestion_id'] as String?;
              if (suggestionId == null || suggestionId.isEmpty) {
                await Navigator.of(context).push(
                  MaterialPageRoute(
                    builder: (_) => OrderDetailPage(
                      accountId: widget.accountId,
                      orderId: o['id'] as String,
                      canCancel: canAct,
                    ),
                  ),
                );
              } else {
                await Navigator.of(context).push(
                  MaterialPageRoute(
                    builder: (_) => SuggestionDetailPage(
                      accountId: widget.accountId,
                      suggestionId: suggestionId,
                      myRole: widget.myRole,
                      waitingOrder: o,
                    ),
                  ),
                );
              }
              await _load();
            },
          ),
        );
      }),
    ];
  }

  List<Widget> _suggestionsSection() {
    final watchedTickers = _watchlist.map((w) => w.ticker).toSet();
    return [
      ..._watchlistSection(),
      if (pending.isEmpty)
        Text(
          deskMode == 'swing'
              ? 'Nenhum setup swing pendente.'
              : 'Nenhuma sugestão pendente.',
        ),
      ...pending.map((s) => _suggestionTile(
            s as Map<String, dynamic>,
            watchedTickers: watchedTickers,
            onToggleWatch: () => _toggleWatch(s),
            watchBusy: _watchBusy,
          )),
      if (pending.isNotEmpty && history.isNotEmpty) const SizedBox(height: 16),
      if (history.isNotEmpty) ...[
        Text('Decisões anteriores', style: Theme.of(context).textTheme.titleSmall),
        const SizedBox(height: 8),
        ...history.map((s) => _suggestionTile(s as Map<String, dynamic>)),
      ],
    ];
  }

  List<Widget> _watchlistSection() {
    if (_watchlist.isEmpty) return const [];
    return [
      Text('Observação', style: Theme.of(context).textTheme.titleSmall),
      const SizedBox(height: 8),
      ..._watchlist.map(_watchlistTile),
      const SizedBox(height: 16),
    ];
  }

  Widget _watchlistTile(WatchlistItem w) {
    final price = w.price;
    final change = w.changePct;
    final up = change != null && change >= 0;
    return Card(
      child: ListTile(
        dense: true,
        leading: CircleAvatar(
          backgroundColor: Theme.of(context).colorScheme.secondaryContainer,
          child: const Icon(Icons.visibility_outlined, size: 20),
        ),
        title: Text(w.ticker),
        subtitle: Text(
          price == null
              ? 'Aguardando cotação'
              : '${formatPrice(price)} · ${formatMoney(price, currency: w.currency)}',
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
              onPressed: canAct ? () => _removeWatch(w) : null,
              icon: const Icon(Icons.close, size: 18),
            ),
          ],
        ),
      ),
    );
  }

  List<Widget> _positionsSection() {
    final openMkt = _deskMarketValue();
    final openUpnl = _deskUnrealized();
    final upnlColor = openUpnl > 0
        ? Colors.green.shade700
        : openUpnl < 0
            ? Colors.red.shade700
            : null;
    return [
      if (canAct && openPositions.isNotEmpty)
        Align(
          alignment: Alignment.centerRight,
          child: TextButton.icon(
            onPressed: _closeAllPositions,
            icon: const Icon(Icons.sell_outlined, size: 18),
            label: const Text('Fechar todas'),
          ),
        ),
      if (openMkt != null && openPositions.isNotEmpty)
        Padding(
          padding: const EdgeInsets.only(bottom: 8),
          child: Text(
            'Valor a mercado ${_money(openMkt)} · P&L ${_money(openUpnl)}',
            style: Theme.of(context).textTheme.bodySmall?.copyWith(color: upnlColor),
          ),
        ),
      if (openPositions.isEmpty) const Text('Nenhuma posição aberta.'),
      ...openPositions.map((raw) {
        final p = raw as Map<String, dynamic>;
        final mark = asNum(p['mark_price']);
        final mkt = asNum(p['market_value_brl']);
        final upnl = asNum(p['unrealized_pnl_brl']);
        final upnlPct = asNum(p['unrealized_pnl_pct']);
        final color = (upnl ?? 0) > 0
            ? Colors.green.shade700
            : (upnl ?? 0) < 0
                ? Colors.red.shade700
                : null;
        final alert = p['price_alert'] as String?;
        final latched = p['latched_5'] == true;
        final protect = p['protect_active'] == true;
        final daysReview = p['days_until_review'] as int?;
        Color? cardColor;
        if (alert == 'stop') {
          cardColor = Colors.red.withValues(alpha: 0.06);
        } else if (alert == 'target') {
          cardColor = Colors.green.withValues(alpha: 0.06);
        } else if (alert == 'protect' || protect) {
          cardColor = Colors.orange.withValues(alpha: 0.08);
        } else if (alert == 'latched' || latched) {
          cardColor = Colors.blue.withValues(alpha: 0.06);
        } else if (alert == 'time_review') {
          cardColor = Colors.purple.withValues(alpha: 0.06);
        } else if (alert == 'recovery') {
          cardColor = Colors.blue.withValues(alpha: 0.06);
        } else if (alert == 'trailing') {
          cardColor = Colors.amber.withValues(alpha: 0.08);
        }
        final suggestionId = p['suggestion_id'] as String?;
        return Card(
          color: cardColor,
          child: ListTile(
            onTap: suggestionId != null && suggestionId.isNotEmpty
                ? () async {
                    await Navigator.of(context).push(
                      MaterialPageRoute(
                        builder: (_) => SuggestionDetailPage(
                          accountId: widget.accountId,
                          suggestionId: suggestionId,
                          myRole: widget.myRole,
                        ),
                      ),
                    );
                    await _load();
                  }
                : null,
            title: Row(
              children: [
                Expanded(child: Text('${p['ticker']} · ${formatQty(p['quantity'])}')),
                if (alert == 'stop')
                  Chip(
                    label: const Text('STOP', style: TextStyle(fontSize: 11)),
                    backgroundColor: Colors.red.shade100,
                    visualDensity: VisualDensity.compact,
                    padding: EdgeInsets.zero,
                  )
                else if (alert == 'target')
                  Chip(
                    label: const Text('ALVO', style: TextStyle(fontSize: 11)),
                    backgroundColor: Colors.green.shade100,
                    visualDensity: VisualDensity.compact,
                    padding: EdgeInsets.zero,
                  )
                else if (alert == 'recovery')
                  Chip(
                    label: const Text('RECUP', style: TextStyle(fontSize: 11)),
                    backgroundColor: Colors.blue.shade100,
                    visualDensity: VisualDensity.compact,
                    padding: EdgeInsets.zero,
                  )
                else if (alert == 'trailing')
                  Chip(
                    label: const Text('TRAIL', style: TextStyle(fontSize: 11)),
                    backgroundColor: Colors.amber.shade100,
                    visualDensity: VisualDensity.compact,
                    padding: EdgeInsets.zero,
                  )
                else if (protect)
                  Chip(
                    label: const Text('PROT', style: TextStyle(fontSize: 11)),
                    backgroundColor: Colors.orange.shade100,
                    visualDensity: VisualDensity.compact,
                    padding: EdgeInsets.zero,
                  )
                else if (latched)
                  Chip(
                    label: const Text('OBS', style: TextStyle(fontSize: 11)),
                    backgroundColor: Colors.blue.shade100,
                    visualDensity: VisualDensity.compact,
                    padding: EdgeInsets.zero,
                  )
                else if (daysReview != null && daysReview <= 2)
                  Chip(
                    label: Text('D14', style: TextStyle(fontSize: 11)),
                    backgroundColor: Colors.purple.shade100,
                    visualDensity: VisualDensity.compact,
                    padding: EdgeInsets.zero,
                  ),
              ],
            ),
            subtitle: Text(
              'Entrada ${formatPrice(p['entry_price'])}'
              '${mark != null ? ' · ${formatPrice(mark)}' : ''}'
              '${mkt != null ? '\n${_money(mkt)}' : ''}'
              '${upnl != null ? ' · P&L ${_money(upnl)}' : ''}'
              '${upnlPct != null ? ' (${formatPct(upnlPct)})' : ''}'
              '${p['stop_price'] != null ? '\nStop ${formatPrice(p['stop_price'])}' : ''}'
              '${p['target_price'] != null ? ' · Alvo ${formatPrice(p['target_price'])}' : ''}',
            ),
            isThreeLine: true,
            trailing: canAct
                ? Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      if (p['strategy_kind'] == 'hv_dip')
                        IconButton(
                          tooltip: 'Comprar mais (nova tranche)',
                          visualDensity: VisualDensity.compact,
                          icon: const Icon(Icons.add_shopping_cart_outlined, size: 20),
                          onPressed: () => _suggestMore(p),
                        ),
                      FilledButton.tonal(
                        onPressed: () => _closePosition(p),
                        child: Text(
                          upnl != null ? _money(upnl) : 'Fechar',
                          style: TextStyle(color: color, fontWeight: FontWeight.w700),
                        ),
                      ),
                    ],
                  )
                : (upnl != null
                    ? Text(_money(upnl), style: TextStyle(color: color, fontWeight: FontWeight.w700))
                    : null),
          ),
        );
      }),
    ];
  }

  List<Widget> _resultsSection(ColorScheme scheme) {
    final items = (pnl?['items'] as List<dynamic>?) ?? [];
    final total = asNum(pnl?['total_pnl_brl']) ?? 0;
    final totalColor = total > 0
        ? Colors.green.shade700
        : total < 0
            ? Colors.red.shade700
            : scheme.onSurface;
    final goals = (pnl?['goals'] as Map<String, dynamic>?) ?? {};
    final scorecard = pnl?['scorecard'] as Map<String, dynamic>?;
    final dailyTarget = asNum(goals['daily_target_pct']) ?? 7.0;
    final showChart = pnlSeries.length >= 2;
    return [
      SegmentedButton<String>(
        segments: const [
          ButtonSegment(value: 'day', label: Text('Dia')),
          ButtonSegment(value: 'week', label: Text('Sem')),
          ButtonSegment(value: 'month', label: Text('Mês')),
          ButtonSegment(value: 'year', label: Text('Ano')),
        ],
        selected: {pnlPeriod},
        onSelectionChanged: (s) {
          setState(() => pnlPeriod = s.first);
          _load();
        },
      ),
      const SizedBox(height: 12),
      Text(
        _money(total),
        style: Theme.of(context).textTheme.headlineSmall?.copyWith(
              color: totalColor,
              fontWeight: FontWeight.w700,
            ),
      ),
      Text(
        '${pnl?['trades'] ?? 0} trades · ${pnl?['wins'] ?? 0}W · ${pnl?['losses'] ?? 0}L',
        style: Theme.of(context).textTheme.bodySmall,
      ),
      if (goals.isNotEmpty) ...[
        const SizedBox(height: 12),
        PnlGoalBanner(goals: goals, currency: moneyCcy),
      ],
      const SizedBox(height: 12),
      if (showChart)
        PnlLineChart(
          points: pnlSeries,
          currency: moneyCcy,
          dailyTargetPct: dailyTarget,
        )
      else if (goals.isNotEmpty && pnlPeriod == 'day')
        Text(
          'Diário sem curva: acompanhe meta × atingido acima. '
          'Mude para Sem/Mês para ver a evolução.',
          style: Theme.of(context).textTheme.bodySmall?.copyWith(
                color: scheme.onSurfaceVariant,
              ),
        )
      else
        PnlLineChart(points: pnlSeries, currency: moneyCcy, dailyTargetPct: dailyTarget),
      if (scorecard != null) ...[
        const SizedBox(height: 12),
        StretchScorecardCard(scorecard: scorecard, currency: moneyCcy),
      ],
      const SizedBox(height: 12),
      if (items.isEmpty) const Text('Nenhum trade fechado no período.'),
      ...items.map((raw) {
        final p = raw as Map<String, dynamic>;
        final pnlVal = asNum(p['realized_pnl_brl']) ?? 0;
        final color = pnlVal >= 0 ? Colors.green.shade700 : Colors.red.shade700;
        return Card(
          child: ListTile(
            title: Text('${p['ticker']} · ${p['exit_reason'] ?? '—'}'),
            subtitle: Text(
              '${formatPrice(p['entry_price'])} → ${formatPrice(p['exit_price'])} · '
              '${formatQty(p['quantity'])}'
              '${p['r_multiple_realized'] != null ? ' · R ${formatRatio(p['r_multiple_realized'])}' : ''}',
            ),
            trailing: Text(
              _money(pnlVal),
              style: TextStyle(color: color, fontWeight: FontWeight.w700),
            ),
          ),
        );
      }),
    ];
  }

  Widget _suggestionTile(
    Map<String, dynamic> s, {
    Set<String>? watchedTickers,
    VoidCallback? onToggleWatch,
    bool watchBusy = false,
  }) {
    final kind = s['strategy_kind'] as String? ?? 'income';
    final isTrade = kind == 'swing' || kind == 'hv_dip';
    if (isTrade) {
      final letter = s['swing_score_letter'] as String? ?? '?';
      final review = s['review_required'] == true;
      final tranche = s['tranche_index'];
      final metrics = (s['metrics'] as Map<String, dynamic>?) ?? {};
      final h1Label =
          kind == 'swing' ? h1ChipLabel(metrics['h1_status']?.toString()) : null;
      final dipLive = asNum(metrics['dip_pct_live']);
      final refreshedAt = metrics['refreshed_at'];
      final pending = s['status'] == 'pending';
      final ticker = (s['ticker'] as String?)?.toUpperCase() ?? '';
      final watched = watchedTickers?.contains(ticker) ?? false;
      final liveHint = dipLive != null && refreshedAt != null
          ? '\nDip ${formatPct(dipLive)} · atualizado ${formatRefreshedAt(refreshedAt)}'
          : '';
      return Card(
        child: ListTile(
          title: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                kind == 'hv_dip'
                    ? '${s['ticker']} — NM $letter (${formatScore(s['score'])})'
                    : '${s['ticker']} — $letter (${formatScore(s['score'])})',
              ),
              Wrap(
                spacing: 4,
                runSpacing: 0,
                children: [
                  if (kind == 'hv_dip' && isLiveSuggestion(metrics))
                    const Chip(
                      label: Text('VIVA', style: TextStyle(fontSize: 10)),
                      visualDensity: VisualDensity.compact,
                      padding: EdgeInsets.zero,
                    ),
                  if (metrics['catalyst'] != null)
                    const Chip(
                      label: Text('CATALISTA', style: TextStyle(fontSize: 10)),
                      visualDensity: VisualDensity.compact,
                      padding: EdgeInsets.zero,
                    ),
                  if (review)
                    const Chip(
                      label: Text('REVIEW', style: TextStyle(fontSize: 10)),
                      visualDensity: VisualDensity.compact,
                      padding: EdgeInsets.zero,
                    ),
                  if (h1Label != null)
                    Chip(
                      label: Text(h1Label, style: const TextStyle(fontSize: 10)),
                      visualDensity: VisualDensity.compact,
                      padding: EdgeInsets.zero,
                    ),
                ],
              ),
            ],
          ),
          subtitle: Text(
            '${formatPrice(s['entry_price'])} · stop ${formatPrice(s['stop_price'])} · alvo ${formatPrice(s['target_price'])}'
            '$liveHint'
            '\n${_money(s['proposed_amount_brl'])} · ${s['status']}'
            '${tranche != null ? ' · T$tranche' : ''}',
          ),
          isThreeLine: true,
          trailing: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              if (pending && onToggleWatch != null)
                IconButton(
                  tooltip: watched
                      ? 'Remover da observação'
                      : 'Adicionar à observação',
                  visualDensity: VisualDensity.compact,
                  onPressed: watchBusy ? null : onToggleWatch,
                  icon: Icon(
                    watched ? Icons.star : Icons.star_border,
                    size: 20,
                    color: watched ? Colors.amber.shade700 : null,
                  ),
                ),
              const Icon(Icons.chevron_right),
            ],
          ),
          onTap: () => _openDetail(s),
        ),
      );
    }
    final assetClass = s['asset_class'] as String? ?? 'fii';
    final freq = s['dividend_frequency'] as String? ?? '';
    final metrics = (s['metrics'] as Map<String, dynamic>?) ?? {};
    final eff = metrics['effective_yield'];
    return Card(
      child: ListTile(
        title: Text('${s['ticker']} — ${formatScore(s['score'])}'),
        subtitle: Text(
          '$assetClass · $freq'
          '${eff != null ? ' · ${formatPct(eff)}' : ''} · ${_money(s['proposed_amount_brl'])}',
        ),
        trailing: const Icon(Icons.chevron_right),
        onTap: () => _openDetail(s),
      ),
    );
  }

  Future<void> _openDetail(Map<String, dynamic> s) async {
    await Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) => SuggestionDetailPage(
          accountId: widget.accountId,
          suggestionId: s['id'] as String,
          myRole: widget.myRole,
        ),
      ),
    );
    await _load();
  }
}
