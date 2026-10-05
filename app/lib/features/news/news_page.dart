import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../core/api_client.dart';

class NewsPage extends StatefulWidget {
  const NewsPage({super.key, required this.accountId});

  final String accountId;

  @override
  State<NewsPage> createState() => _NewsPageState();
}

class _NewsPageState extends State<NewsPage> {
  List<dynamic> items = [];
  bool loading = true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    items = await context.read<ApiClient>().getList('/accounts/${widget.accountId}/news');
    if (mounted) setState(() => loading = false);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Notícias')),
      body: loading
          ? const Center(child: CircularProgressIndicator())
          : RefreshIndicator(
              onRefresh: () async {
                setState(() => loading = true);
                await _load();
              },
              child: ListView.builder(
                itemCount: items.length,
                itemBuilder: (context, i) {
                  final m = items[i] as Map<String, dynamic>;
                  return ListTile(
                    title: Text(m['title'] as String? ?? ''),
                    subtitle: Text(
                      '${m['ticker'] ?? 'geral'} · ${m['source'] ?? ''}',
                    ),
                  );
                },
              ),
            ),
    );
  }
}
