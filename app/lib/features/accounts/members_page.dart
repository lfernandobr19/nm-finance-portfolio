import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';

import '../../core/api_client.dart';

class MembersPage extends StatefulWidget {
  const MembersPage({super.key, required this.accountId});

  final String accountId;

  @override
  State<MembersPage> createState() => _MembersPageState();
}

class _MembersPageState extends State<MembersPage> {
  List<dynamic> members = [];
  List<dynamic> invites = [];
  bool loading = true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final api = context.read<ApiClient>();
    members = await api.getList('/accounts/${widget.accountId}/members');
    invites = await api.getList('/accounts/${widget.accountId}/invites');
    if (mounted) setState(() => loading = false);
  }

  Future<void> _invite(String role) async {
    final api = context.read<ApiClient>();
    final invite = await api.post('/accounts/${widget.accountId}/invites', {'role': role});
    final code = invite['code'] as String;
    await Clipboard.setData(ClipboardData(text: code));
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text('Convite $code copiado')),
    );
    await _load();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Membros e convites')),
      body: loading
          ? const Center(child: CircularProgressIndicator())
          : ListView(
              padding: const EdgeInsets.all(16),
              children: [
                Text('Membros', style: Theme.of(context).textTheme.titleMedium),
                ...members.map((m) {
                  final map = m as Map<String, dynamic>;
                  return ListTile(
                    title: Text(map['full_name'] as String? ?? map['email'] as String? ?? ''),
                    subtitle: Text('${map['email']} · ${map['role']}'),
                  );
                }),
                const SizedBox(height: 16),
                Text('Convites abertos', style: Theme.of(context).textTheme.titleMedium),
                ...invites.map((i) {
                  final map = i as Map<String, dynamic>;
                  return ListTile(
                    title: Text(map['code'] as String),
                    subtitle: Text('Papel: ${map['role']}'),
                    trailing: IconButton(
                      icon: const Icon(Icons.copy),
                      onPressed: () => Clipboard.setData(
                        ClipboardData(text: map['code'] as String),
                      ),
                    ),
                  );
                }),
                const SizedBox(height: 16),
                FilledButton(
                  onPressed: () => _invite('operator'),
                  child: const Text('Convidar operador'),
                ),
                const SizedBox(height: 8),
                OutlinedButton(
                  onPressed: () => _invite('viewer'),
                  child: const Text('Convidar visualizador'),
                ),
              ],
            ),
    );
  }
}
