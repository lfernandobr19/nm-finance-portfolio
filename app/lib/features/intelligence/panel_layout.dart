import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'panel_spec.dart';

/// Persisted, editable layout of the intelligence dashboard: panel order,
/// visibility (hidden set) and per-panel size. Preferences are stored in
/// [SharedPreferences] as JSON and restored on load, falling back to the
/// registry defaults (equal weight = medium size, all visible, registry order).
class PanelLayout extends ChangeNotifier {
  static const _prefsKey = 'intel_panel_layout_v1';

  List<String> _order = [];
  final Set<String> _hidden = {};
  final Map<String, PanelSize> _sizes = {};
  bool _loaded = false;

  bool get loaded => _loaded;

  List<String> get order => List.unmodifiable(_order);

  Set<String> get hidden => Set.unmodifiable(_hidden);

  PanelSize sizeOf(String id) => _sizes[id] ?? PanelSize.medium;

  bool isHidden(String id) => _hidden.contains(id);

  /// Loads persisted layout, reconciling against [defaultOrder] so that newly
  /// added panels appear and removed ids are dropped.
  Future<void> load(List<String> defaultOrder) async {
    _order = List.of(defaultOrder);
    _sizes.clear();
    _hidden.clear();
    try {
      final prefs = await SharedPreferences.getInstance();
      final raw = prefs.getString(_prefsKey);
      if (raw != null) {
        final data = jsonDecode(raw) as Map<String, dynamic>;
        final savedOrder = (data['order'] as List?)?.cast<String>() ?? const [];
        final known = <String>[];
        for (final id in savedOrder) {
          if (defaultOrder.contains(id) && !known.contains(id)) known.add(id);
        }
        for (final id in defaultOrder) {
          if (!known.contains(id)) known.add(id);
        }
        _order = known;

        final savedSizes =
            (data['sizes'] as Map?)?.cast<String, dynamic>() ?? const {};
        savedSizes.forEach((id, name) {
          _sizes[id] = PanelSize.values.firstWhere(
            (s) => s.name == name,
            orElse: () => PanelSize.medium,
          );
        });

        final savedHidden =
            (data['hidden'] as List?)?.cast<String>() ?? const [];
        _hidden.addAll(savedHidden.where(defaultOrder.contains));
      }
    } catch (_) {
      // Any parse/IO error falls back to defaults.
    }
    _loaded = true;
    notifyListeners();
  }

  /// Reorders visible panels. Indices refer to the filtered, visible list and
  /// follow `ReorderableListView.onReorderItem` semantics (newIndex is already
  /// adjusted for the removed item).
  void reorderVisible(int oldIndex, int newIndex) {
    final visible = _order.where((id) => !_hidden.contains(id)).toList();
    if (oldIndex < 0 || oldIndex >= visible.length) return;
    final item = visible.removeAt(oldIndex);
    visible.insert(newIndex.clamp(0, visible.length), item);
    final hiddenIds = _order.where((id) => _hidden.contains(id)).toList();
    _order = [...visible, ...hiddenIds];
    notifyListeners();
    _save();
  }

  void toggleHidden(String id) {
    if (!_hidden.add(id)) _hidden.remove(id);
    notifyListeners();
    _save();
  }

  void setSize(String id, PanelSize size) {
    _sizes[id] = size;
    notifyListeners();
    _save();
  }

  Future<void> reset(List<String> defaultOrder) async {
    _order = List.of(defaultOrder);
    _sizes.clear();
    _hidden.clear();
    notifyListeners();
    await _save();
  }

  Future<void> _save() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      await prefs.setString(
        _prefsKey,
        jsonEncode({
          'order': _order,
          'sizes': _sizes.map((k, v) => MapEntry(k, v.name)),
          'hidden': _hidden.toList(),
        }),
      );
    } catch (_) {
      // Best-effort persistence; never crash the UI.
    }
  }
}
