import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'package:provider/provider.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../app/selected_account.dart';
import '../../core/api_client.dart';
import '../../data/models/news.dart';
import '../../data/repositories/news_repository.dart';
import 'master_detail.dart';

/// Desktop Notícias: master list of news + detail with open-in-browser.
class NewsScreen extends StatefulWidget {
  const NewsScreen({super.key});

  @override
  State<NewsScreen> createState() => _NewsScreenState();
}

class _NewsScreenState extends State<NewsScreen> {
  List<NewsItem> _items = [];
  NewsItem? _selected;
  bool _loading = false;
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
    if (_accountId.isEmpty) {
      setState(() {
        _items = [];
        _selected = null;
      });
      return;
    }
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final repo = NewsRepository(context.read<ApiClient>());
      _items = await repo.list(_accountId);
      _items.sort((a, b) {
        final at = a.publishedAt ?? DateTime.fromMillisecondsSinceEpoch(0);
        final bt = b.publishedAt ?? DateTime.fromMillisecondsSinceEpoch(0);
        return bt.compareTo(at);
      });
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
        title:
            Text(account == null ? 'Notícias' : 'Notícias · ${account.name}'),
        actions: [
          if (account != null)
            IconButton(onPressed: _reload, icon: const Icon(Icons.refresh)),
        ],
      ),
      body: account == null
          ? const PaneEmpty(
              message: 'Selecione uma conta na aba Contas.',
              icon: Icons.newspaper_outlined,
            )
          : _loading
              ? const PaneLoading()
              : _error != null
                  ? PaneError(message: _error!, onRetry: _reload)
                  : MasterDetail(
                      master: _NewsList(
                        items: _items,
                        selectedId: _selected?.id,
                        onSelect: (n) => setState(() => _selected = n),
                      ),
                      detail: _selected == null
                          ? const PaneEmpty(message: 'Selecione uma notícia.')
                          : _NewsDetail(item: _selected!),
                    ),
    );
  }
}

class _NewsList extends StatelessWidget {
  const _NewsList({
    required this.items,
    required this.selectedId,
    required this.onSelect,
  });

  final List<NewsItem> items;
  final String? selectedId;
  final void Function(NewsItem) onSelect;

  @override
  Widget build(BuildContext context) {
    if (items.isEmpty) {
      return const PaneEmpty(message: 'Nenhuma notícia.');
    }
    return ListView.separated(
      itemCount: items.length,
      separatorBuilder: (_, __) => const Divider(height: 1),
      itemBuilder: (context, i) {
        final n = items[i];
        return ListTile(
          selected: n.id == selectedId,
          dense: true,
          title: Text(n.title, maxLines: 2, overflow: TextOverflow.ellipsis),
          subtitle: Text('${n.ticker ?? 'geral'} · ${n.source}'),
          onTap: () => onSelect(n),
        );
      },
    );
  }
}

class _NewsDetail extends StatelessWidget {
  const _NewsDetail({required this.item});

  final NewsItem item;

  @override
  Widget build(BuildContext context) {
    final date = item.publishedAt == null
        ? '—'
        : DateFormat.yMMMd('pt_BR')
            .add_Hm()
            .format(item.publishedAt!.toLocal());
    return ListView(
      padding: const EdgeInsets.all(20),
      children: [
        Text(item.title, style: Theme.of(context).textTheme.headlineSmall),
        const SizedBox(height: 8),
        Text(
          '${item.ticker ?? 'Geral'} · ${item.source} · $date',
          style: Theme.of(context).textTheme.bodySmall,
        ),
        const SizedBox(height: 16),
        FilledButton.icon(
          onPressed: () => launchUrl(
            Uri.parse(item.url),
            mode: LaunchMode.externalApplication,
          ),
          icon: const Icon(Icons.open_in_browser),
          label: const Text('Abrir no navegador'),
        ),
      ],
    );
  }
}
