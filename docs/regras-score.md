# Regras do score de saúde / risco de churn — referência

> Documento de referência permanente para validar casos reais. **Extraído
> diretamente do código** (`backend/app/agents/growth/scoring.py` e
> `trajectory.py`), não de memória. Se o código mudar, este arquivo deve mudar
> junto. Última sincronização: **2026-06-30 (blend nível absoluto + relativo)**.
>
> ⚠️ Os limiares abaixo são **heurísticos/provisórios** — definidos na calibração
> caso-controle e serão recalibrados pelo loop de feedback (sinal × desfecho)
> conforme acumula churn real. São uma régua estável para comparar casos *hoje*,
> não verdades permanentes.
>
> **Changelog:**
> - **2026-07-01** — **execução ATIVA no bloco de 15%** (flag `EXECUTION_IN_SCORE`,
>   default ligado): entra como CONFIRMADOR, risco direto = 1 − exec_score/100
>   (porte fiel do computeLiveScore via mirror ClickUp, as-of). Evidência: não
>   prediz churn sozinha (AUC 0,49/0,44 em churn−30/−60), mas a 15% renormalizado
>   é NEUTRA no ranking (AUC coorte 0,822→0,820) e traz atrito de entrega para o
>   score/motivos. Sem sinal → bloco ausente, renormaliza (não pune ausência).
>   Execução ruim NÃO vira "intenção de saída" (não é fala de saída).
> - **2026-07-01** — **aprendizado de boas práticas**: ações registradas por conta
>   (`interventions`: ação + dor + desfecho); quando `retido`, a prática passa a
>   ser citada na diretriz de casos futuros com a MESMA dor (📚). API:
>   POST /api/interventions, POST /api/interventions/{id}/result, GET /api/practices.
> - **2026-06-30** — **trajetória comensurável e ponderada**: a direção
>   (subindo/estável/caindo) passou a ser a mudança de NÍVEL dos sinais de risco
>   absoluto (silêncio/tom, frações 0–1, metade recente vs antiga), ponderada pelos
>   pesos do score. Antes somava velocidades em unidades diferentes (comprimento em
>   chars dominava) → 61% da carteira "caindo" falso na 1ª rodada real. Depois do
>   fix: caindo 61%→20%, alertas 96→50 na carteira de 150. Ver seção 3.
> - **2026-06-30** — **peso intra-bloco (opção A)**: silêncio 0,75/iniciativa 0,25 e
>   tom 0,75/comprimento 0,25 (rebaixa os sinais relativos ruidosos a secundários).
>   6 casos revalidados com o negócio: 5/6 corretos, único "erro" = churn
>   estruturalmente invisível (decisão pessoal, sem rastro no grupo).
> - **2026-06-30** — **gate de cobertura** (`MIN_COVERAGE_WEEKS = 2`): conta sem
>   dados suficientes de WhatsApp vira `evaluable=False`/faixa `sem_dados`/sem
>   alerta (lista de revisão manual), em vez de "saudável 100". Validação ao vivo:
>   AUC subiu de 0,52 (tudo) p/ ~0,81 (só avaliáveis). Ver caixa "Gate de
>   cobertura" na seção 2.
> - **2026-06-30** — `signal_risk` passou a misturar **nível absoluto** + relativo
>   para silêncio e tom negativo (`_ABSOLUTE_BLEND = 0,6`). Motivo: o modelo
>   só-relativo apagava a diferença absoluta validada (o churner sempre-quieto não
>   desvia do próprio baseline) e o AUC de ranking caía a ~aleatório. Validação
>   offline na coorte (cache de analyses, pelo `score_account` real): AUC
>   **0,68 → 0,79**. Confirmação final com mensagens ao vivo (iniciativa/comprimento)
>   pendente. Ver seção 2, item 1.
> - 2026-06-26 — o estágio deixou de ser só nível de risco e passou a
>   combinar nível + trajetória (evolução aprovada). Seções 2, 3 e 5 refletem isso.

---

