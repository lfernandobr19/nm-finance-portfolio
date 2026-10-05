import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../core/api_client.dart';
import '../../core/auth_state.dart';
import '../../core/theme_controller.dart';
import '../../core/market_prefs.dart';
import '../suggestions/account_home_page.dart';

class AccountsPage extends StatefulWidget {
  const AccountsPage({super.key});

  @override
  State<AccountsPage> createState() => _AccountsPageState();
}

class _AccountsPageState extends State<AccountsPage> {
  List<dynamic> accounts = [];
  bool loading = true;
  String? error;
  String market = 'br'; // br | us

  @override
  void initState() {
    super.initState();
    _bootstrap();
  }

  Future<void> _bootstrap() async {
    market = await MarketPrefs.load();
    await _load();
  }

  bool _isUsdAccount(Map<String, dynamic> map) {
    final ccy = (map['currency'] as String?)?.toUpperCase() ?? 'BRL';
    final broker = (map['broker_code'] as String?)?.toLowerCase() ?? '';
    return ccy == 'USD' || broker == 'alpaca';
  }

  List<dynamic> get _filtered {
    return accounts.where((a) {
      final map = a as Map<String, dynamic>;
      final usd = _isUsdAccount(map);
      return market == 'us' ? usd : !usd;
    }).toList();
  }

  Future<void> _load() async {
    setState(() {
      loading = true;
      error = null;
    });
    try {
      final api = context.read<ApiClient>();
      if (market == 'us') {
        try {
          await api.post('/accounts/ensure-nm-usd', {});
        } catch (_) {
          // Conta pode já existir ou API antiga — lista abaixo
        }
      }
      accounts = await api.getList('/accounts');
    } catch (e) {
      error = e.toString();
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  Future<void> _setMarket(String next) async {
    if (next == market) return;
    setState(() => market = next);
    await MarketPrefs.save(next);
    await _load();
  }

  Future<void> _createAccount() async {
    if (market == 'us') {
      final api = context.read<ApiClient>();
      await api.post('/accounts/ensure-nm-usd', {});
      await _load();
      return;
    }
    final nameCtrl = TextEditingController();
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Nova conta Brasil'),
        content: TextField(
          controller: nameCtrl,
          decoration: const InputDecoration(labelText: 'Nome'),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancelar')),
          FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Criar')),
        ],
      ),
    );
    if (ok != true || nameCtrl.text.trim().isEmpty) return;
    if (!mounted) return;
    final api = context.read<ApiClient>();
    await api.post('/accounts', {
      'name': nameCtrl.text.trim(),
      'target_capital': 50000,
      'max_ticket_brl': 5000,
    });
    await _load();
  }

