import '../../core/pnl_line_chart.dart';
import '../../data/models/position.dart';

/// Uma fatia da alocação consolidada por ativo (valor + % do total do bloco).
class AllocationSlice {
  const AllocationSlice({
    required this.ticker,
    required this.value,
    required this.pct,
  });

  final String ticker;
  final double value;
  final double pct;
}

/// Uma movimentação recente (ordem de corretora) exibida no feed.
class ActivityItem {
  const ActivityItem({
    required this.id,
    required this.ticker,
    required this.side,
    required this.quantity,
    required this.price,
    required this.status,
    required this.currency,
    required this.at,
  });

  final String id;
  final String ticker;
  final String side; // buy | sell
  final double quantity;
  final double price;
  final String status;
  final String currency;
  final DateTime at;
}

/// Consolidação de todas as contas de uma mesma moeda (Brasil = BRL, EUA = USD).
class CurrencyBucket {
  const CurrencyBucket({
    required this.currency,
    required this.label,
    required this.cash,
    required this.invested,
    required this.marketValue,
    required this.equity,
    required this.unrealizedPnl,
    required this.realizedPnl,
    required this.realizedPnlDay,
    required this.openPositions,
    required this.pnlPoints,
    required this.allocation,
    required this.positions,
  });

  final String currency; // 'BRL' | 'USD'
  final String label; // 'Brasil' | 'EUA'
  final double cash;
  final double invested;
  final double marketValue;
  final double equity;
  final double unrealizedPnl;
  final double realizedPnl;
  final double realizedPnlDay;
  final int openPositions;
  final List<PnlPoint> pnlPoints;
  final List<AllocationSlice> allocation;
  final List<Position> positions;

  /// Resultado total do bloco: realizado + não realizado.
  double get totalPnl => realizedPnl + unrealizedPnl;

  bool get isEmpty =>
      cash == 0 &&
      invested == 0 &&
      marketValue == 0 &&
      equity == 0 &&
      openPositions == 0 &&
      positions.isEmpty;
}

/// Agregado imutável do dashboard, separado por moeda.
class DashboardData {
  const DashboardData({
    required this.brl,
    required this.usd,
    required this.activity,
    required this.updatedAt,
  });

  final CurrencyBucket? brl;
  final CurrencyBucket? usd;
  final List<ActivityItem> activity;
  final DateTime? updatedAt;

  bool get hasAny =>
      (brl != null && !brl!.isEmpty) || (usd != null && !usd!.isEmpty);
}
