import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../app/selected_account.dart';
import '../../core/api_client.dart';
import '../../core/format.dart';
import '../settings/settings_page.dart';
import 'master_detail.dart';

/// Desktop Regras: two-column layout — read-only current values on the left,
/// editable form (reused [SettingsPage]) on the right.
class RulesScreen extends StatefulWidget {
  const RulesScreen({super.key});

  @override
  State<RulesScreen> createState() => _RulesScreenState();
}

class _RulesScreenState extends State<RulesScreen> {
  Map<String, dynamic>? _account;
  Map<String, dynamic>? _rules;
  bool _loading = false;
  String? _error;
  String _accountId = '';

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final accountId = context.watch<SelectedAccount>().accountId;
    if (_accountId != accountId) {
      _accountId = accountId;
      _reload();
    }
  }

  Future<void> _reload() async {
    if (_accountId.isEmpty) {
      setState(() {
        _account = null;
        _rules = null;
      });
      return;
    }
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final api = context.read<ApiClient>();
      _account = await api.getMap('/accounts/$_accountId');
      _rules = await api.getMap('/accounts/$_accountId/rules');
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
        title: Text(account == null ? 'Regras' : 'Regras · ${account.name}'),
        actions: [
          if (account != null)
            IconButton(onPressed: _reload, icon: const Icon(Icons.refresh)),
        ],
      ),
      body: account == null
          ? const PaneEmpty(
              message: 'Selecione uma conta na aba Contas.',
              icon: Icons.tune,
            )
          : MasterDetail(
              masterWidth: 320,
              master: _RulesSummary(
                loading: _loading,
                error: _error,
                account: _account,
                rules: _rules,
                onRetry: _reload,
              ),
              detail: SettingsPage(accountId: account.id),
            ),
    );
  }
}

class _RulesSummary extends StatelessWidget {
  const _RulesSummary({
    required this.loading,
    required this.error,
    required this.account,
    required this.rules,
    required this.onRetry,
  });

  final bool loading;
  final String? error;
  final Map<String, dynamic>? account;
  final Map<String, dynamic>? rules;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    if (loading) return const PaneLoading();
    if (error != null) return PaneError(message: error!, onRetry: onRetry);
    final a = account ?? const {};
    final r = rules ?? const {};
    final isUsd = (a['currency'] as String?) == 'USD' ||
        (a['broker_code'] as String?)?.toLowerCase() == 'alpaca';
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        Text('Valores atuais', style: Theme.of(context).textTheme.titleMedium),
        const SizedBox(height: 12),
        _row(context, 'Execução', a['execution_mode'] ?? 'paper'),
        _row(context, 'Auto-aprovar',
            a['auto_approve_enabled'] == true ? 'ligado' : 'desligado'),
        _row(context, 'Score mín. auto',
            formatScore(a['auto_approve_min_score'])),
        _row(context, 'Limite diário', '${a['daily_auto_approve_limit'] ?? 0}'),
        if (!isUsd) ...[
          _row(context, 'Yield efetivo mín.',
              formatPct(r['min_effective_yield'])),
          _row(context, 'P/VP máx.', formatRatio(r['max_p_vp'])),
          _row(context, 'Volume mín.', formatQty(r['min_avg_volume'])),
          _row(context, 'Score limiar', formatScore(r['score_threshold'])),
          _row(
            context,
            'Mensal?',
            r['prefer_monthly_dividends'] != false ? 'sim' : 'não',
          ),
          _row(context, 'Máx. posições', '${a['swing_max_positions'] ?? 5}'),
          _row(context, 'Piso caixa %', formatPct(a['swing_cash_floor_pct'])),
          _row(context, 'Risco A %', formatPct(a['swing_risk_pct_a'])),
          _row(context, 'Risco B %', formatPct(a['swing_risk_pct_b'])),
        ] else ...[
          _row(
              context, 'Máx. posições NM', '${a['hv_dip_max_positions'] ?? 4}'),
          _row(context, 'Teto por ticker %',
              formatPct(a['hv_dip_max_ticker_pct'])),
          _row(context, 'Piso caixa %', formatPct(a['hv_dip_cash_floor_pct'])),
        ],
        const SizedBox(height: 16),
        Text(
          'Edite os valores à direita e salve.',
          style: Theme.of(context).textTheme.bodySmall?.copyWith(
                color: Theme.of(context).colorScheme.onSurfaceVariant,
              ),
        ),
      ],
    );
  }

  Widget _row(BuildContext context, String label, String value) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Expanded(
            child: Text(label, style: Theme.of(context).textTheme.labelMedium),
          ),
          const SizedBox(width: 8),
          Flexible(
            child: Text(
              value,
              textAlign: TextAlign.end,
              style: Theme.of(context)
                  .textTheme
                  .bodyMedium
                  ?.copyWith(fontWeight: FontWeight.w600),
            ),
          ),
        ],
      ),
    );
  }
}
