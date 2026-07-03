# Faturamento (planilhas NPS) prediz churn? — conclusão (03-07-2026)

## Pergunta e contexto
Com o acesso às planilhas individuais de NPS/faturamento liberado (3 pastas do
Drive), testamos a crença registrada "faturamento é esparso e tardio, não é
preditor" — que até então era suposição, não medida. Scripts:
`backend/scripts/offline_fat_sweep.py` (varredura/caching) e
`offline_fat_churn.py` (caso-controle as-of, sem vazamento).

## Cobertura final dos dados
357/371 planilhas acessíveis (96%; nenhuma da coorte bloqueada). Funil dos 61
cancelados: 14 sem linha/link na planilha mestre · 7 com planilha sem nenhum
faturamento · **16 com planilha abandonada 2-3 meses antes do churn** · 24 com
janela completa no mês anterior ao churn. Controles: 85/200 com série.

## Desenho
Sinais de queda medidos só com meses ANTERIORES ao mês do evento (churn para
casos; para controles, mês cheio anterior): `mom` (mês/mês anterior), `base3`
(mês/média dos 3 anteriores), `slide2` (mês/2 meses atrás). Dois desenhos:
simples (controles ancorados em mai/2026) e **pareado por mês** (cada caso
comparado só com controles medidos no MESMO mês — elimina sazonalidade).

## Resultado

| horizonte | sinal | AUC simples | AUC pareado/mês |
|---|---|---|---|
| churn−1 | mom | 0,560 | **0,488** |
| churn−1 | base3 | 0,629 | **0,564** |
| churn−1 | slide2 | 0,557 | **0,559** |
| churn−2 | mom | 0,343 | **0,390** |
| churn−2 | base3 | 0,416 | **0,423** |
| churn−2 | slide2 | 0,490 | **0,430** |

(n = 20-25 cancelados × 60-85 controles; máximo possível com os dados.)

## Leitura
1. **Faturamento não prediz churn.** No desenho correto (pareado por mês), os
   sinais de queda ficam em 0,49-0,56 ≈ moeda ao ar. O indício animador das
   amostras parciais ("estagnação vs crescimento", AUC 0,63-0,66) era em boa
   parte **artefato de sazonalidade** — controles todos medidos em maio.
2. **Leve INVERSÃO 2 meses antes** (AUC 0,39-0,43; cancelados com +14-25% de
   crescimento vs controles estáveis): clientes cancelam mesmo com faturamento
   ok. Coerente com o resto do modelo — churn aqui é de RELACIONAMENTO
   (conversa/tom, AUC 0,81), não de resultado de vendas.
3. **Achado operacional**: 16/61 cancelados tiveram a planilha de NPS
   ABANDONADA 2-3 meses antes do churn — a equipe para de preencher quando o
   cliente está saindo. "Planilha sem atualização há 2+ meses" é um sinal de
   disciplina operacional que pode valer monitoramento (não entra no score por
   ora; é tardio e reflexo, não causa).

## Decisão
Confirmada a decisão existente, agora com medida: **faturamento não entra como
sinal preditor**; segue como ponderação de prioridade (MRR) e como seção
informativa do relatório mensal de assessoria.
