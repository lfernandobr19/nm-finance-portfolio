import 'dart:convert';

import 'package:fiidesk/features/intelligence/panel_layout.dart';
import 'package:fiidesk/features/intelligence/panel_registry.dart';
import 'package:fiidesk/features/intelligence/panel_spec.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  const defaultOrder = [
    'pulse',
    'radar',
    'calibration',
    'catalysts',
    'analytics',
    'regime',
    'equity',
    'studies',
    'signals',
    'assertiveness',
  ];

  setUp(() {
    SharedPreferences.setMockInitialValues({});
  });

  group('PanelRegistry', () {
    test('registers twelve panels with unique ids', () {
      expect(PanelRegistry.all, hasLength(12));
      final ids = PanelRegistry.all.map((p) => p.id).toSet();
      expect(ids, hasLength(12));
    });

    test('byId resolves a panel and falls back on unknown ids', () {
      expect(PanelRegistry.byId('pulse').title, 'Pulso');
      expect(PanelRegistry.byId('equity').title, 'Curva de Equity');
      expect(PanelRegistry.byId('does-not-exist').id, 'pulse');
    });
  });

  group('PanelLayout defaults', () {
    test('loads registry defaults when no preference is stored', () async {
      final layout = PanelLayout();
      await layout.load(defaultOrder);
      expect(layout.loaded, isTrue);
      expect(layout.order, defaultOrder);
      expect(layout.hidden, isEmpty);
      for (final id in defaultOrder) {
        expect(layout.sizeOf(id), PanelSize.medium);
      }
    });

    test('sizeOf returns medium for unknown ids', () async {
      final layout = PanelLayout();
      await layout.load(defaultOrder);
      expect(layout.sizeOf('unknown'), PanelSize.medium);
    });
  });

  group('PanelLayout persistence', () {
    test('restores order, sizes and hidden from stored JSON', () async {
      SharedPreferences.setMockInitialValues({
        'intel_panel_layout_v1': jsonEncode({
          'order': ['equity', 'radar', 'catalysts'],
          'sizes': {'equity': 'large', 'radar': 'small'},
          'hidden': ['catalysts'],
        }),
      });
      final layout = PanelLayout();
      await layout.load(defaultOrder);

      // Saved ids keep their relative order first, new ids appended.
      expect(layout.order, [
        'equity',
        'radar',
        'catalysts',
        'pulse',
        'calibration',
        'analytics',
        'regime',
        'studies',
        'signals',
        'assertiveness',
      ]);
      expect(layout.sizeOf('equity'), PanelSize.large);
      expect(layout.sizeOf('radar'), PanelSize.small);
      expect(layout.isHidden('catalysts'), isTrue);
      expect(layout.isHidden('equity'), isFalse);
    });

    test('drops unknown ids and keeps only known ones', () async {
      SharedPreferences.setMockInitialValues({
        'intel_panel_layout_v1': jsonEncode({
          'order': ['legacy-panel', 'equity'],
          'sizes': {},
          'hidden': ['legacy-panel'],
        }),
      });
      final layout = PanelLayout();
      await layout.load(defaultOrder);
      expect(layout.order.contains('legacy-panel'), isFalse);
      expect(layout.hidden.contains('legacy-panel'), isFalse);
      expect(layout.order.first, 'equity');
    });

    test('saves after a mutation and reloads from storage', () async {
      final layout = PanelLayout();
      await layout.load(defaultOrder);
      layout.setSize('radar', PanelSize.large);
      layout.toggleHidden('analytics');

      final reloaded = PanelLayout();
      await reloaded.load(defaultOrder);
      expect(reloaded.sizeOf('radar'), PanelSize.large);
      expect(reloaded.isHidden('analytics'), isTrue);
    });
  });

  group('PanelLayout mutations', () {
    test('reorderVisible moves a visible item', () async {
      final layout = PanelLayout();
      await layout.load(defaultOrder);
      layout.reorderVisible(0, 2);
      expect(layout.order, [
        'radar',
        'calibration',
        'pulse',
        'catalysts',
        'analytics',
        'regime',
        'equity',
        'studies',
        'signals',
        'assertiveness',
      ]);
    });

    test('reorderVisible keeps hidden panels at the end', () async {
      final layout = PanelLayout();
      await layout.load(defaultOrder);
      layout.toggleHidden('radar');
      layout.reorderVisible(0, 3);
      // visible = [calibration, catalysts, analytics, regime, equity, studies, signals]
      expect(layout.order, [
        'calibration',
        'catalysts',
        'analytics',
        'pulse',
        'regime',
        'equity',
        'studies',
        'signals',
        'assertiveness',
        'radar',
      ]);
    });

    test('toggleHidden round-trips visibility', () async {
      final layout = PanelLayout();
      await layout.load(defaultOrder);
      expect(layout.isHidden('radar'), isFalse);
      layout.toggleHidden('radar');
      expect(layout.isHidden('radar'), isTrue);
      layout.toggleHidden('radar');
      expect(layout.isHidden('radar'), isFalse);
    });

    test('reset restores defaults', () async {
      final layout = PanelLayout();
      await layout.load(defaultOrder);
      layout.setSize('radar', PanelSize.large);
      layout.toggleHidden('analytics');
      layout.reorderVisible(0, 2);

      await layout.reset(defaultOrder);
      expect(layout.order, defaultOrder);
      expect(layout.hidden, isEmpty);
      expect(layout.sizeOf('radar'), PanelSize.medium);
    });
  });
}
