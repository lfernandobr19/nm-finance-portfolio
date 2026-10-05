/// Horários de pregão B3 (Ibovespa) e Nasdaq/NYSE (regular session).
library;

class MarketSession {
  const MarketSession({
    required this.id,
    required this.name,
    required this.hoursExchange,
    required this.hoursLocalBr,
    required this.isOpen,
    required this.statusLabel,
    this.note,
  });

  final String id;
  final String name;
  final String hoursExchange;
  final String hoursLocalBr;
  final bool isOpen;
  final String statusLabel;
  final String? note;
}

/// Segunda–sexta, pregão regular (sem after-hours).
class MarketHours {
  static const b3OpenHour = 10;
  static const b3OpenMinute = 0;
  static const b3CloseHour = 17;
  static const b3CloseMinute = 0;

  static const usOpenHour = 9;
  static const usOpenMinute = 30;
  static const usCloseHour = 16;
  static const usCloseMinute = 0;

  /// Horário de Brasília (UTC−3, sem DST).
  static DateTime nowBr() {
    final utc = DateTime.now().toUtc();
    return utc.add(const Duration(hours: -3));
  }

  /// US Eastern (EST/EDT) a partir de UTC.
  static DateTime nowUsEastern(DateTime utc) {
    final offsetHours = _usEasternOffsetHours(utc);
    return utc.add(Duration(hours: offsetHours));
  }

  /// Segundo domingo de março (02:00 local) até primeiro domingo de novembro.
  static int _usEasternOffsetHours(DateTime utc) {
    final year = utc.year;
    final dstStart = _nthWeekdayOfMonth(year, 3, DateTime.sunday, 2);
    final dstEnd = _nthWeekdayOfMonth(year, 11, DateTime.sunday, 1);
    final inDst = !utc.isBefore(dstStart) && utc.isBefore(dstEnd);
    return inDst ? -4 : -5;
  }

  static DateTime _nthWeekdayOfMonth(int year, int month, int weekday, int nth) {
    var d = DateTime.utc(year, month, 1);
    var count = 0;
    while (d.month == month) {
      if (d.weekday == weekday) {
        count++;
        if (count == nth) return d;
      }
      d = d.add(const Duration(days: 1));
    }
    return DateTime.utc(year, month, 1);
  }

  static bool _inSession(DateTime local, int openH, int openM, int closeH, int closeM) {
    if (local.weekday > DateTime.friday) return false;
    final open = openH * 60 + openM;
    final close = closeH * 60 + closeM;
    final now = local.hour * 60 + local.minute;
    return now >= open && now < close;
  }

  static String _brTime(int h, int m) {
    return '${h.toString().padLeft(2, '0')}:${m.toString().padLeft(2, '0')} BRT';
  }

  static String _etTime(int h, int m, DateTime utc) {
    final suffix = _usEasternOffsetHours(utc) == -4 ? 'ET (EDT)' : 'ET (EST)';
    return '${h.toString().padLeft(2, '0')}:${m.toString().padLeft(2, '0')} $suffix';
  }

  static String _usSessionInBr(DateTime utc) {
    final offsetBrFromUtc = -3;
    final offsetEtFromUtc = _usEasternOffsetHours(utc);
    final delta = offsetBrFromUtc - offsetEtFromUtc;
    int toBr(int h, int m) {
      final total = h * 60 + m + delta * 60;
      final norm = ((total % (24 * 60)) + (24 * 60)) % (24 * 60);
      return norm;
    }
    final open = toBr(usOpenHour, usOpenMinute);
    final close = toBr(usCloseHour, usCloseMinute);
    String fmt(int mins) {
      final h = mins ~/ 60;
      final m = mins % 60;
      return '${h.toString().padLeft(2, '0')}:${m.toString().padLeft(2, '0')} BRT';
    }
    return '${fmt(open)}–${fmt(close)}';
  }

