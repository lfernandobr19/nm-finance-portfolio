import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../core/api_client.dart';
import '../../core/theme_controller.dart';

class SettingsPage extends StatefulWidget {
  const SettingsPage({super.key, required this.accountId});

  final String accountId;

  @override
  State<SettingsPage> createState() => _SettingsPageState();
}

class _SettingsPageState extends State<SettingsPage> {
  Map<String, dynamic>? account;
  Map<String, dynamic>? rules;
  bool loading = true;
  bool saving = false;

  final effCtrl = TextEditingController();
  final pvpCtrl = TextEditingController();
  final volCtrl = TextEditingController();
  final thrCtrl = TextEditingController();
  final autoScoreCtrl = TextEditingController();
  final autoLimitCtrl = TextEditingController();
  final swingEquityCtrl = TextEditingController();
  final swingMaxPosCtrl = TextEditingController();
  final swingFloorCtrl = TextEditingController();
  final swingRiskACtrl = TextEditingController();
  final swingRiskBCtrl = TextEditingController();
  final hvDipEquityCtrl = TextEditingController();
  final hvDipMaxPosCtrl = TextEditingController();
  final hvDipMaxTickerPctCtrl = TextEditingController();
  final hvDipFloorCtrl = TextEditingController();

  bool preferMonthly = true;
  bool allowFii = true;
  bool allowBdr = true;
  String executionMode = 'paper';

