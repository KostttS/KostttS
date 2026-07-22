import 'dart:math';

/// Sanitized example of a FlutterFlow-style custom action.
///
/// Adds a rounded distance value to JSON-like records and sorts them from
/// nearest to farthest. Records without valid coordinates are kept at the end.
Future<List<dynamic>> addDistanceAndSort({
  required List<dynamic> items,
  required double originLatitude,
  required double originLongitude,
  String latitudeKey = 'latitude',
  String longitudeKey = 'longitude',
  String distanceKey = 'distanceKm',
}) async {
  final enriched = <Map<String, dynamic>>[];

  for (final item in items) {
    if (item is! Map) {
      continue;
    }

    final record = Map<String, dynamic>.from(item);
    final latitude = _asDouble(record[latitudeKey]);
    final longitude = _asDouble(record[longitudeKey]);

    if (latitude == null || longitude == null) {
      record[distanceKey] = null;
    } else {
      final distance = _haversineKm(
        originLatitude,
        originLongitude,
        latitude,
        longitude,
      );
      record[distanceKey] = double.parse(distance.toStringAsFixed(1));
    }

    enriched.add(record);
  }

  enriched.sort((a, b) {
    final first = _asDouble(a[distanceKey]);
    final second = _asDouble(b[distanceKey]);

    if (first == null && second == null) return 0;
    if (first == null) return 1;
    if (second == null) return -1;
    return first.compareTo(second);
  });

  return enriched;
}

double? _asDouble(dynamic value) {
  if (value is num) return value.toDouble();
  if (value is String) return double.tryParse(value);
  return null;
}

double _haversineKm(
  double firstLatitude,
  double firstLongitude,
  double secondLatitude,
  double secondLongitude,
) {
  const earthRadiusKm = 6371.0;

  final latitudeDelta = _toRadians(secondLatitude - firstLatitude);
  final longitudeDelta = _toRadians(secondLongitude - firstLongitude);

  final a = pow(sin(latitudeDelta / 2), 2) +
      cos(_toRadians(firstLatitude)) *
          cos(_toRadians(secondLatitude)) *
          pow(sin(longitudeDelta / 2), 2);

  return earthRadiusKm * 2 * atan2(sqrt(a), sqrt(1 - a));
}

double _toRadians(double degrees) => degrees * pi / 180;
