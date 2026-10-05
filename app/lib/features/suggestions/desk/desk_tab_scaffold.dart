import 'package:flutter/material.dart';

import 'desk_summary_header.dart';

/// NestedScrollView + SliverAppBar + TabBarView shell for account desk.
class DeskTabScaffold extends StatelessWidget {
  const DeskTabScaffold({
    super.key,
    required this.tabController,
    required this.isUs,
    required this.portfolio,
    required this.moneyCcy,
    required this.openCount,
    required this.waitingCount,
    required this.pendingCount,
    required this.onRefresh,
    required this.onTapSummary,
    required this.onTapMarket,
    required this.tabBodies,
    this.onTapDayTrade,
    this.deskMode,
    this.onDeskChanged,
    this.loading = false,
  });

  final TabController tabController;
  final bool isUs;
  final Map<String, dynamic>? portfolio;
  final String moneyCcy;
  final int openCount;
  final int waitingCount;
  final int pendingCount;
  final Future<void> Function() onRefresh;
  final VoidCallback onTapSummary;
  final VoidCallback onTapMarket;
  final VoidCallback? onTapDayTrade;
  final List<Widget> tabBodies;
  final String? deskMode;
  final ValueChanged<String>? onDeskChanged;
  final bool loading;

  @override
  Widget build(BuildContext context) {
    if (loading) {
      return const Center(child: CircularProgressIndicator());
    }

    const tabBarHeight = 48.0;
    final headerHeight = isUs ? 72.0 : 96.0;
    final expandedHeight = headerHeight + tabBarHeight;

    return NestedScrollView(
      floatHeaderSlivers: true,
      headerSliverBuilder: (context, innerBoxIsScrolled) {
        final scheme = Theme.of(context).colorScheme;
        return [
          SliverOverlapAbsorber(
            handle: NestedScrollView.sliverOverlapAbsorberHandleFor(context),
            sliver: SliverAppBar(
              pinned: true,
              floating: true,
              snap: true,
              automaticallyImplyLeading: false,
              expandedHeight: expandedHeight,
              collapsedHeight: expandedHeight,
              forceElevated: innerBoxIsScrolled,
              flexibleSpace: FlexibleSpaceBar(
                collapseMode: CollapseMode.pin,
                stretchModes: const [],
                background: Container(
                  color: scheme.surfaceContainerLow,
                  padding: const EdgeInsets.only(left: 12, right: 12, bottom: tabBarHeight),
                  alignment: Alignment.bottomLeft,
                  child: DeskSummaryHeader(
                    portfolio: portfolio,
                    isUs: isUs,
                    moneyCcy: moneyCcy,
                    openCount: openCount,
                    waitingCount: waitingCount,
                    onTapSummary: onTapSummary,
                    onTapMarket: onTapMarket,
                    onTapDayTrade: onTapDayTrade,
                    deskMode: deskMode,
                    onDeskChanged: onDeskChanged,
                    compact: true,
                  ),
                ),
              ),
              bottom: TabBar(
                controller: tabController,
                isScrollable: true,
                tabAlignment: TabAlignment.start,
                labelPadding: const EdgeInsets.symmetric(horizontal: 12),
                tabs: [
                  DeskTabLabel(label: 'Sugestões', count: pendingCount),
                  DeskTabLabel(label: 'Aguardando', count: waitingCount),
                  DeskTabLabel(label: 'Abertas', count: openCount),
                  const DeskTabLabel(label: 'Resultados'),
                ],
              ),
            ),
          ),
        ];
      },
      body: TabBarView(
        controller: tabController,
        children: tabBodies
            .map(
              (body) => RefreshIndicator(
                onRefresh: onRefresh,
                child: body,
              ),
            )
            .toList(),
      ),
    );
  }
}

/// Wraps tab list content with overlap injector for NestedScrollView.
class DeskTabScrollBody extends StatelessWidget {
  const DeskTabScrollBody({super.key, required this.storageKey, required this.children});

  final String storageKey;
  final List<Widget> children;

  @override
  Widget build(BuildContext context) {
    return Builder(
      builder: (context) {
        return CustomScrollView(
          key: PageStorageKey<String>(storageKey),
          slivers: [
            SliverOverlapInjector(
              handle: NestedScrollView.sliverOverlapAbsorberHandleFor(context),
            ),
            SliverPadding(
              padding: const EdgeInsets.fromLTRB(16, 8, 16, 24),
              sliver: SliverList(
                delegate: SliverChildListDelegate(children),
              ),
            ),
          ],
        );
      },
    );
  }
}
