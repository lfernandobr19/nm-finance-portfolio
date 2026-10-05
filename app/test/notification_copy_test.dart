import 'package:flutter_test/flutter_test.dart';

import 'package:fiidesk/core/notification_copy.dart';
import 'package:fiidesk/core/suggestion_poller.dart';

void main() {
  test('income copy shows yields and valor in BRL', () {
    final copy = buildSuggestionNotificationCopy(
      NewSuggestionEvent(
        id: '1',
        accountId: 'a',
        ticker: 'MXRF11',
        strategyKind: 'income',
        isUsd: false,
        proposedAmount: 2500,
        assetName: 'Maxi Renda',
        grossYield: 12.5,
        effectiveYield: 12.5,
      ),
    );
    expect(copy.title, 'NM Finance · Renda · MXRF11');
    expect(copy.bigBody, contains('Nome da ação: MXRF11 (Maxi Renda)'));
    expect(copy.bigBody, contains('Yield efetivo:'));
    expect(copy.bigBody, contains('Valor: R\$'));
    expect(copy.bigBody, isNot(contains('Yield bruto:')));
    expect(copy.summary, contains('Yield'));
  });

  test('income copy shows gross yield when different from effective', () {
    final copy = buildSuggestionNotificationCopy(
      NewSuggestionEvent(
        id: '2',
        accountId: 'a',
        ticker: 'R1IN34',
        strategyKind: 'income',
        isUsd: false,
        grossYield: 12.0,
        effectiveYield: 8.4,
        proposedAmount: 1000,
      ),
    );
    expect(copy.bigBody, contains('Yield bruto:'));
    expect(copy.bigBody, contains('Yield efetivo:'));
  });

  test('swing copy shows entrada stop alvo valor', () {
    final copy = buildSuggestionNotificationCopy(
      NewSuggestionEvent(
        id: '3',
        accountId: 'a',
        ticker: 'VALE3',
        strategyKind: 'swing',
        letter: 'B',
        isUsd: false,
        entry: 62.4,
        stop: 59.8,
        target: 68.0,
        proposedAmount: 1200,
      ),
    );
    expect(copy.title, 'NM Finance · Swing · B');
    expect(copy.bigBody, contains('Entrada:'));
    expect(copy.bigBody, contains('Stop:'));
    expect(copy.bigBody, contains('Alvo:'));
    expect(copy.bigBody, contains('Valor:'));
  });

  test('hv_dip copy uses USD and NM title', () {
    final copy = buildSuggestionNotificationCopy(
      NewSuggestionEvent(
        id: '4',
        accountId: 'a',
        ticker: 'TSLA',
        strategyKind: 'hv_dip',
        letter: 'A',
        isUsd: true,
        entry: 245.0,
        stop: 220.0,
        target: 290.0,
        proposedAmount: 25,
      ),
    );
    expect(copy.title, 'NM Finance · A');
    expect(copy.bigBody, contains('Valor: US\$'));
    expect(copy.summary, contains('Entrada'));
  });

  test('hv_dip catalyst copy shows "Compra sugerida" + factors', () {
    final copy = buildSuggestionNotificationCopy(
      NewSuggestionEvent(
        id: '5',
        accountId: 'a',
        ticker: 'NVDA',
        strategyKind: 'hv_dip',
        letter: 'A',
        isUsd: true,
        entry: 120.0,
        stop: 108.0,
        target: 140.0,
        catalyst: const CatalystInfo(
          eventType: 'partnership',
          sentiment: 'bullish',
          confidence: 0.88,
          impactScore: 70,
          title: 'Acordo Amazon/NVIDIA',
        ),
      ),
    );
    expect(copy.title, 'NM Finance · Compra sugerida · NVDA · A');
    expect(copy.bigBody, contains('parceria'));
    expect(copy.bigBody, contains('conf 88%'));
    expect(copy.bigBody, contains('imp 70'));
    expect(copy.summary, contains('parceria'));
  });

  test('hv_dip auto-buy copy shows "Compra automática"', () {
    final copy = buildSuggestionNotificationCopy(
      NewSuggestionEvent(
        id: '6',
        accountId: 'a',
        ticker: 'AMD',
        strategyKind: 'hv_dip',
        letter: 'A',
        isUsd: true,
        status: 'auto_approved',
        catalyst: const CatalystInfo(
          eventType: 'guidance_up',
          sentiment: 'bullish',
          confidence: 0.9,
        ),
      ),
    );
    expect(copy.title, 'NM Finance · Compra automática · AMD · A');
    expect(copy.bigBody, contains('guidance positiva'));
    expect(copy.summary, contains('guidance positiva'));
  });

  test('hv_dip without prices falls back to dip vivo instead of "confirme no app"', () {
    final copy = buildSuggestionNotificationCopy(
      NewSuggestionEvent(
        id: '7',
        accountId: 'a',
        ticker: 'PLTR',
        strategyKind: 'hv_dip',
        letter: 'B',
        isUsd: true,
        dipLive: -4.75,
      ),
    );
    expect(copy.title, 'NM Finance · B');
    expect(copy.summary, contains('Dip vivo'));
    expect(copy.summary, isNot(contains('confirme no app')));
    expect(copy.bigBody, contains('Dip vivo:'));
  });

  test('hv_dip with neither prices nor dip falls back to "confirme no app"', () {
    final copy = buildSuggestionNotificationCopy(
      NewSuggestionEvent(
        id: '8',
        accountId: 'a',
        ticker: 'XYZ',
        strategyKind: 'hv_dip',
        letter: 'C',
        isUsd: true,
      ),
    );
    expect(copy.summary, contains('confirme no app'));
  });
}
