# Medição real da migração de frontend (pedido Otávio 21/07/2026)

Registro por lote: tempo de execução efetiva, ciclos de correção, onde o
tempo foi, e interrupções operacionais (separadas do custo da migração).
Base para reextrapolar os lotes 2–6 com dado real.

## Lote 0 — Fundação

- **Início:** 21/07 09:00 · **fim da execução:** 21/07 09:11 · **execução efetiva: ~11 min**
  (mais ~4 min de verificação/registro na sequência).
- **Entregue:** scaffold Vite+TS+Tailwind4+React Router; biblioteca inteira portada
  (6 charts + blocks + kpi/caveat/states + 10 componentes ui) com as 3 correções
  aprovadas (2× hachura theme-aware, Fragment key, caveats Set→array); 2 primitivos
  novos (BarListHGrouped, MetaBar); shell (sidebar/tema/guard 401); cliente de API;
  vitrine /app exercitando tudo; app/spa.py servindo estático com chaveamento por
  rota (SPA_ROUTES); estágio bun no Dockerfile do deploy.
- **Ciclos de correção: 0** — typecheck e build passaram de primeira (9,1s de build);
  console do navegador sem erros; guard e rotas antigas verificados via HTTP.
- **Onde foi o tempo:** ~3 min instalação do bun (máquina não tinha Node/npm/bun —
  imprevisto nº 1); ~2 min leitura do protótipo p/ mapear deps; ~4 min geração de
  código; ~2 min build+verificação.
- **Interrupção operacional:** 0 min dentro do lote (o backfill do Pipedrive seguia
  em background, sem custo de atenção).
- **Nota honesta:** o Dockerfile com estágio bun ainda NÃO foi exercitado num build
  real de deploy — primeiro deploy do Lote 1 é o teste; risco baixo, mas existe.

## Lote 1 — Growth core (Contas, Alertas, Cancelamentos)

- _pendente_

## Extrapolação (preencher após o Lote 1)

- _pendente_
