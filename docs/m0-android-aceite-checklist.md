# Aceite Android — NM Finance (M55)

Validar após instalar APK ≥ 0.1.10 (build +11).

**Deploy 2026-08-27:** Ravenna API :8010 + worker reiniciados; APK `FII-Desk-0.1.10.apk` instalado no M55 via agente (Success).

| # | Item | Onde | OK? |
|---|------|------|-----|
| 1 | Login + API Ravenna | Login | |
| 2 | Mercado **EUA** → High-Vol NM | Home | |
| 3 | Banner freios (`NM · x/4 tickers · caixa %`) | Home conta USD | |
| 4 | Settings: 4 pos, 80% ticker, 30% piso | Regras e automação | |
| 5 | Sugestões hv_dip pendentes | Lista | |
| 6 | Badge **REVIEW** quando aplicável | Card sugestão | |
| 7 | Approve → saldo USD desce | Detalhe + banner | |
| 8 | Posição aberta com chip STOP/ALVO se preço cruzou | Abertas | |
| 9 | Mercado **Brasil** → Income/Swing ok | Alternar mercado | |
| 10 | Notificação local nova sugestão NM | Background/poll | |

Backend smoke: `PYTHONPATH=. python scripts/m0_aceite_smoke.py` no Ravenna.
