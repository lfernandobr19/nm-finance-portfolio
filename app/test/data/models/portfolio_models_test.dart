import 'package:flutter_test/flutter_test.dart';

import 'package:fiidesk/data/models/account.dart';
import 'package:fiidesk/data/models/order.dart';
import 'package:fiidesk/data/models/news.dart';
import 'package:fiidesk/data/models/position.dart';
import 'package:fiidesk/data/models/suggestion.dart';

void main() {
  group('Position.fromJson', () {
    test('parses open position with mark-to-market fields', () {
      final p = Position.fromJson({
        'id': 'p1',
        'account_id': 'a1',
        'order_id': 'o1',
        'suggestion_id': 's1',
        'ticker': 'PETR4',
        'strategy_kind': 'swing',
        'quantity': 100,
        'entry_price': 32.5,
        'stop_price': 31.0,
        'target_price': 35.0,
        'setup_low': 32.0,
        'tranche_index': 1,
        'status': 'open',
        'opened_at': '2026-08-20T10:00:00Z',
        'mark_price': 33.0,
        'cost_brl': 3250.0,
        'market_value_brl': 3300.0,
        'unrealized_pnl_brl': 50.0,
        'unrealized_pnl_pct': 1.5,
        'latched_5': true,
        'protect_active': false,
      });
      expect(p.ticker, 'PETR4');
      expect(p.strategyKind, 'swing');
      expect(p.quantity, closeTo(100, 1e-9));
      expect(p.status, 'open');
      expect(p.latched5, isTrue);
      expect(p.unrealizedPnlBrl, closeTo(50, 1e-9));
    });

    test('tolerates null latched/protect and dates', () {
      final p = Position.fromJson({
        'id': 'p2',
        'account_id': 'a1',
        'ticker': 'X',
        'strategy_kind': 'income',
        'quantity': 1,
        'entry_price': 10,
        'status': 'closed',
        'opened_at': '2026-08-01T00:00:00Z',
        'latched_5': null,
        'protect_active': null,
        'days_until_review': null,
      });
      expect(p.latched5, isNull);
      expect(p.protectActive, isNull);
      expect(p.daysUntilReview, isNull);
    });
  });

  group('Portfolio.fromJson', () {
    test('parses snapshot with cash and equity', () {
      final pf = Portfolio.fromJson({
        'cash_brl': 5000.0,
        'invested_open_brl': 10000.0,
        'market_value_open_brl': 10200.0,
        'unrealized_pnl_brl': 200.0,
        'equity_brl': 15200.0,
        'equity_cost_brl': 15000.0,
        'open_positions': 4,
        'open_swing': 2,
        'open_income': 1,
        'open_hv_dip': 1,
        'realized_pnl_day_brl': 150.0,
        'currency': 'BRL',
      });
      expect(pf.cashBrl, closeTo(5000, 1e-9));
      expect(pf.equityBrl, closeTo(15200, 1e-9));
      expect(pf.openPositions, 4);
      expect(pf.openHvDip, 1);
    });
  });

  group('Suggestion.fromJson', () {
    test('parses swing suggestion with letter + metrics', () {
      final s = Suggestion.fromJson({
        'id': 's1',
        'account_id': 'a1',
        'ticker': 'AAPL',
        'strategy_kind': 'swing',
        'asset_class': 'stock',
        'score': 8.5,
        'swing_score_letter': 'A',
        'entry_price': 190.0,
        'stop_price': 188.0,
        'target_price': 194.0,
        'r_multiple': 2.0,
        'status': 'open',
        'reasons': [
          {'rule': 'vol', 'passed': true}
        ],
        'metrics': {'vol': 1.2},
        'price_explanation': 'setup limpo',
        'rule_version': 2,
        'proposed_amount_brl': 1000.0,
        'setup_low': 189.0,
        'review_required': true,
        'review_reason': 'perto do topo',
        'expires_at': '2026-08-31T00:00:00Z',
        'created_at': '2026-08-30T00:00:00Z',
      });
      expect(s.strategyKind, 'swing');
      expect(s.swingScoreLetter, 'A');
      expect(s.reviewRequired, isTrue);
      expect(s.reasons, hasLength(1));
      expect(s.metrics['vol'], 1.2);
    });
  });

  group('Order.fromJson', () {
    test('parses broker order with fill', () {
      final o = Order.fromJson({
        'id': 'o1',
        'account_id': 'a1',
        'suggestion_id': 's1',
        'ticker': 'AAPL',
        'strategy_kind': 'swing',
        'side': 'buy',
        'quantity': 5,
        'amount_brl': 950.0,
        'limit_price': 190.0,
        'status': 'filled',
        'broker': 'inter',
        'execution_mode': 'paper',
        'filled_price': 189.5,
        'filled_at': '2026-08-30T10:00:00Z',
        'execution_payload': {'x': 1},
        'created_at': '2026-08-30T10:00:00Z',
      });
      expect(o.side, 'buy');
      expect(o.status, 'filled');
      expect(o.filledPrice, closeTo(189.5, 1e-9));
      expect(o.executionPayload['x'], 1);
    });
  });

  group('Account.fromJson', () {
    test('parses account with role object', () {
      final a = Account.fromJson({
        'id': 'a1',
        'name': 'Mesa',
        'owner_user_id': 'u1',
        'target_capital': 10000.0,
        'currency': 'BRL',
        'execution_mode': 'paper',
        'my_role': {'value': 'owner'},
      });
      expect(a.name, 'Mesa');
      expect(a.myRole, 'owner');
    });

    test('parses account with role string fallback', () {
      final a = Account.fromJson({
        'id': 'a2',
        'name': 'M2',
        'owner_user_id': 'u1',
        'target_capital': 1000.0,
        'my_role': 'operator',
      });
      expect(a.myRole, 'operator');
    });
  });

  group('NewsItem.fromJson', () {
    test('parses simple news item', () {
      final n = NewsItem.fromJson({
        'id': 'n1',
        'ticker': 'AAPL',
        'title': 'Apple sobe',
        'url': 'https://example.com',
        'source': 'finnhub',
        'published_at': '2026-08-30T10:00:00Z',
      });
      expect(n.ticker, 'AAPL');
      expect(n.title, 'Apple sobe');
      expect(n.publishedAt, isNotNull);
    });
  });
}
