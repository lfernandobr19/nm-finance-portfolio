/// Small JSON coercion helpers shared by the typed data layer.
///
/// The backend returns Pydantic-serialized floats (sometimes as int when whole),
/// so every numeric read goes through a tolerant converter.
library;

double asDouble(Object? value, [double fallback = 0.0]) {
  if (value == null) return fallback;
  if (value is num) return value.toDouble();
  if (value is String) {
    final parsed = double.tryParse(value);
    if (parsed != null) return parsed;
  }
  return fallback;
}

double? asDoubleOrNull(Object? value) {
  if (value == null) return null;
  if (value is num) return value.toDouble();
  if (value is String) return double.tryParse(value);
  return null;
}

int asInt(Object? value, [int fallback = 0]) {
  if (value == null) return fallback;
  if (value is int) return value;
  if (value is num) return value.toInt();
  if (value is String) return int.tryParse(value) ?? fallback;
  return fallback;
}

bool asBool(Object? value, [bool fallback = false]) {
  if (value == null) return fallback;
  if (value is bool) return value;
  if (value is num) return value != 0;
  if (value is String) return value.toLowerCase() == 'true';
  return fallback;
}

String asString(Object? value, [String fallback = '']) {
  if (value == null) return fallback;
  return value.toString();
}

String? asStringOrNull(Object? value) {
  if (value == null) return null;
  final s = value.toString();
  return s.isEmpty ? null : s;
}

List<dynamic> asList(Object? value) {
  if (value is List) return value;
  return const [];
}

Map<String, dynamic> asMap(Object? value) {
  if (value is Map) {
    return value.map((k, v) => MapEntry(k.toString(), v));
  }
  return const {};
}

List<T> asListOf<T>(Object? value, T Function(Map<String, dynamic>) fromJson) {
  return asList(value)
      .whereType<Map>()
      .map((e) => fromJson(e.map((k, v) => MapEntry(k.toString(), v))))
      .toList();
}
