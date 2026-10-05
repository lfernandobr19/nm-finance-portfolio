import 'dart:convert';
import 'dart:ffi';
import 'dart:io';
import 'dart:typed_data';

import 'package:ffi/ffi.dart';
import 'package:flutter_secure_storage_platform_interface/flutter_secure_storage_platform_interface.dart';
import 'package:path/path.dart' as path;
import 'package:path_provider/path_provider.dart';
import 'package:win32/win32.dart';

/// Dart-only DPAPI-backed implementation of `flutter_secure_storage` for
/// Windows. Uses `CryptProtectData`/`CryptUnprotectData` via the `win32`
/// package (pure Dart FFI), so no ATL/MFC C++ toolchain is required.
class FlutterSecureStorageWindows extends FlutterSecureStoragePlatform {
  FlutterSecureStorageWindows() : _storage = _DpapiJsonFileStorage();

  final _DpapiJsonFileStorage _storage;

  Future<void> _lock = Future.value();

  /// Serialises read-modify-write operations so concurrent callers cannot
  /// corrupt the encrypted JSON file.
  Future<T> _serialized<T>(Future<T> Function() action) {
    final run = _lock.then((_) => action());
    _lock = run.then<void>((_) {}, onError: (_) {});
    return run;
  }

  static void registerWith() {
    FlutterSecureStoragePlatform.instance = FlutterSecureStorageWindows();
  }

  @override
  Future<bool> containsKey({
    required String key,
    required Map<String, String> options,
  }) =>
      _serialized(() async => (await _storage.load()).containsKey(key));

  @override
  Future<void> delete({
    required String key,
    required Map<String, String> options,
  }) =>
      _serialized(() async {
        final map = await _storage.load();
        if (map.remove(key) != null) {
          await _storage.save(map);
        }
      });

  @override
  Future<void> deleteAll({required Map<String, String> options}) =>
      _serialized(() => _storage.clear());

  @override
  Future<String?> read({
    required String key,
    required Map<String, String> options,
  }) =>
      _serialized(() async => (await _storage.load())[key]);

  @override
  Future<Map<String, String>> readAll({required Map<String, String> options}) =>
      _serialized(() => _storage.load());

  @override
  Future<void> write({
    required String key,
    required String value,
    required Map<String, String> options,
  }) =>
      _serialized(() async {
        final map = await _storage.load();
        map[key] = value;
        await _storage.save(map);
      });
}

const String _encryptedJsonFileName = 'flutter_secure_storage.dat';

class _DpapiJsonFileStorage {
  Future<String> _jsonFilePath() async {
    final appData = await getApplicationSupportDirectory();
    return path.canonicalize(path.join(appData.path, _encryptedJsonFileName));
  }

  Future<Map<String, String>> load() async {
    final file = File(await _jsonFilePath());
    if (!file.existsSync()) {
      return {};
    }

    final Uint8List encryptedText;
    try {
      encryptedText = await file.readAsBytes();
    } on FileSystemException {
      return {};
    }

    final String plainText;
    try {
      plainText = _unprotect(encryptedText);
    } on Exception {
      await file.delete();
      rethrow;
    }

    final dynamic decoded;
    try {
      decoded = jsonDecode(plainText);
    } on FormatException {
      await file.delete();
      rethrow;
    }

    if (decoded is! Map) {
      await file.delete();
      throw const FormatException('JSON is not an object.');
    }

    return {
      for (final entry in decoded.entries)
        if (entry.key is String && entry.value is String)
          entry.key as String: entry.value as String,
    };
  }

  Future<void> save(Map<String, String> data) async {
    final file = File(await _jsonFilePath());
    final plainText = utf8.encode(jsonEncode(data));
    final encryptedText = _protect(plainText);

    while (true) {
      try {
        await (await file.create(recursive: true))
            .writeAsBytes(encryptedText, flush: true);
        break;
      } on FileSystemException {
        // Retry: another process removed the file or parent directory.
      }
    }
  }

  Future<void> clear() async {
    final file = File(await _jsonFilePath());
    if (file.existsSync()) {
      try {
        await file.delete();
      } on FileSystemException {
        // Ignore.
      }
    }
  }
}

Uint8List _protect(List<int> plainText) => using((alloc) {
      final pPlainText = alloc<Uint8>(plainText.length);
      pPlainText.asTypedList(plainText.length).setAll(0, plainText);

      final plainTextBlob =
          alloc.allocate<CRYPT_INTEGER_BLOB>(sizeOf<CRYPT_INTEGER_BLOB>());
      plainTextBlob.ref.cbData = plainText.length;
      plainTextBlob.ref.pbData = pPlainText;

      final encryptedTextBlob =
          alloc.allocate<CRYPT_INTEGER_BLOB>(sizeOf<CRYPT_INTEGER_BLOB>());
      final result = CryptProtectData(
        plainTextBlob,
        null,
        null,
        null,
        0,
        encryptedTextBlob,
      );
      if (!result.value) {
        throw WindowsException(
          result.error.toHRESULT(),
          message: 'Failure on CryptProtectData()',
        );
      }

      try {
        return Uint8List.fromList(
          encryptedTextBlob.ref.pbData.asTypedList(encryptedTextBlob.ref.cbData),
        );
      } finally {
        if (encryptedTextBlob.ref.pbData.address != NULL) {
          LocalFree(HLOCAL(encryptedTextBlob.ref.pbData.cast()));
        }
      }
    });

String _unprotect(List<int> encryptedText) => using((alloc) {
      final pEncryptedText = alloc<Uint8>(encryptedText.length);
      pEncryptedText
          .asTypedList(encryptedText.length)
          .setAll(0, encryptedText);

      final encryptedTextBlob =
          alloc.allocate<CRYPT_INTEGER_BLOB>(sizeOf<CRYPT_INTEGER_BLOB>());
      encryptedTextBlob.ref.cbData = encryptedText.length;
      encryptedTextBlob.ref.pbData = pEncryptedText;

      final plainTextBlob =
          alloc.allocate<CRYPT_INTEGER_BLOB>(sizeOf<CRYPT_INTEGER_BLOB>());
      final result = CryptUnprotectData(
        encryptedTextBlob,
        null,
        null,
        null,
        0,
        plainTextBlob,
      );
      if (!result.value) {
        throw WindowsException(
          result.error.toHRESULT(),
          message: 'Failure on CryptUnprotectData()',
        );
      }

      try {
        return utf8.decode(
          plainTextBlob.ref.pbData.asTypedList(plainTextBlob.ref.cbData),
        );
      } finally {
        if (plainTextBlob.ref.pbData.address != NULL) {
          LocalFree(HLOCAL(plainTextBlob.ref.pbData.cast()));
        }
      }
    });
