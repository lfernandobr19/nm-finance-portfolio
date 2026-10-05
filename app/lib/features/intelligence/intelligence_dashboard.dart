import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../app/selected_account.dart';
import '../../core/api_client.dart';
import '../../data/repositories/intelligence_repository.dart';
import '../desktop/master_detail.dart';
import 'intelligence_store.dart';
import 'panel_layout.dart';
import 'panel_registry.dart';
import 'panel_spec.dart';

/// Customizable Intelligence Center. Modular panels (equal weight by
/// default) rendered in a reorderable stack; a "Personalizar" mode exposes
/// drag-to-reorder, per-panel size (S/M/L) and visibility toggles, all
/// persisted across launches via [PanelLayout].
class IntelligenceDashboard extends StatefulWidget {
  const IntelligenceDashboard({super.key});

  @override
  State<IntelligenceDashboard> createState() => _IntelligenceDashboardState();
}

class _IntelligenceDashboardState extends State<IntelligenceDashboard> {
  final PanelLayout _layout = PanelLayout();
  IntelligenceStore? _store;
  bool _personalize = false;
  int _refreshTick = 0;
  String _accountId = '';

  @override
  void initState() {
    super.initState();
    _layout.load(PanelRegistry.all.map((p) => p.id).toList());
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    _accountId = context.read<SelectedAccount>().accountId;
    _store ??= IntelligenceStore(
      IntelligenceRepository(context.read<ApiClient>()),
    )..start();
  }

  @override
  void dispose() {
    _store?.dispose();
    _layout.dispose();
    super.dispose();
  }

  List<PanelSpec> get _visibleSpecs => _layout.order
      .where((id) => !_layout.isHidden(id))
      .map(PanelRegistry.byId)
      .toList();

  @override
  Widget build(BuildContext context) {
    final account = context.watch<SelectedAccount>().current;
    return Scaffold(
      appBar: AppBar(
        title: Text(account == null
            ? 'Inteligência'
            : 'Inteligência · ${account.name}'),
        actions: [
          IconButton(
            tooltip: 'Atualizar painéis',
            onPressed: account == null
                ? null
                : () {
                    setState(() => _refreshTick++);
                    _store?.refresh();
                  },
            icon: const Icon(Icons.refresh),
          ),
          if (_personalize)
            PopupMenuButton<String>(
              tooltip: 'Mais ações',
              icon: const Icon(Icons.more_vert),
              onSelected: (value) {
                if (value == 'reset') {
                  _layout.reset(PanelRegistry.all.map((p) => p.id).toList());
                }
              },
              itemBuilder: (context) => const [
                PopupMenuItem(
                  value: 'reset',
                  child: Text('Restaurar layout padrão'),
                ),
              ],
            ),
          IconButton(
            tooltip: _personalize ? 'Concluir personalização' : 'Personalizar',
            onPressed: () => setState(() => _personalize = !_personalize),
            icon: Icon(_personalize ? Icons.check : Icons.tune),
          ),
        ],
      ),
      body: account == null
          ? const PaneEmpty(
              message: 'Selecione uma conta na aba Contas.',
              icon: Icons.insights,
            )
          : !_layout.loaded
              ? const PaneLoading()
              : ChangeNotifierProvider<IntelligenceStore>.value(
                  value: _store!,
                  child: _buildBody(context),
                ),
    );
  }

  Widget _buildBody(BuildContext context) {
    final specs = _visibleSpecs;
    if (specs.isEmpty) {
      return const PaneEmpty(
        message: 'Todos os painéis estão ocultos.\n'
            'Use "Personalizar" para reexibir.',
        icon: Icons.dashboard_customize_outlined,
      );
    }

    final children = <Widget>[
      for (var i = 0; i < specs.length; i++)
        _PanelCard(
          key: ValueKey(specs[i].id),
          index: i,
          spec: specs[i],
          accountId: _accountId,
          refreshTick: _refreshTick,
          size: _layout.sizeOf(specs[i].id),
          personalize: _personalize,
          onHide: () => _layout.toggleHidden(specs[i].id),
          onSize: (size) => _layout.setSize(specs[i].id, size),
        ),
    ];

    if (_personalize) {
      return ReorderableListView(
        buildDefaultDragHandles: false,
        padding: const EdgeInsets.all(12),
        onReorderItem: _layout.reorderVisible,
        children: children,
      );
    }
    return ListView(
      padding: const EdgeInsets.all(12),
      children: children,
    );
  }
}

class _PanelCard extends StatelessWidget {
  const _PanelCard({
    super.key,
    required this.index,
    required this.spec,
    required this.accountId,
    required this.refreshTick,
    required this.size,
    required this.personalize,
    required this.onHide,
    required this.onSize,
  });

  final int index;
  final PanelSpec spec;
  final String accountId;
  final int refreshTick;
  final PanelSize size;
  final bool personalize;
  final VoidCallback onHide;
  final ValueChanged<PanelSize> onSize;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Card(
      margin: const EdgeInsets.only(bottom: 12),
      clipBehavior: Clip.antiAlias,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Container(
            color: scheme.surfaceContainerHigh.withValues(alpha: 0.6),
            padding:
                const EdgeInsets.only(left: 8, right: 4, top: 4, bottom: 4),
            child: Row(
              children: [
                if (personalize)
                  ReorderableDragStartListener(
                    index: index,
                    child: const Padding(
                      padding: EdgeInsets.only(right: 8),
                      child: Icon(Icons.drag_indicator, size: 20),
                    ),
                  ),
                Icon(spec.icon, size: 18, color: scheme.primary),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    spec.title,
                    style: Theme.of(context)
                        .textTheme
                        .titleSmall
                        ?.copyWith(fontWeight: FontWeight.w700),
                  ),
                ),
                if (personalize) ...[
                  PopupMenuButton<PanelSize>(
                    tooltip: 'Tamanho do painel',
                    icon: const Icon(Icons.unfold_more, size: 18),
                    initialValue: size,
                    onSelected: onSize,
                    itemBuilder: (context) => [
                      for (final s in PanelSize.values)
                        CheckedPopupMenuItem(
                          value: s,
                          checked: s == size,
                          child: Text('${s.label} · ${s.height.toInt()}px'),
                        ),
                    ],
                  ),
                  IconButton(
                    tooltip: 'Ocultar painel',
                    visualDensity: VisualDensity.compact,
                    onPressed: onHide,
                    icon: const Icon(Icons.visibility_off_outlined, size: 18),
                  ),
                ],
              ],
            ),
          ),
          SizedBox(
            height: size.height,
            child: spec.builder(context, accountId, refreshTick),
          ),
        ],
      ),
    );
  }
}
