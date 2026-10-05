import 'package:flutter_test/flutter_test.dart';

import 'package:fiidesk/data/models/hv_dip.dart';
import 'package:fiidesk/data/models/day_trade.dart';
import 'package:fiidesk/data/models/news_event.dart';
import 'package:fiidesk/data/models/pnl_series.dart';

void main() {
  group('Observation.fromJson', () {
    test('parses full payload with rounded floats and dates', () {
      final o = Observation.fromJson({
        'ticker': 'INTC',
        'status': 'observing',
        'recovery_probability': 0.6123,
        'recovery_in_progress': true,
        'active_catalyst': false,
        'last_decision': 'observing',
        'note': 'queda estrutural',
        'first_seen_at': '2026-08-01T12:00:00Z',
        'last_evaluated_at': '2026-08-30T15:00:00Z',
        'updated_at': '2026-08-30T15:00:00Z',
      });
      expect(o.ticker, 'INTC');
      expect(o.status, 'observing');
      expect(o.recoveryProbability, closeTo(0.6123, 1e-9));
      expect(o.recoveryInProgress, isTrue);
      expect(o.activeCatalyst, isFalse);
      expect(o.note, 'queda estrutural');
      expect(o.lastEvaluatedAt, isNotNull);
    });

    test('tolerates nulls and missing numeric fields', () {
      final o = Observation.fromJson({'ticker': 'X', 'status': 'active'});
      expect(o.recoveryProbability, isNull);
      expect(o.recoveryInProgress, isFalse);
      expect(o.activeCatalyst, isFalse);
      expect(o.lastDecision, isNull);
    });

    test('coerces string numbers to double', () {
      final o = Observation.fromJson({
        'ticker': 'X',
        'status': 'observing',
        'recovery_probability': '0.5',
      });
      expect(o.recoveryProbability, closeTo(0.5, 1e-9));
    });
  });

  group('HvDipConfig / HvDipConfigHistory', () {
    test('HvDipConfig parses params and validation maps', () {
      final c = HvDipConfig.fromJson({
        'version': 3,
        'is_active': true,
        'params': {'lookback_days': 90},
        'origin': 'walk_forward',
        'validation': {'dsr': 1.2},
        'activated_at': '2026-08-30T00:00:00Z',
      });
      expect(c.version, 3);
      expect(c.isActive, isTrue);
      expect(c.params['lookback_days'], 90);
      expect(c.origin, 'walk_forward');
      expect(c.validation['dsr'], 1.2);
    });

    test('HvDipConfigHistory parses reason', () {
      final h = HvDipConfigHistory.fromJson({
        'version': 2,
        'params': {},
        'origin': 'auto',
        'reason': 'dsr acima do threshold',
        'validation': {},
        'created_at': '2026-08-29T00:00:00Z',
      });
      expect(h.version, 2);
      expect(h.reason, 'dsr acima do threshold');
    });
  });

  group('NewsEvent.fromJson', () {
    test('parses LLM catalyst fields', () {
      final n = NewsEvent.fromJson({
        'id': 'n1',
        'title': 'Intel anuncia turnaround',
        'url': 'https://example.com',
        'ticker': 'INTC',
        'source': 'finnhub',
        'event_type': 'earnings',
        'sentiment': 'positive',
        'confidence': 0.88,
        'impact_score': 0.7,
        'catalyst_strength': 'strong',
        'published_at': '2026-08-30T10:00:00Z',
        'used_in_suggestion': true,
      });
      expect(n.ticker, 'INTC');
      expect(n.eventType, 'earnings');
      expect(n.sentiment, 'positive');
      expect(n.confidence, closeTo(0.88, 1e-9));
      expect(n.catalystStrength, 'strong');
      expect(n.usedInSuggestion, isTrue);
    });

    test('handles null ticker and missing optionals', () {
      final n = NewsEvent.fromJson({
        'id': 'n2',
        'title': 't',
        'url': 'u',
      });
      expect(n.ticker, isNull);
      expect(n.eventType, isNull);
      expect(n.confidence, isNull);
      expect(n.usedInSuggestion, isFalse);
    });
  });

  group('DayTrade models', () {
    test('DayTradeGroupStat parses Wilson win-rate + expectancy', () {
      final s = DayTradeGroupStat.fromJson({
        'key': 'breakout',
        'n': 40,
        'wins': 25,
        'losses': 15,
        'win_rate': 0.625,
        'win_rate_lo': 0.47,
        'win_rate_hi': 0.77,
        'expectancy_r': 0.45,
        'profit_factor': 1.8,
        'avg_hold_minutes': 22.5,
        'total_pnl': 120.5,
        'total_r': 9.2,
      });
      expect(s.key, 'breakout');
      expect(s.n, 40);
      expect(s.wins, 25);
      expect(s.winRate, closeTo(0.625, 1e-9));
      expect(s.expectancyR, closeTo(0.45, 1e-9));
    });

    test('DayTradeAnalytics groups three dimensions', () {
      final a = DayTradeAnalytics.fromJson({
        'total_closed': 100,
        'by_rule': [
          {'key': 'r1', 'n': 50},
        ],
        'by_ticker': [
          {'key': 'AAPL', 'n': 30},
        ],
        'by_side': [
          {'key': 'long', 'n': 80},
        ],
      });
      expect(a.totalClosed, 100);
      expect(a.byRule, hasLength(1));
      expect(a.byTicker.single.key, 'AAPL');
      expect(a.bySide.single.key, 'long');
    });

    test('DayTradeSignal parses session date and prices', () {
      final s = DayTradeSignal.fromJson({
        'id': 's1',
        'account_id': 'a1',
        'session_date': '2026-08-30',
        'ticker': 'AAPL',
        'rule_id': 'r1',
        'side': 'long',
        'entry_price': 190.5,
        'stop_price': 189.0,
        'target_price': 193.0,
        'status': 'open',
        'simulated_pnl_usd': 12.3,
        'metrics': {'r': 1.5},
        'created_at': '2026-08-30T15:00:00Z',
      });
      expect(s.ticker, 'AAPL');
      expect(s.side, 'long');
      expect(s.entryPrice, closeTo(190.5, 1e-9));
      expect(s.simulatedPnlUsd, closeTo(12.3, 1e-9));
    });

    test('IntradayBar parses OHLCV', () {
      final b = IntradayBar.fromJson({
        'ts': '2026-08-30T14:00:00Z',
        'open': 190.0,
        'high': 191.5,
        'low': 189.5,
        'close': 191.0,
        'volume': 1000,
      });
      expect(b.high, closeTo(191.5, 1e-9));
      expect(b.volume, closeTo(1000, 1e-9));
      expect(b.ts, isNotNull);
    });

    test('DayTradeState parses tripped tickers + regimes', () {
      final st = DayTradeState.fromJson({
        'circuit_breaker_tripped': ['NVDA'],
        'regimes': [
          {'ticker': 'AAPL', 'regime': 'trend', 'slope': 0.02},
          {'ticker': 'TSLA', 'regime': 'chop', 'slope': -0.01},
        ],
      });
      expect(st.circuitBreakerTripped, ['NVDA']);
      expect(st.regimes, hasLength(2));
      expect(st.regimes.first.regime, 'trend');
    });
  });

  group('PnlSeries models', () {
    test('PnlSeries parses points and goals', () {
      final p = PnlSeries.fromJson({
        'period': 'month',
        'currency': 'BRL',
        'from': '2026-08-01',
        'daily_target_pct': 7.0,
        'equity_ref': 10000,
        'points': [
          {
            'date': '2026-08-01',
            'cumulative_pnl': 100,
            'day_pnl': 100,
            'target_cumulative_pnl': 110,
            'day_target_pnl': 110,
            'day_pnl_pct': 1.0,
            'day_target_pct': 7.0,
          },
        ],
      });
      expect(p.period, 'month');
      expect(p.points, hasLength(1));
      expect(p.points.first.cumulativePnl, closeTo(100, 1e-9));
      expect(p.dailyTargetPct, closeTo(7.0, 1e-9));
      expect(p.equityRef, closeTo(10000, 1e-9));
    });
  });
}