  static MarketSession b3Session([DateTime? utcNow]) {
    final utc = (utcNow ?? DateTime.now()).toUtc();
    final br = utc.add(const Duration(hours: -3));
    final open = _inSession(br, b3OpenHour, b3OpenMinute, b3CloseHour, b3CloseMinute);
    return MarketSession(
      id: 'b3',
      name: 'Ibovespa (B3)',
      hoursExchange: '${_brTime(b3OpenHour, b3OpenMinute)} – ${_brTime(b3CloseHour, b3CloseMinute)}',
      hoursLocalBr: '10:00–17:00 BRT',
      isOpen: open,
      statusLabel: open ? 'Aberto' : 'Fechado',
    );
  }

  static MarketSession usSession([DateTime? utcNow]) {
    final utc = (utcNow ?? DateTime.now()).toUtc();
    final et = nowUsEastern(utc);
    final open = _inSession(et, usOpenHour, usOpenMinute, usCloseHour, usCloseMinute);
    final brRange = _usSessionInBr(utc);
    return MarketSession(
      id: 'us',
      name: 'Nasdaq / NYSE',
      hoursExchange:
          '${_etTime(usOpenHour, usOpenMinute, utc)} – ${_etTime(usCloseHour, usCloseMinute, utc)}',
      hoursLocalBr: brRange,
      isOpen: open,
      statusLabel: open ? 'Aberto' : 'Fechado',
      note: open ? null : 'Ordens limit enviadas ficam na fila até a próxima sessão',
    );
  }

  static List<MarketSession> all([DateTime? utcNow]) => [b3Session(utcNow), usSession(utcNow)];

  /// Sessão relevante para o mercado ativo no app (`br` | `us`).
  static MarketSession forMarket(String market, [DateTime? utcNow]) {
    return market == 'us' ? usSession(utcNow) : b3Session(utcNow);
  }
}

/// Status legível de ordem na corretora (tastytrade etc.).
String orderWaitingLabel(Map<String, dynamic> order) {
  final status = (order['status'] as String?) ?? '';
  if (status == 'rejected') {
    final err = order['error_message'];
    if (err != null && '$err'.isNotEmpty) return 'Rejeitada';
    return 'Rejeitada';
  }
  final payload = order['execution_payload'];
  if (payload is Map) {
    final tt = payload['tastytrade'];
    if (tt is Map) {
      final data = tt['data'];
      if (data is Map) {
        final ord = data['order'];
        if (ord is Map) {
          final remote = (ord['status'] as String?) ?? '';
          if (remote.isNotEmpty) {
            switch (remote.toLowerCase()) {
              case 'received':
              case 'routed':
              case 'live':
              case 'working':
                return 'Na fila da corretora';
              case 'filled':
                return 'Executada';
              case 'rejected':
                return 'Rejeitada';
              default:
                return remote;
            }
          }
        }
        final warnings = data['warnings'];
        if (warnings is List && warnings.isNotEmpty) {
          final w = warnings.first;
          if (w is Map && (w['code'] as String?) == 'tif.next_valid_session') {
            return 'Aguardando abertura do mercado';
          }
        }
      }
    }
    final mode = payload['mode'] as String?;
    if (mode != null && mode.startsWith('tastytrade')) {
      return 'Enviada à corretora';
    }
  }
  switch (status) {
    case 'submitted':
      return 'Aguardando execução';
    case 'queued':
      return 'Na fila';
    case 'awaiting_broker':
      return 'Aguardando corretora';
    default:
      return status;
  }
}

String? orderWaitingDetail(Map<String, dynamic> order) {
  final payload = order['execution_payload'];
  if (payload is! Map) return null;
  final tt = payload['tastytrade'];
  if (tt is! Map) return null;
  final data = tt['data'];
  if (data is! Map) return null;
  final warnings = data['warnings'];
  if (warnings is List) {
    for (final w in warnings) {
      if (w is Map && w['message'] != null) return w['message'] as String;
    }
  }
  final ord = data['order'];
  if (ord is Map && ord['reject-reason'] != null) {
    return ord['reject-reason'] as String;
  }
  return null;
}