  Future<void> _acceptInvite() async {
    final codeCtrl = TextEditingController();
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Entrar com convite'),
        content: TextField(
          controller: codeCtrl,
          decoration: const InputDecoration(labelText: 'Código'),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancelar')),
          FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Aceitar')),
        ],
      ),
    );
    if (ok != true || codeCtrl.text.trim().isEmpty) return;
    if (!mounted) return;
    await context.read<ApiClient>().post('/accounts/invites/accept', {
      'code': codeCtrl.text.trim(),
    });
    await _load();
  }

  Future<void> _renameAccount(Map<String, dynamic> account) async {
    final ctrl = TextEditingController(text: account['name'] as String? ?? '');
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
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancelar')),
          FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Salvar')),
        ],
      ),
    );
    if (ok != true || ctrl.text.trim().isEmpty || !mounted) return;
    try {
      await context
          .read<ApiClient>()
          .patch('/accounts/${account['id']}', {'name': ctrl.text.trim()});
      await _load();
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('Falha ao renomear: $e')));
      }
    }
  }

  Future<void> _deleteAccount(Map<String, dynamic> account) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text('Excluir "${account['name']}"?'),
        content: const Text(
          'Apaga a conta e todo o histórico (posições, ordens, sugestões e '
          'observação). Não pode ser desfeita.',
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancelar')),
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
    try {
      await context.read<ApiClient>().delete('/accounts/${account['id']}');
      await _load();
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('Falha ao excluir: $e')));
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final user = context.watch<AuthState>().user;
    final themeCtrl = context.watch<ThemeController>();
    final filtered = _filtered;
    return Scaffold(
      appBar: AppBar(
        title: const Text('NM Finance'),
        actions: [
          PopupMenuButton<ThemeMode>(
            tooltip: 'Tema',
            icon: Icon(
              themeCtrl.mode == ThemeMode.dark
                  ? Icons.dark_mode
                  : themeCtrl.mode == ThemeMode.light
                      ? Icons.light_mode
                      : Icons.brightness_auto,
            ),
            onSelected: themeCtrl.setMode,
            itemBuilder: (_) => const [
              PopupMenuItem(value: ThemeMode.system, child: Text('Sistema')),
              PopupMenuItem(value: ThemeMode.light, child: Text('Claro')),
              PopupMenuItem(value: ThemeMode.dark, child: Text('Escuro')),
            ],
          ),
          IconButton(onPressed: _acceptInvite, icon: const Icon(Icons.mail_outline)),
          IconButton(
            onPressed: () => context.read<AuthState>().logout(),
            icon: const Icon(Icons.logout),
          ),
        ],
      ),
      floatingActionButton: FloatingActionButton(
        onPressed: _createAccount,
        tooltip: market == 'us' ? 'Garantir conta NM USD' : 'Nova conta Brasil',
        child: const Icon(Icons.add),
      ),
      body: loading
          ? const Center(child: CircularProgressIndicator())
          : error != null
              ? Center(child: Text(error!))
              : RefreshIndicator(
                  onRefresh: _load,
                  child: ListView(
                    padding: const EdgeInsets.all(16),
                    children: [
                      Text('Olá, ${user?['full_name'] ?? user?['email'] ?? ''}'),
                      const SizedBox(height: 12),
                      SegmentedButton<String>(
                        segments: const [
                          ButtonSegment(
                            value: 'br',
                            label: Text('Brasil'),
                            icon: Icon(Icons.flag),
                          ),
                          ButtonSegment(
                            value: 'us',
                            label: Text('EUA'),
                            icon: Icon(Icons.public),
                          ),
                        ],
                        selected: {market},
                        onSelectionChanged: (s) => _setMarket(s.first),
                      ),
                      if (market == 'us') ...[
                        const SizedBox(height: 8),
                        Text(
                          'NM · Next Milestone — High-Vol Dip (USD)',
                          style: Theme.of(context).textTheme.bodySmall,
                        ),
                      ],
                      const SizedBox(height: 12),
                      if (filtered.isEmpty)
                        Text(
                          market == 'us'
                              ? 'Nenhuma conta EUA. Toque + para criar NM USD Paper.'
                              : 'Nenhuma conta Brasil. Crie uma ou aceite um convite.',
                        ),
                      ...filtered.map((a) {
                        final map = a as Map<String, dynamic>;
                        final usd = _isUsdAccount(map);
                        final isOwner = map['my_role'] == 'owner';
                        return Card(
                          child: ListTile(
                            title: Text(map['name'] as String),
                            subtitle: Text(
                              usd
                                  ? 'EUA · ${map['broker_code'] ?? 'alpaca'} · Papel: ${map['my_role']}'
                                  : 'Brasil · Papel: ${map['my_role']}',
                            ),
                            trailing: Row(
                              mainAxisSize: MainAxisSize.min,
                              children: [
                                if (isOwner)
                                  PopupMenuButton<String>(
                                    tooltip: 'Gerenciar conta',
                                    icon: const Icon(Icons.more_vert),
                                    onSelected: (v) {
                                      if (v == 'rename') _renameAccount(map);
                                      if (v == 'delete') _deleteAccount(map);
                                    },
                                    itemBuilder: (_) => const [
                                      PopupMenuItem(
                                        value: 'rename',
                                        child: ListTile(
                                          leading: Icon(Icons.edit_outlined),
                                          title: Text('Renomear'),
                                          contentPadding: EdgeInsets.zero,
                                        ),
                                      ),
                                      PopupMenuItem(
                                        value: 'delete',
                                        child: ListTile(
                                          leading: Icon(Icons.delete_outline),
                                          title: Text('Excluir'),
                                          contentPadding: EdgeInsets.zero,
                                        ),
                                      ),
                                    ],
                                  ),
                                const Icon(Icons.chevron_right),
                              ],
                            ),
                            onTap: () {
                              Navigator.of(context).push(
                                MaterialPageRoute(
                                  builder: (_) => AccountHomePage(
                                    accountId: map['id'] as String,
                                    accountName: map['name'] as String,
                                    myRole: map['my_role'] as String,
                                    market: usd ? 'us' : 'br',
                                    currency: usd ? 'USD' : 'BRL',
                                  ),
                                ),
                              );
                            },
                          ),
                        );
                      }),
                    ],
                  ),
                ),
    );
  }
}