## Visão geral — as quatro saídas e de onde cada uma vem

| Saída | O que é | Derivada de | Função |
|---|---|---|---|
| **score** (0–100) | nível de saúde atual (100 = saudável) | `health = 100·(1 − risco_total)` | `score_account` |
| **faixa de risco** | rótulo do nível atual | função **só do score** | `_risk_band(health)` |
| **trajetória** | para onde está indo (subindo/estável/caindo) | velocidade média dos sinais | `_trajectory_from_velocity` |
| **estágio de declínio** | onde está na jornada de saída | **nível de risco + trajetória + override de tardio** | `_stage(risco_total, blocos, trajetória)` |

**Como o score nasce** (resumo):
1. Cada **sinal** vira um **risco 0–1** combinando o desvio do baseline da conta (peso 0,6) e a velocidade da tendência (peso 0,4) — `signal_risk`. **Sinais com escala absoluta de risco** (silêncio e tom negativo — ambos são frações 0–1 de %dias, "maior = pior"): o risco mistura o **nível absoluto** da janela (peso `_ABSOLUTE_BLEND` = **0,6**) com esse risco relativo (0,4) — `risco = 0,6·nível + 0,4·(0,6·desvio + 0,4·velocidade)`. Sinais sem "normal" absoluto (iniciativa, comprimento) ficam **puramente relativos**.
2. Sinais agrupados em **4 blocos**; risco do bloco = **média PONDERADA** dos riscos dos seus sinais (peso intra-bloco). No WhatsApp os líderes fortes dominam: **silêncio 0,75 / iniciativa 0,25** (engagement) e **tom negativo 0,75 / comprimento 0,25** (tone). Iniciativa e comprimento são secundários (relativos, sem escala absoluta) — entram no score e nos motivos, mas não mandam. Os pesos renormalizam sobre os sinais presentes (só silêncio veio → vale 1). Sinal sem peso definido = 1,0.
3. `risco_total` (0–1) = soma ponderada pelos pesos aprovados:

   | Bloco | Peso | Sinais |
   |---|---|---|
   | engagement | **45** | silêncio, iniciativa do cliente |
   | tone | **25** | comprimento da msg, tom negativo |
   | execution | **15** *(confirmador; flag `EXECUTION_IN_SCORE`)* | execução ClickUp (risco direto = 1 − exec/100) |
   | lagging (tardio) | **15** | CRÍTICO explícito, inadimplência |

4. `score = round(100·(1 − risco_total), 1)`.

> **`risco_total = 1 − score/100`** — score e risco_total são o mesmo número em
> escalas diferentes. É a chave da relação faixa↔estágio (seção 3).

> **🚧 Gate de cobertura (`MIN_COVERAGE_WEEKS = 2`)** — ausência de dado NÃO é
> saúde. Se a conta tem menos de **2 semanas** distintas de sinal líder de
> WhatsApp na janela (`coverage_weeks`), ela é marcada **`evaluable = False`**,
> faixa **`sem_dados`**, recomendação "revisar manualmente" e **não dispara
> alerta automático** — sai do ranking de saúde e vai p/ uma lista à parte. Sem
> isso, um cancelando que ficou em silêncio pontuava "saudável 100" (falsa
> tranquilidade) — foi o que derrubava o AUC de ranking a ~aleatório na validação
> ao vivo. Na coorte, ~25% dos cancelados (11/44) não tinham cobertura pré-churn.

