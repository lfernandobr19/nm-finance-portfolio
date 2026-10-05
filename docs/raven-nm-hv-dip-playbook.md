# NM Finance — High-Vol Dip playbook (M0/M1)

**Produto:** NM Finance · **NM** · Next Milestone  
**Desk:** EUA (USD) · estratégia `hv_dip`  
**Mercado no app:** alternador **Brasil | EUA** (BR Income/Swing intactos)

## Setup

1. **Universo:** lista curada ~40 tickers US líquidos (high-beta / high weekly range). Rank por **ATR% 20d** + volume. Validar com `python scripts/validate_universe.py`.
2. **Entrada (dip):** close atual ≤ máxima dos últimos **N=10** pregões × (1 − **X=8%**/100), e ainda **acima** do piso do setup (mínima dos últimos N).
3. **Scale-in (pirâmide):** tranches **1× → 1,5× → 2×** do tamanho base; máx. **3** compras no mesmo ticker; teto **Z=80%** do patrimônio alocado naquele ticker (ajustável na Settings).
4. **Saída patient:** alvo inicial = entry + **2R** (R = entry − setup_low); **Exit V2:** observação em **+5%** (LATCHED), proteção em **max(8%, 1R)** com venda auto se preço cai **2%** do pico (PROTECT); hold máx. **14 dias** → notificação para avaliar; rotação manual quando setup melhor.
5. **Hard stop:** `min(setup_low × 0,995, último_reforço × (1 − Y/100))` com **Y=12** — **auto-venda**.
6. **Auto-venda V2:** STOP, 2R (alvo), PROTECT (−2% do pico). **Notifica (sem auto):** LATCHED +5%, dia 14, rotação.
7. **Review (sempre confirmação humana, mesmo com auto):**
   - close em nova mínima **52 semanas** (ou mínima do lookback disponível), **ou**
   - earnings em ±2 pregões com rompimento do piso  
   → gera Suggestion com `review_required=true`; **auto-approve não executa**.
8. **Freios conta (seed ~US$ 100):**
   - máx. **4** tickers `hv_dip` abertos (tranches no mesmo ticker não gastam slot);
   - **piso de caixa 30%** — abaixo disso, novas compras **B/C** bloqueadas;
   - **score A (imperdível)** pode ultrapassar o piso;
   - teto por ticker default **80%** do patrimônio (Settings).

## Score / ranking

| Letter | Critério | Uso |
|--------|----------|-----|
| **A** | Dip ≥ 8% + ATR% alto + volume ≥ 1,0× SMA20 + não Review | Tamanho base cheio; pode comprar abaixo do piso 30% |
| **B** | Dip ok, volume/ATR mais fraco | Tamanho base × 0,75 |
| **C** | Dip fraco ou Review | Só com confirmação; Review sempre |

Top **N** (`HV_DIP_TOP_N`, default 10) por ATR% + profundidade do dip + letter.

## Dados / broker (M0)

- Market data: **Alpaca Basic** ou **fallback Yahoo** (sem keys).
- Execução: **Alpaca paper** quando keys configuradas; senão **`alpaca_paper_sim`** (ledger local).
- Worker: ciclo `hv_dip` ~**1–2×/dia** (`HV_DIP_MIN_INTERVAL_SECONDS`, default 12h) + **exit_watch V2** (auto-close STOP/2R/PROTECT; alertas LATCHED/dia14/rotação).

## App

- **Brasil:** Income | Swing (BRL, Inter).
- **EUA:** High-Vol NM (USD, Alpaca paper) — banner de freios na home; Settings NM.
- Troca de mercado = troca de `InvestmentAccount` ativa.

## Aceite M0/M1

- [x] Paper/Yahoo gera suggestions `hv_dip`
- [x] Approve sim preenche + debita `cash_usd` (`alpaca_paper_sim`)
- [ ] Approve com Alpaca paper real (aguardando keys BR)
- [x] Review exige tap no app (auto não passa)
- [ ] Desk BR regressão no M55 (checklist Android)
- [x] Freios visíveis na home EUA
- [x] Alertas stop/alvo nas posições abertas

Checklist Android: [`docs/m0-android-aceite-checklist.md`](m0-android-aceite-checklist.md)

## Scorecard Exit V2 — metas stretch

Baseline paper **NM USD** (27–28/ago/2026): 6 fechados manuais · WR 83% · **+$7,55** · retorno médio **+8,7%** · equity ~**US$ 100** · **0** stops reais (amostra sortuda).

Horizonte: **40 trades fechados** ou **60 dias** (o que vier primeiro). Metas **acima** do lote inicial — não empatar.

| # | Métrica | Baseline | Meta stretch |
|---|---------|----------|--------------|
| 1 | Equity da conta | ~US$ 100 | **US$ 130** (+30%) |
| 2 | Retorno médio / trade fechado | +8,7% | **≥ +11%** |
| 3 | P&L realizado acumulado no período | +7,55 | **≥ +25** |
| 4 | % trades que chegam LATCHED (+5%) | n/d | **≥ 55%** |
| 5 | % saídas em 2R ou PROTECT | 0% (manual) | **≥ 40%** |
| 6 | Expectancy (R médio) | n/d | **≥ +0,45R** |
| 7 | Max drawdown equity | ~0% | **≤ 12%** |
| 8 | Win rate sustentável (com stops) | 83% inflado | **≥ 58%** |

**Check a cada 10 fechados:** (1) equity na trilha até 130 · (2) média % ≥ 11 · (3) ≥4/10 saíram 2R/PROTECT · (4) DD ≤ 12%. **≥3/4 verde** = sistema superando o primeiro lote.

**Meta diária (relatório):** **+7%** do equity de referência por dia civil. No app: barra meta × atingido no diário; no gráfico Sem/Mês/Ano, curva tracejada de meta acumulada (7% × dias).

## Ferramentas

- `python scripts/validate_universe.py` — tickers com OHLC ok
- `python scripts/hv_dip_backtest.py` — calibração offline (CSV)
- `python scripts/m0_aceite_smoke.py` — smoke backend Ravenna
- `bash scripts/alpaca_setup.sh` — plug keys quando Alpaca liberar

## Fora do M0

Live Alpaca, full-auto fora de Review, Polygon/SIP, IBKR, day trade, FIIs M2, tastytrade, rename package.
