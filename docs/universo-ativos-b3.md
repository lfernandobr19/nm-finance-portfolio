# Universo de ativos e venue (planejamento)

## Decisão: B3 como venue principal (MVP → fase 2)

Para o NM Finance, **B3 é a escolha recomendada** no início:

| Critério | B3 (FII + BDR) | Corretora exterior (Avenue, IBKR, etc.) |
|----------|----------------|------------------------------------------|
| Conta / câmbio | Uma corretora BR, em R$ | Conta internacional + FX |
| Operação no app | Mesmo fluxo de aprovação | Mais APIs, KYC, fuso |
| FIIs mensais | Nativo | Não aplica |
| Imóveis EUA / global | Via **BDR de REIT** (~40 na B3) | REIT nativo (ticker US) |
| Impostos | FII PF: isenção típica de rendimento; BDR: withholding EUA + regras BR | W-8BEN, declaração exterior |
| Liquidez / horário | Pregão B3 | Pregão US |

**Sugestão:** manter **tudo na B3** enquanto o produto for “sugerir → aprovar”. Abrir venue exterior só se precisar de REIT sem BDR, opções, ou custo/liquidez melhores — e como fase 3+ separada.

## Classes no produto

1. **`fii`** — FII listado B3 (ex.: HGLG11, MXRF11). Foco natural em **dividendo mensal**.
2. **`bdr_reit`** — BDR de REIT internacional (ticker `*34`, ex. ligados a Realty Income / LTC / Agree etc.). Preferir os com **pagamento mensal** no underlying.
3. **`bdr_equity`** (opcional depois) — BDRs de ações/ETFs internacionais pagadores; muitos são **trimestrais**, não mensais.

Campo no modelo: `asset_class`, `venue=B3`, `dividend_frequency` (`monthly` | `quarterly` | `other`), `currency_exposure` (`BRL` | `USD_via_BDR`).

## Regras de score (extensão)

Além de DY / P/VP / volume (FII):

- **Frequência de dividendo** — boost se `monthly` (alinhado ao objetivo de renda)
- **Yield líquido estimado** em BDR (após withholding ~30% EUA, quando aplicável) — não comparar DY bruto de BDR com DY de FII
- **Liquidez do BDR** (volume B3 costuma ser menor que do FII líquido)
- **Setor / geografia** do REIT underlying
- Filtros por conta: `allowed_asset_classes`, `prefer_monthly_dividends=true`

## Dados

- Cotação B3: mesmo provedor / stub, com tickers FII + BDR
- Calendário de proventos: fonte de dividends (Frequência + último pagamento)
- Explicação determinística: “DY bruto X% · freq. mensal · exposição USD via BDR · yield líquido estimado Y%”

## Fases

- **Agora (doc/plan):** universo FII + BDR REIT; B3 only; preferência mensal
- **Próxima implementação:** `asset_class` + regras de frequência + amostra de BDRs no stub de market
- **Depois:** integração corretora B3; venue exterior só se houver demanda clara

## Swing Desk (paralelo)

Lista fixa ~30 tickers (BDRs tech + `IVVB11` + líquidos não-tech) em `backend/app/services/swing/universe.py`. Playbook: [swing-desk-playbook.md](swing-desk-playbook.md).
