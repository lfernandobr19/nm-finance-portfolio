# Swing Desk playbook (MVP)

## Setup

1. Tendência **semanal** a favor: close semanal > **SMA10** (derivada das barras diárias brapi). Free ~3 meses de histórico → SMA20 semanal fica para plano pago / sprint futura.
2. Entrada: **rompimento diário** na direção do semanal (close > máxima dos últimos 20 pregões).
3. Stop técnico: mínimo entre (nível de rompimento × 0,995) e (entrada − 1,5×ATR14).
4. Alvo inicial: entrada + 2R (score pode classificar como B/C se volume fraco).

## Score (Opção 1)

| Letter | Critério | Risco conta |
|--------|----------|-------------|
| **A** | W+D + volume ≥1,2× SMA20 + R:R ≥ 2 | 1–1,5% (`swing_risk_pct_a`) |
| **B** | Setup ok com volume/R:R mais fraco (~1,5) | 0,5–1% (`swing_risk_pct_b`) |
| **C** | Breakout fraco | **só paper** |

Top **10** por ATR% + volume + bônus de letter → `Suggestion` `strategy_kind=swing`.

## Freios

- Máx. **5** posições swing filled abertas.
- Piso de caixa **20%** do `swing_equity_brl`.
- Sem teto semanal além do máximo de posições.
- Paper default; live Inter reutiliza adapters fase 3.

## Cota brapi free

- Universo fixo ~30 tickers, **1 req/ticker** por refresh (cache OHLC ~5h).
- Worker: ciclo swing no mínimo a cada **6h** (~**4×/dia** úteis) → ~2,6k req/mês vs 15k free.
- Token: `BRAPI_TOKEN` no `.env` (nunca no git/chat).

## App

Toggle **Income | Swing** na home da conta. Settings: equity, max posições, piso %, risco A/B.

## Fora deste MVP

Avenue/US; rotação automática mensal do universo; plano brapi pago.

## Confirmação 1h (mesmo cron 4×/dia)

Após D+W passar, o scan busca barras **1h** só para os candidatos (cache `{ticker}.1h.json`, TTL ~90 min). A última hora **fechada** precisa fechar ≥ rompimento diário e ter mínima ≥ stop. Sem cotação 1h → **fail-open** (`h1_skip`). Reprova → não entra no Top N (`h1_fail`). Sem cron extra.
