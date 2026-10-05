import 'package:flutter/material.dart';

import 'evolution_panels.dart';
import 'intelligence_panels.dart';
import 'panel_spec.dart';

/// Declarative registry of the intelligence panels. The dashboard reads the
/// order/visibility/size preferences from [PanelLayout] and builds each panel
/// through its [PanelSpec.builder].
class PanelRegistry {
  PanelRegistry._();

  static final List<PanelSpec> all = [
    const PanelSpec(
      id: 'pulse',
      title: 'Pulso',
      icon: Icons.monitor_heart_outlined,
      builder: _pulse,
    ),
    const PanelSpec(
      id: 'radar',
      title: 'Radar de Observação',
      icon: Icons.radar,
      builder: _radar,
    ),
    const PanelSpec(
      id: 'calibration',
      title: 'Auto-calibração',
      icon: Icons.auto_fix_high,
      builder: _calibration,
    ),
    const PanelSpec(
      id: 'catalysts',
      title: 'Feed de Catalisadores',
      icon: Icons.campaign_outlined,
      builder: _catalysts,
    ),
    const PanelSpec(
      id: 'analytics',
      title: 'Analytics Profunda',
      icon: Icons.query_stats,
      builder: _analytics,
    ),
    const PanelSpec(
      id: 'regime',
      title: 'Regime + Circuit Breaker',
      icon: Icons.speed,
      builder: _regime,
    ),
    const PanelSpec(
      id: 'equity',
      title: 'Curva de Equity',
      icon: Icons.show_chart,
      builder: _equity,
    ),
    const PanelSpec(
      id: 'studies',
      title: 'Estudos Ativos',
      icon: Icons.query_stats,
      builder: _studies,
    ),
    const PanelSpec(
      id: 'signals',
      title: 'Sinais Day Trade',
      icon: Icons.bolt_outlined,
      builder: _signals,
    ),
    const PanelSpec(
      id: 'assertiveness',
      title: 'Assertividade',
      icon: Icons.verified_outlined,
      builder: _assertiveness,
    ),
    const PanelSpec(
      id: 'evolution',
      title: 'Linha do tempo',
      icon: Icons.timeline,
      builder: _evolution,
    ),
    const PanelSpec(
      id: 'memory',
      title: 'Memória',
      icon: Icons.psychology_outlined,
      builder: _memory,
    ),
  ];

  static PanelSpec byId(String id) =>
      all.firstWhere((p) => p.id == id, orElse: () => all.first);

  static Widget _pulse(BuildContext c, String a, int r) =>
      PulsePanel(accountId: a, refreshTick: r);
  static Widget _radar(BuildContext c, String a, int r) =>
      RadarPanel(accountId: a, refreshTick: r);
  static Widget _calibration(BuildContext c, String a, int r) =>
      CalibrationPanel(accountId: a, refreshTick: r);
  static Widget _catalysts(BuildContext c, String a, int r) =>
      CatalystsPanel(accountId: a, refreshTick: r);
  static Widget _analytics(BuildContext c, String a, int r) =>
      AnalyticsPanel(accountId: a, refreshTick: r);
  static Widget _regime(BuildContext c, String a, int r) =>
      RegimePanel(accountId: a, refreshTick: r);
  static Widget _equity(BuildContext c, String a, int r) =>
      EquityPanel(accountId: a, refreshTick: r);
  static Widget _studies(BuildContext c, String a, int r) =>
      StudiesPanel(accountId: a, refreshTick: r);
  static Widget _signals(BuildContext c, String a, int r) =>
      SignalsPanel(accountId: a, refreshTick: r);
  static Widget _assertiveness(BuildContext c, String a, int r) =>
      AssertivenessPanel(accountId: a, refreshTick: r);
  static Widget _evolution(BuildContext c, String a, int r) =>
      EvolutionPanel(accountId: a, refreshTick: r);
  static Widget _memory(BuildContext c, String a, int r) =>
      MemoryPanel(accountId: a, refreshTick: r);
}
