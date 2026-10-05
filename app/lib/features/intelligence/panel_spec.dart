import 'package:flutter/material.dart';

/// Size of an intelligence panel (controls its height / content density).
enum PanelSize {
  small,
  medium,
  large;

  double get height => switch (this) {
        PanelSize.small => 200,
        PanelSize.medium => 340,
        PanelSize.large => 500,
      };

  String get label => switch (this) {
        PanelSize.small => 'S',
        PanelSize.medium => 'M',
        PanelSize.large => 'L',
      };
}

/// Declarative description of an intelligence panel.
class PanelSpec {
  const PanelSpec({
    required this.id,
    required this.title,
    required this.icon,
    required this.builder,
  });

  final String id;
  final String title;
  final IconData icon;

  /// Builds the panel content for a given account and refresh tick. The tick
  /// increments on a manual "refresh all" and triggers panel reloads.
  final Widget Function(BuildContext context, String accountId, int refreshTick)
      builder;
}