**Confirmador tardio (bloco `lagging`) — risco DIRETO, não trajetória** (um "quero
cancelar" é fato, não tendência). O coletor calcula:
- CRÍTICO nas `analyses` nos últimos **14 dias**, *ou* "fala em cancelar" (regex
  conservadora de cancelar serviço/contrato) nas mensagens dos últimos **21 dias**
  → `direct_risk = 0,90` → **dispara o override de intenção de saída** (≥ 0,60).
- CRÍTICO entre **14–30 dias**, não recorrente → `direct_risk = 0,50` →
  confirma/eleva risco, mas **NÃO** força saída (a conta pode ter se recuperado).

**Guarda de melhora sustentada** (`_sustained_rising`): um `subindo` só rebaixa o
estágio em 2 níveis (recuperação plena) se a melhora persistir além do período
mais recente; um pico isolado de uma única semana rebaixa no máximo 1 nível
("recuperando"), não "saudável" pleno.

---

## 1. Faixa de risco — limiares exatos

Função `_risk_band(health)`. Decide **só pelo score** (cortes estritos `>`):

| Faixa | Condição (score) |
|---|---|
| `baixo` | score **> 70** |
| `medio` | **50 < score ≤ 70** |
| `alto` | **30 < score ≤ 50** |
| `critico` | score **≤ 30** |

---

## 2. Estágio de declínio — árvore de decisão exata

Função `_stage(risco_total, blocos, trajetória)`. **Ordem importa:**

**Passo 1 — override de sinal tardio:**
> Se o maior risco entre os sinais do bloco `lagging` for **≥ 0,60** → estágio =
> **`intenção de saída`** (para aqui). Um confirmador forte (cliente falou em
> cancelar, inadimplência grave) joga direto para o fim, independente de
> nível/trajetória — isso é jornada-correto.

**Passo 2 — o nível de risco define a PROFUNDIDADE potencial (índice 0–4):**

| `risco_total` | score equiv. | nível |
|---|---|---|
| < 0,20 | > 80 | 0 — saudável |
| 0,20 – 0,40 | 60–80 | 1 — desengajamento inicial |
| 0,40 – 0,60 | 40–60 | 2 — insatisfação latente |
| 0,60 – 0,80 | 20–40 | 3 — insatisfação ativa |
| ≥ 0,80 | ≤ 20 | 4 — intenção de saída |

**Passo 3 — a TRAJETÓRIA decide quanto dessa profundidade a conta ocupa.**
A conta só **avança** na jornada quando a deterioração é sustentada (caindo), e
**recua** se está melhorando:

| trajetória | ajuste no índice |
|---|---|
| `caindo` | **0** — ocupa o nível cheio |
| `estável` | **−1** — segura um passo atrás |
| `subindo` | **−2** — recua (recuperando) |
| `desconhecida` | **−1** — conservador |

`índice_final = clamp(nível + ajuste, 0, 4)` → estágio.

> **Exemplo:** três contas com risco_total 0,45 (nível 2 = insatisfação latente):
> a que está **caindo** fica em `insatisfação latente`; a **estável** recua para
> `desengajamento inicial`; a que está **subindo** recua para `saudável`. Mesmo
> nível de risco, estágios diferentes — **agora a jornada (direção) importa.**

---

## 3. Relação entre as quatro saídas

> ⚙️ **Atualizado 2026-06-26:** o estágio passou a ser sensível à trajetória. A
> descrição abaixo reflete o comportamento NOVO (sua leitura original agora está
> correta).

- **score + faixa** = nível atual ("onde está agora").
- **trajetória** = direção ("para onde vai"), calculada da velocidade.
- **estágio** = combina **profundidade (nível de risco)** + **direção (trajetória)**
  + override de tardio. Reflete a **jornada**: a conta só ocupa um estágio
  profundo se a deterioração for sustentada.

| Pergunta | Resposta (código atual) |
|---|---|
| Estágio depende da trajetória? | **Sim** (passo 3) — além do nível e do override de tardio. |
| Faixa e estágio são independentes? | **Parcialmente.** Ambos partem do score (correlacionados), mas o estágio também depende da trajetória → **duas contas na mesma faixa podem ter estágios diferentes** se uma cai e a outra sobe. |
| O que descreve "para onde vai"? | Trajetória (direção) e estágio (jornada). |

> **Exemplo real (amostra):** SAMA (faixa `medio`, **subindo**) → estágio
> `saudável`. Uma conta `medio` **caindo** ficaria em estágio mais profundo.
> Mesma faixa, estágios diferentes — pela trajetória.

---

## 4. Saídas auxiliares

**Trajetória** — `_trajectory_from_velocity(v)`. `v` = `_weighted_health_velocity`:
mudança de NÍVEL dos sinais de risco ABSOLUTO (silêncio/tom, frações 0–1 →
comensuráveis), metade recente vs antiga, ponderada pelos pesos do score (positivo
= risco caindo = melhorando). Sinais sem escala absoluta (iniciativa/comprimento)
NÃO entram na trajetória — em unidades diferentes, dominavam e geravam "caindo"
falso. `v` é uma variação de nível 0–1 (não mais velocidade/dia):

| Trajetória | Condição |
|---|---|
| `caindo` | v **≤ −0,05** (nível de risco subiu >5% entre as metades) |
| `subindo` | v **≥ +0,05** |
| `estável` | −0,05 < v < +0,05 |

**Gatilho de alerta** — `should_alert(score)`:

| Dispara? | Condição |
|---|---|
| Sim | estágio `intenção de saída` ou `insatisfação ativa` — **saída confirmada SEMPRE alerta**, independe da faixa |
| Sim | faixa `alto` **ou** `critico` |
| Sim | faixa `medio` **E** trajetória `caindo` |
| Não | demais casos (faixa `baixo` sem estágio profundo não alerta) |

**Confiança** (0,1–1,0) — `_confidence`: `alcance_médio_em_dias / 60`, limitado a
[0,1; 1,0]. 60+ dias de histórico ≈ confiança plena.

**Lead-time (dias)** — `_lead_time_days`: `None` se velocidade ≥ 0; senão
`int(max(7, min(120, (1 − risco_total)·120)))`.

---

## 5. Tabela de validação — snapshot (dados AO VIVO; números mudam a cada dia)

> Rodado com `analyses` ao vivo + `asof = hoje`. Como os dados são vivos, os
> valores exatos mudam dia a dia; o que vale como referência são as **regras**.

| Conta | score | faixa | trajetória | estágio | alerta (severidade) |
|---|---|---|---|---|---|
| SAMA IMPORTS (cancelado) | 60,3 | medio | subindo | intenção de saída | **crítico** |
| FAMILIA DE NEGOCIOS (ativo) | 66,3 | medio | caindo | intenção de saída | **crítico** |
| NAVALHA AUTO PARTS (ativo) | 68,6 | medio | caindo | desengajamento inicial | **alto** |
| PHL BELEZA (cancelado) | 75,1 | baixo | estável | intenção de saída | **crítico** |
| LOJA DOS STICKERS (cancelado) | 77,6 | baixo | caindo | desengajamento inicial | **atenção** |
| FANATICOS RETRO (ativo) | 88,7 | baixo | estável | saudável | — |

- **FAMILIA → intenção de saída (crítico):** cancelamento de 26/06 capturado como
  CRÍTICO recente (`analyses` ao vivo). Antes saía como desengajamento por **cache
  desatualizado** — corrigido (coletor passou a ler `analyses` ao vivo, nunca de cache).
- **LOJA → desengajamento + atenção:** churner quieto (`baixo` + `caindo`) → alerta
  brando; não passa mais sem registro.
- **SAMA / PHL → intenção de saída (crítico):** override de cancelamento (CRÍTICO +
  "quero cancelar"), domina score e trajetória.

---

## 6. Limitações conhecidas que afetam estes números (hoje)

- **Sinais de mensagem agora COMPLETOS:** o gateway passou a paginar por
  `group_id` (índice composto + keyset); o leitor usa páginas de 200 (500+ estoura
  o limite de payload, ~24 MB/500 msgs). Os 4 sinais relacionais estão completos.
- **Execução com peso provisório (15):** não revalidada (ver `scoring.py`).
- **Discriminação é populacional, não determinística:** o modelo separa coortes
  em média (N=34), não crava por conta. Use o score como prioridade/tendência +
  loop prospectivo, não como veredito individual.
