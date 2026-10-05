import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../core/api_client.dart';
import '../../core/format.dart';
import 'dashboard_controller.dart';
import 'dashboard_view.dart';

/// Dashboard desktop: visão global de todas as contas (sem escopo por conta).
class DashboardScreen extends StatefulWidget {
  const DashboardScreen({super.key});

  @override
  State<DashboardScreen> createState() => _DashboardScreenState();
}

class _DashboardScreenState extends State<DashboardScreen> {
  late final DashboardController _controller =
      DashboardController(context.read<ApiClient>());

  @override
  void initState() {
    super.initState();
    _controller.load();
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Dashboard'),
        actions: [
          ListenableBuilder(
            listenable: _controller,
            builder: (context, _) {
              final t = _controller.data?.updatedAt;
              if (t == null) return const SizedBox.shrink();
              return Center(
                child: Padding(
                  padding: const EdgeInsets.only(right: 8),
                  child: Text(
                    'Atualizado ${formatRefreshedAt(t.toIso8601String())}',
                    style: Theme.of(context).textTheme.labelSmall?.copyWith(
                          color: Theme.of(context).colorScheme.onSurfaceVariant,
                        ),
                  ),
                ),
              );
            },
          ),
          IconButton(
            tooltip: 'Atualizar',
            onPressed: _controller.load,
            icon: const Icon(Icons.refresh),
          ),
        ],
      ),
      body: Padding(
        padding: const EdgeInsets.all(16),
        child: DashboardView(controller: _controller, isWide: true),
      ),
    );
  }
}
