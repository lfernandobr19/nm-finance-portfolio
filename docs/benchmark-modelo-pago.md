# Benchmark do modelo pago — 12 de outubro de 2026

Checkpoint, não compromisso. O modelo pago (Gemini 2.5 Flash-Lite) fica
**fora** da stack até esta data. Rodar antes de as Fases 1–2 estarem
entregues e o corpus ter 2.000 eventos rotulados em 14d produz um número
que parece uma resposta.

## Condições de go/no-go

- Fases 1 e 2 no ar (multi-horizonte, banda por ATR, backlog drenado, FDR).
- ≥ 2.000 eventos rotulados no horizonte de 14 dias.
- Baseline de Brier do `qwen2.5:7b` local estável sob a régua corrigida.

A Fase 3 **não** é pré-requisito. Este experimento responde só
"o modelo pago classifica notícia melhor?", medido em eventos, não em P&L.

## O que o benchmark não responde

Se classificar melhor vira P&L melhor. O catalisador de notícia é raro
(~1 sugestão/dia) e cada trade leva até 14 dias para fechar. Atribuição
em dinheiro fica para uma revisão posterior.

## Protocolo

Comparação pareada: os dois modelos classificam os **mesmos** eventos.

1. Amostra estratificada por `event_type` de ~1.000 eventos já rotulados.
2. Classificar em shadow com Gemini 2.5 Flash-Lite
   (`$0.10` / `$0.40` por 1M tokens). Integração é config:
   `LLM_API_BASE`, `LLM_MODEL`, `LLM_API_KEY` no `llm_client.py`
   OpenAI-compatível. Não promover o default.
3. Comparar Brier e hit-rate em 14d, com IC por bootstrap da diferença pareada.
4. Promover só se a melhora for significativa **e** a whitelist derivada
   do modelo pago sobreviver ao FDR.

Custo estimado: ~US$ 0,12.

Escopo que permanece local independentemente do resultado: redação de
insight e embeddings (`nomic-embed-text`).