  bool get isUsdAccount {
    final currency = account?['currency'] as String?;
    final broker = (account?['broker_code'] as String?)?.toLowerCase();
    return currency == 'USD' || broker == 'alpaca';
  }

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    effCtrl.dispose();
    pvpCtrl.dispose();
    volCtrl.dispose();
    thrCtrl.dispose();
    autoScoreCtrl.dispose();
    autoLimitCtrl.dispose();
    swingEquityCtrl.dispose();
    swingMaxPosCtrl.dispose();
    swingFloorCtrl.dispose();
    swingRiskACtrl.dispose();
    swingRiskBCtrl.dispose();
    hvDipEquityCtrl.dispose();
    hvDipMaxPosCtrl.dispose();
    hvDipMaxTickerPctCtrl.dispose();
    hvDipFloorCtrl.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    final api = context.read<ApiClient>();
    account = await api.getMap('/accounts/${widget.accountId}');
    rules = await api.getMap('/accounts/${widget.accountId}/rules');
    final minEff = rules!['min_effective_yield'] ?? rules!['min_dividend_yield'];
    effCtrl.text = '$minEff';
    pvpCtrl.text = '${rules!['max_p_vp']}';
    volCtrl.text = '${rules!['min_avg_volume']}';
    thrCtrl.text = '${rules!['score_threshold']}';
    preferMonthly = rules!['prefer_monthly_dividends'] != false;
    final classes = List<String>.from(rules!['allowed_asset_classes'] ?? ['fii', 'bdr_reit']);
    allowFii = classes.contains('fii');
    allowBdr = classes.contains('bdr_reit');
    autoScoreCtrl.text = '${account!['auto_approve_min_score']}';
    autoLimitCtrl.text = '${account!['daily_auto_approve_limit']}';
    executionMode = account!['execution_mode'] as String? ?? 'paper';
    swingEquityCtrl.text = '${account!['cash_brl'] ?? account!['swing_equity_brl'] ?? 10000}';
    swingMaxPosCtrl.text = '${account!['swing_max_positions'] ?? 5}';
    swingFloorCtrl.text = '${account!['swing_cash_floor_pct'] ?? 20}';
    swingRiskACtrl.text = '${account!['swing_risk_pct_a'] ?? 1.5}';
    swingRiskBCtrl.text = '${account!['swing_risk_pct_b'] ?? 1.0}';
    hvDipEquityCtrl.text =
        '${account!['cash_usd'] ?? account!['hv_dip_equity_usd'] ?? 100}';
    hvDipMaxPosCtrl.text = '${account!['hv_dip_max_positions'] ?? 4}';
    hvDipMaxTickerPctCtrl.text = '${account!['hv_dip_max_ticker_pct'] ?? 80}';
    hvDipFloorCtrl.text = '${account!['hv_dip_cash_floor_pct'] ?? 30}';
    if (mounted) setState(() => loading = false);
  }

  Future<void> _saveRules() async {
    setState(() => saving = true);
    final api = context.read<ApiClient>();
    if (!isUsdAccount) {
      final classes = <String>[
        if (allowFii) 'fii',
        if (allowBdr) 'bdr_reit',
      ];
      if (classes.isEmpty) {
        classes.addAll(['fii', 'bdr_reit']);
      }
      final minEff = double.parse(effCtrl.text);
      await api.put('/accounts/${widget.accountId}/rules', {
        'min_effective_yield': minEff,
        'min_dividend_yield': minEff,
        'max_p_vp': double.parse(pvpCtrl.text),
        'min_avg_volume': double.parse(volCtrl.text),
        'score_threshold': double.parse(thrCtrl.text),
        'prefer_monthly_dividends': preferMonthly,
        'allowed_asset_classes': classes,
      });
      account = await api.patch('/accounts/${widget.accountId}', {
        'auto_approve_min_score': double.parse(autoScoreCtrl.text),
        'daily_auto_approve_limit': int.parse(autoLimitCtrl.text),
        'swing_equity_brl': double.parse(swingEquityCtrl.text),
        'cash_brl': double.parse(swingEquityCtrl.text),
        'swing_max_positions': int.parse(swingMaxPosCtrl.text),
        'swing_cash_floor_pct': double.parse(swingFloorCtrl.text),
        'swing_risk_pct_a': double.parse(swingRiskACtrl.text),
        'swing_risk_pct_b': double.parse(swingRiskBCtrl.text),
      });
    } else {
      final equity = double.parse(hvDipEquityCtrl.text);
      account = await api.patch('/accounts/${widget.accountId}', {
        'auto_approve_min_score': double.parse(autoScoreCtrl.text),
        'daily_auto_approve_limit': int.parse(autoLimitCtrl.text),
        'cash_usd': equity,
        'hv_dip_equity_usd': equity,
        'hv_dip_max_positions': int.parse(hvDipMaxPosCtrl.text),
        'hv_dip_max_ticker_pct': double.parse(hvDipMaxTickerPctCtrl.text),
        'hv_dip_cash_floor_pct': double.parse(hvDipFloorCtrl.text),
      });
    }
    setState(() => saving = false);
    if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Regras atualizadas')),
      );
    }
  }

  Future<void> _toggleAuto(bool value) async {
    final api = context.read<ApiClient>();
    account = await api.patch('/accounts/${widget.accountId}', {
      'auto_approve_enabled': value,
    });
    setState(() {});
  }

  Future<void> _toggleAutomationPaused(bool value) async {
    final api = context.read<ApiClient>();
    account = await api.patch('/accounts/${widget.accountId}', {
      'automation_paused': value,
    });
    setState(() {});
  }

  Future<void> _setExecutionMode(String mode) async {
    final api = context.read<ApiClient>();
    final patch = <String, dynamic>{'execution_mode': mode};
    if (!isUsdAccount) {
      patch['broker_code'] = 'inter';
    }
    account = await api.patch('/accounts/${widget.accountId}', patch);
    setState(() => executionMode = mode);
  }

  @override
  Widget build(BuildContext context) {
    if (loading) {
      return const Scaffold(body: Center(child: CircularProgressIndicator()));
    }
    final auto = account?['auto_approve_enabled'] == true;
    final themeCtrl = context.watch<ThemeController>();
    return Scaffold(
      appBar: AppBar(title: const Text('Regras e automação')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Text('Aparência', style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: 8),
          SegmentedButton<ThemeMode>(
            segments: const [
              ButtonSegment(value: ThemeMode.system, label: Text('Sistema'), icon: Icon(Icons.brightness_auto)),
              ButtonSegment(value: ThemeMode.light, label: Text('Claro'), icon: Icon(Icons.light_mode)),
              ButtonSegment(value: ThemeMode.dark, label: Text('Escuro'), icon: Icon(Icons.dark_mode)),
            ],
            selected: {themeCtrl.mode},
            onSelectionChanged: (s) => themeCtrl.setMode(s.first),
          ),
          const Divider(),
          SwitchListTile(
            title: const Text('Auto-aprovar'),
            subtitle: Text(
              isUsdAccount
                  ? 'Review NM continua exigindo confirmação manual.'
                  : 'Desligado por padrão. Sugestões com score alto viram auto_approved (sem ordem na corretora).',
            ),
            value: auto,
            onChanged: _toggleAuto,
          ),
          SwitchListTile(
            title: const Text('Pausar automação'),
            subtitle: const Text(
              'Kill switch: suspende compras e vendas automáticas nesta conta (sugestões manuais continuam).',
            ),
            value: account?['automation_paused'] == true,
            secondary: Icon(
              account?['automation_paused'] == true
                  ? Icons.pause_circle
                  : Icons.play_circle_outline,
              color: account?['automation_paused'] == true
                  ? Colors.orange.shade800
                  : Colors.green.shade700,
            ),
            onChanged: _toggleAutomationPaused,
          ),
          Text('Execução', style: Theme.of(context).textTheme.titleMedium),
          SegmentedButton<String>(
            segments: [
              const ButtonSegment(value: 'paper', label: Text('Paper')),
              ButtonSegment(
                value: 'live',
                label: Text(isUsdAccount ? 'Live Alpaca' : 'Live Inter'),
              ),
            ],
            selected: {executionMode},
            onSelectionChanged: (s) => _setExecutionMode(s.first),
          ),
          if (executionMode == 'live' && !isUsdAccount)
            const Padding(
              padding: EdgeInsets.only(top: 8, bottom: 8),
              child: Text(
                'Live: ao aprovar, você ainda precisa lançar a ordem no Home Broker do Inter e marcar como executada aqui. Sem API automática PF.',
                style: TextStyle(fontSize: 13),
              ),
            ),
          if (executionMode == 'live' && isUsdAccount)
            const Padding(
              padding: EdgeInsets.only(top: 8, bottom: 8),
              child: Text(
                'Live Alpaca: ordens via API quando as keys estiverem configuradas no servidor.',
                style: TextStyle(fontSize: 13),
              ),
            ),
          TextField(
            controller: autoScoreCtrl,
            decoration: const InputDecoration(labelText: 'Score mínimo auto-aprovar'),
            keyboardType: TextInputType.number,
          ),
          TextField(
            controller: autoLimitCtrl,
            decoration: const InputDecoration(labelText: 'Limite diário de auto-aprovações'),
            keyboardType: TextInputType.number,
          ),
          if (!isUsdAccount) ...[
            const Divider(),
            SwitchListTile(
              title: const Text('Preferir dividendos mensais'),
              value: preferMonthly,
              onChanged: (v) => setState(() => preferMonthly = v),
            ),
            const Text('Classes permitidas'),
            CheckboxListTile(
              title: const Text('FII'),
              value: allowFii,
              onChanged: (v) => setState(() => allowFii = v ?? true),
            ),
            CheckboxListTile(
              title: const Text('BDR REIT'),
              value: allowBdr,
              onChanged: (v) => setState(() => allowBdr = v ?? true),
            ),
            TextField(
              controller: effCtrl,
              decoration: const InputDecoration(
                labelText: 'Yield efetivo mínimo (%)',
                helperText: 'FII: DY bruto · BDR: DY líquido após withholding',
              ),
              keyboardType: TextInputType.number,
            ),
            TextField(
              controller: pvpCtrl,
              decoration: const InputDecoration(labelText: 'P/VP máximo'),
              keyboardType: TextInputType.number,
            ),
            TextField(
              controller: volCtrl,
              decoration: const InputDecoration(labelText: 'Volume médio mínimo (R\$)'),
              keyboardType: TextInputType.number,
            ),
            TextField(
              controller: thrCtrl,
              decoration: const InputDecoration(labelText: 'Limiar de score'),
              keyboardType: TextInputType.number,
            ),
            const Divider(),
            Text('Swing Desk', style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: 4),
            const Text(
              'Freios: máx. posições, piso de caixa %, risco A/B. O sizing usa o caixa (cash) da conta.',
              style: TextStyle(fontSize: 13),
            ),
            TextField(
              controller: swingEquityCtrl,
              decoration: const InputDecoration(
                labelText: 'Caixa / equity de referência (R\$)',
                helperText: 'Ao salvar, atualiza cash_brl e swing_equity_brl',
              ),
              keyboardType: TextInputType.number,
            ),
            TextField(
              controller: swingMaxPosCtrl,
              decoration: const InputDecoration(labelText: 'Máx. posições abertas'),
              keyboardType: TextInputType.number,
            ),
            TextField(
              controller: swingFloorCtrl,
              decoration: const InputDecoration(labelText: 'Piso caixa (%)'),
              keyboardType: TextInputType.number,
            ),
            TextField(
              controller: swingRiskACtrl,
              decoration: const InputDecoration(labelText: 'Risco score A (% equity)'),
              keyboardType: TextInputType.number,
            ),
            TextField(
              controller: swingRiskBCtrl,
              decoration: const InputDecoration(labelText: 'Risco score B (% equity)'),
              keyboardType: TextInputType.number,
            ),
          ] else ...[
            const Divider(),
            Text('High-Vol NM', style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: 4),
            const Text(
              'Freios USD: posições distintas, teto por ticker (scale-in) e piso de caixa — abaixo do piso só score A (imperdível).',
              style: TextStyle(fontSize: 13),
            ),
            TextField(
              controller: hvDipEquityCtrl,
              decoration: const InputDecoration(
                labelText: 'Patrimônio / caixa de referência (US\$)',
                helperText: 'Ao salvar, atualiza cash_usd e hv_dip_equity_usd',
              ),
              keyboardType: TextInputType.number,
            ),
            TextField(
              controller: hvDipMaxPosCtrl,
              decoration: const InputDecoration(
                labelText: 'Máx. posições abertas (tickers distintos)',
                helperText: 'Tranches no mesmo ticker não contam slot extra',
              ),
              keyboardType: TextInputType.number,
            ),
            TextField(
              controller: hvDipMaxTickerPctCtrl,
              decoration: const InputDecoration(
                labelText: 'Máx. por ticker (% do patrimônio)',
                helperText: 'Teto total em um ticker (tranches somadas); ajuste conforme a oportunidade',
              ),
              keyboardType: TextInputType.number,
            ),
            TextField(
              controller: hvDipFloorCtrl,
              decoration: const InputDecoration(
                labelText: 'Piso de caixa (% do patrimônio)',
                helperText: 'Com menos caixa que isso, só novas compras score A (imperdível)',
              ),
              keyboardType: TextInputType.number,
            ),
          ],
          const SizedBox(height: 16),
          FilledButton(
            onPressed: saving ? null : _saveRules,
            child: Text(saving ? 'Salvando...' : 'Salvar regras'),
          ),
          const Divider(height: 32),
          Text('Conta', style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: 8),
          OutlinedButton(
            onPressed: saving ? null : _changePasswordDialog,
            child: const Text('Alterar senha'),
          ),
        ],
      ),
    );
  }

  Future<void> _changePasswordDialog() async {
    final current = TextEditingController();
    final next = TextEditingController();
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Alterar senha'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            TextField(
              controller: current,
              obscureText: true,
              decoration: const InputDecoration(labelText: 'Senha atual'),
            ),
            TextField(
              controller: next,
              obscureText: true,
              decoration: const InputDecoration(labelText: 'Nova senha'),
            ),
          ],
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancelar')),
          FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Salvar')),
        ],
      ),
    );
    if (ok != true || !mounted) return;
    try {
      final api = context.read<ApiClient>();
      await api.post('/auth/change-password', {
        'current_password': current.text,
        'new_password': next.text,
      });
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Senha alterada')),
      );
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('$e')));
    } finally {
      current.dispose();
      next.dispose();
    }
  }
}
