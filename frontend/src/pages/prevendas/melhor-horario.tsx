import { CalendarRange, PhoneCall, Target } from "lucide-react";
import { useMemo, useState } from "react";
import { useApi } from "@/hooks/use-api";
import { Hint } from "@/components/hint";
import { LoadingSkeleton, ErrorState } from "@/components/states";
import { KpiCard } from "@/components/kpi-card";
import { SectionCard } from "@/components/blocks/section-card";
import { Heatmap, type HeatmapCell } from "@/components/charts/heatmap";
import { Input } from "@/components/ui/input";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { formatPct } from "@/lib/format";
import type { HorariosPayload } from "@/types/api";

// Pré-vendas · Melhor Horário — heatmaps dia×hora (contagem e TAXA
// agendamentos÷ligações), grades por origem e por colaborador (escala POR
// LINHA — compara padrões, não volumes). Dados de /api/prevendas/horarios,
// que embrulha o _horarios_calc (a MESMA função da tela HTML).

const DOW = ["Dom", "Seg", "Ter", "Qua", "Qui", "Sex", "Sáb"];
const thCls = "text-xs font-semibold uppercase tracking-wide text-muted-foreground";

type Cel = { dow: number; hora: number; n: number };

function paraCells(cels: Cel[], dias: number[], horas: number[]): { rows: string[]; cols: string[]; cells: HeatmapCell[] } {
  const rows = horas.map((h) => `${String(h).padStart(2, "0")}h`);
  const cols = dias.map((d) => DOW[d]);
  const cells: HeatmapCell[] = cels
    .filter((c) => dias.includes(c.dow))
    .map((c) => ({ row: `${String(c.hora).padStart(2, "0")}h`, col: DOW[c.dow], value: c.n }));
  return { rows, cols, cells };
}

function grade(porChave: Record<string, Cel[]>, horas: number[]) {
  const rows = Object.keys(porChave).sort(
    (a, b) => somaN(porChave[b]) - somaN(porChave[a]));
  const cells: HeatmapCell[] = [];
  for (const k of rows) {
    const porHora = new Map<number, number>();
    for (const c of porChave[k]) porHora.set(c.hora, (porHora.get(c.hora) ?? 0) + c.n);
    for (const h of horas) {
      const n = porHora.get(h);
      if (n) cells.push({ row: k, col: `${h}h`, value: n });
    }
  }
  return { rows, cols: horas.map((h) => `${h}h`), cells };
}

const somaN = (cs: Cel[]) => cs.reduce((s, c) => s + c.n, 0);

export function MelhorHorarioPage() {
  const hoje = new Date();
  const iso = (d: Date) => d.toISOString().slice(0, 10);
  const [ini, setIni] = useState(iso(new Date(hoje.getFullYear(), hoje.getMonth(), 1)));
  const [fim, setFim] = useState(iso(hoje));
  const [bundle, setBundle] = useState("todos");
  const q = useApi<HorariosPayload>(
    `/api/prevendas/horarios?ini=${ini}&fim=${fim}&bundle=${bundle}`);
  const d = q.data;

  const diasAtivos = useMemo(() => {
    if (!d) return [1, 2, 3, 4, 5];
    const base = [1, 2, 3, 4, 5];
    if (d.celulas.some((c) => c.dow === 6)) base.push(6);
    if (d.celulas.some((c) => c.dow === 0)) base.push(0);
    return base;
  }, [d]);

  // horas em COMUM entre os dois mapas — mesma linha/altura nos dois lados
  // (feedback Otávio 21/07: 08h de um lado alinhada com 08h do outro)
  const horasComuns = useMemo(() => {
    if (!d) return [] as number[];
    return [...new Set([...d.celulas, ...d.ligacoes, ...d.celulas_taxa].map((c) => c.hora))].sort((a, b) => a - b);
  }, [d]);
  const agend = useMemo(() => (d ? paraCells(d.celulas, diasAtivos, horasComuns) : null), [d, diasAtivos, horasComuns]);

  // TAXA: conversão da ligação — numerador = ligações que converteram em
  // agendamento (creditada a última antes do agendamento; célula = hora em que
  // a ligação foi FEITA), denominador = ligações do slot. Subconjunto → ≤100%.
  // Células com <5 ligações vêm marcadas como amostra pequena.
  const taxa = useMemo(() => {
    if (!d || !d.ligacoes.length) return null;
    const ag = new Map(d.celulas_taxa.map((c) => [`${c.dow}|${c.hora}`, c.n]));
    const cells: HeatmapCell[] = [];
    for (const l of d.ligacoes) {
      if (!diasAtivos.includes(l.dow)) continue;
      const a = ag.get(`${l.dow}|${l.hora}`) ?? 0;
      cells.push({
        row: `${String(l.hora).padStart(2, "0")}h`, col: DOW[l.dow],
        value: Math.round((a / l.n) * 100), n: l.n, amostra_pequena: l.n < 5,
      });
    }
    // MESMAS linhas do mapa de agendamentos (horasComuns) — lado a lado alinhado
    return { rows: horasComuns.map((h) => `${String(h).padStart(2, "0")}h`), cols: diasAtivos.map((x) => DOW[x]), cells };
  }, [d, diasAtivos, horasComuns]);

  // melhores janelas por AGENDAMENTO (contagem) — integradas ao card do mapa.
  // O ranking por TAXA saiu com o mapa de conversão da ligação (Otávio 22/07):
  // a taxa geral sobrevive no KPI, com a ressalva dos sem-ligação ao lado.
  const topAgend = useMemo(() => {
    if (!d) return [];
    return [...d.celulas].sort((a, b) => b.n - a.n).slice(0, 5)
      .map((c) => ({ rot: `${DOW[c.dow]} ${String(c.hora).padStart(2, "0")}h`, v: `${c.n} agendamento(s)` }));
  }, [d]);

  // EIXO DE HORAS ÚNICO para os dois mapas por origem (Otávio 22/07: um ia até
  // 19h e o outro até 20h, o que quebrava a leitura lado a lado). É a união das
  // horas com dado real nos dois — não uma faixa fixa, para não criar coluna
  // vazia dos dois lados.
  const horasOrigem = useMemo(() => {
    if (!d) return [] as number[];
    const hs = new Set<number>(d.atendimento.map((r) => r.hora));
    for (const cels of Object.values(d.por_origem)) for (const c of cels) hs.add(c.hora);
    return [...hs].sort((a, b) => a - b);
  }, [d]);

  // ATENDIMENTO por origem × hora (Otávio 22/07: 'que horas os leads de meta
  // atendem mais ligações?'): das ligações feitas para leads de cada canal
  // naquela hora, % que o lead ATENDEU. Desfecho vem da telefonia (subject);
  // ligação registrada à mão sem desfecho fica FORA — não vira 0.
  const atd = useMemo(() => {
    if (!d || !d.atendimento.length) return null;
    const porCanal = new Map<string, Map<number, { a: number; l: number }>>();
    for (const r of d.atendimento) {
      const m = porCanal.get(r.canal) ?? new Map<number, { a: number; l: number }>();
      const v = m.get(r.hora) ?? { a: 0, l: 0 };
      v.a += r.atendidas; v.l += r.ligacoes;
      m.set(r.hora, v); porCanal.set(r.canal, m);
    }
    const totLig = (m: Map<number, { a: number; l: number }>) =>
      [...m.values()].reduce((s, v) => s + v.l, 0);
    const rows = [...porCanal.keys()].sort((x, y) => totLig(porCanal.get(y)!) - totLig(porCanal.get(x)!));
    const cells: HeatmapCell[] = [];
    for (const cn of rows)
      for (const h of horasOrigem) {
        const v = porCanal.get(cn)!.get(h);
        if (v?.l) cells.push({ row: cn, col: `${h}h`, value: Math.round((v.a / v.l) * 100),
                               n: v.l, amostra_pequena: v.l < 5 });
      }
    return { rows, cols: horasOrigem.map((h) => `${h}h`), cells };
  }, [d, horasOrigem]);

  // melhor janela de aproveitamento DE CADA CANAL (Otávio 22/07: ranking geral
  // repetia o mesmo canal; a decisão é 'a que horas eu ligo para ESTE canal').
  // Uma linha por canal, ordenada por volume de ligações; só horas com 5+
  // ligações concorrem — canal sem amostra aparece sinalizado, não some.
  const melhorPorCanal = useMemo(() => {
    if (!d || !d.atendimento.length) return [];
    const porCanal = new Map<string, { hora: number; a: number; l: number }[]>();
    for (const r of d.atendimento) {
      const arr = porCanal.get(r.canal) ?? [];
      const ex = arr.find((x) => x.hora === r.hora);
      if (ex) { ex.a += r.atendidas; ex.l += r.ligacoes; }
      else arr.push({ hora: r.hora, a: r.atendidas, l: r.ligacoes });
      porCanal.set(r.canal, arr);
    }
    return [...porCanal.entries()]
      .map(([canal, horas]) => {
        const totL = horas.reduce((s, x) => s + x.l, 0);
        const totA = horas.reduce((s, x) => s + x.a, 0);
        const elegiveis = horas.filter((x) => x.l >= 5);
        const best = elegiveis.length
          ? elegiveis.reduce((b, x) => (x.a / x.l > b.a / b.l ? x : b))
          : null;
        return { canal, totL, geral: totL ? (totA / totL) * 100 : 0, best };
      })
      .sort((x, y) => y.totL - x.totL);
  }, [d]);

  const gOrigem = useMemo(() => (d ? grade(d.por_origem, horasOrigem) : null), [d, horasOrigem]);
  // a grade por COLABORADOR segue na faixa comercial fixa (7h–20h): ela não fica
  // lado a lado com nenhum outro mapa, então não precisa do eixo compartilhado
  const horasComerciais = useMemo(() => Array.from({ length: 14 }, (_, i) => i + 7), []);

  const topJanelas = (cels: Cel[]) =>
    [...cels].sort((a, b) => b.n - a.n).slice(0, 3)
      .filter((c) => c.n >= 2)
      .map((c) => `${DOW[c.dow]} ${String(c.hora).padStart(2, "0")}h (${c.n})`)
      .join(" · ") || "—";

  const totLig = d ? d.ligacoes.reduce((s, c) => s + c.n, 0) : 0;
  const totAgTx = d ? d.celulas_taxa.reduce((s, c) => s + c.n, 0) : 0;

  return (
    <div className="space-y-6">
      <header>
        <h1 className="font-display inline-flex items-center gap-2 text-2xl font-bold tracking-tight">Melhor Horário<Hint area="prevendas/horarios" titulo="_intro" /></h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Quando as reuniões são agendadas (horário de Brasília) e onde a ligação RENDE mais — por
          dia×hora, origem do lead e bundle.
        </p>
      </header>

      <div className="flex flex-wrap items-center gap-3 rounded-xl border border-border bg-card p-4">
        <CalendarRange className="h-4 w-4 text-muted-foreground" />
        <Input type="date" value={ini} onChange={(e) => setIni(e.target.value)} className="w-[160px]" />
        <span className="text-xs text-muted-foreground">até</span>
        <Input type="date" value={fim} onChange={(e) => setFim(e.target.value)} className="w-[160px]" />
        <Select value={bundle} onValueChange={setBundle}>
          <SelectTrigger className="w-[170px]"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="todos">Todos os bundles</SelectItem>
            {["B1", "B2", "B3", "B4", "B5"].map((b) => <SelectItem key={b} value={b}>{b}</SelectItem>)}
          </SelectContent>
        </Select>
      </div>

      {q.loading && <LoadingSkeleton rows={5} />}
      {q.error && <ErrorState message={q.error} onRetry={q.refetch} />}
      {d && agend && (
        <>
          <div className="grid grid-cols-2 gap-4 md:grid-cols-3">
            <KpiCard icon={Target} tone="primary" title="Agendamentos no período"
              value={d.total.toLocaleString("pt-BR")} />
            <KpiCard icon={PhoneCall} tone="accent" title="Ligações concluídas"
              value={totLig.toLocaleString("pt-BR")}
              subtitle={d.taxa_ini ? `registradas a partir de ${d.taxa_ini.split("-").reverse().join("/")}` : undefined}
              caveat={d.taxa_ini ? "a taxa considera só o trecho com ligações registradas — numerador e denominador da MESMA janela" : undefined} />
            <KpiCard icon={Target} tone="success" title="Conversão da ligação (trecho coberto)"
              value={totLig ? formatPct((totAgTx / totLig) * 100) : "—"}
              subtitle="ligações que converteram em reunião ÷ ligações feitas"
              caveat={d.agend_sem_ligacao > 0
                ? `${d.agend_sem_ligacao} agendamento(s) de deals sem ligação registrada (indicação, inbound direto) ficam fora — esta taxa mede o rendimento da LIGAÇÃO`
                : undefined} />
          </div>

          {/* Agendamentos: mapa + top janelas no MESMO card (Otávio 22/07 — o
              mapa sozinho em largura total ficava grande demais, e a lista é a
              leitura direta dele). Os dois mapas por ORIGEM vêm depois. */}
          <SectionCard hint={<Hint area="prevendas/horarios" titulo="Mapa de calor" />}
            title="Agendamentos — hora × dia"
            subtitle="quanto mais escuro, mais agendamentos naquele dia/hora · detalhes no ⓘ">
            <div className="grid gap-6 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
              <Heatmap rows={agend.rows} cols={agend.cols} cells={agend.cells}
                color="var(--chart-1)" rowLabelWidth={54} dense legendLabel="agendamentos" />
              <div>
                <div className="mb-1 inline-flex items-center gap-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  Melhores horários por agendamento
                  <Hint area="prevendas/horarios" titulo="Top 5 janelas" />
                </div>
                <p className="mb-2 text-xs text-muted-foreground">
                  as 5 janelas dia+hora com mais agendamentos no período
                </p>
                <ul className="space-y-1.5">
                  {topAgend.map((x, i) => (
                    <li key={x.rot} className="flex justify-between gap-3 border-t border-border pt-1.5 text-sm first:border-t-0 first:pt-0">
                      <span><b>{i + 1}º</b> — {x.rot}</span>
                      <span className="shrink-0 tabular-nums text-muted-foreground">{x.v}</span>
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          </SectionCard>

          {/* Bloco ORIGEM: quando o lead de cada canal ATENDE × quando ele
              AGENDA — lado a lado porque respondem à mesma pergunta.
              Lado a lado só a partir de 2xl (Otávio 22/07): com o eixo de horas
              unificado são 15 colunas, e em 1280px as duas metades obrigavam a
              ROLAR para ver as últimas horas — nunca rolar para ver dado. */}
          <div className="grid gap-6 2xl:grid-cols-2">
            <SectionCard hint={<Hint area="prevendas/horarios" titulo="Atendimento de ligações por origem" />}
              headerClassName="min-h-[72px]"
              title="Atendimento de ligações — origem × hora"
              subtitle={`das ligações FEITAS na hora, % que o lead ATENDEU (embaixo, o nº de ligações — a % sozinha engana em amostra pequena) · escala por linha · role de lado se o período abrir muitas horas · hachura = <5 ligações${
                d.atendimento_ini ? ` · desfecho desde ${d.atendimento_ini.split("-").reverse().join("/")}` : ""}`}>
              {atd && atd.cells.length ? (
                <>
                  <Heatmap rows={atd.rows} cols={atd.cols} cells={atd.cells}
                    color="var(--success)" rowScale dense tall scrollX rowLabelWidth={110}
                    valueLabel={(v) => `${v}%`}
                    subLabel={(c) => (c.n != null ? String(c.n) : null)}
                    legendLabel="atendimento"
                    tooltipLabel={(c) => `${c.row} ${c.col}: ${c.value}% atendidas (${c.n} ligação(ões))${c.amostra_pequena ? " · amostra pequena" : ""}`} />
                  <div className="mt-3">
                    <div className="mb-1 inline-flex items-center gap-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                      Melhor janela de cada canal
                      <Hint area="prevendas/horarios" titulo="Melhores janelas de aproveitamento" />
                    </div>
                    <ul className="space-y-1.5">
                      {melhorPorCanal.map((x) => (
                        <li key={x.canal} className="flex justify-between gap-3 border-t border-border pt-1.5 text-sm first:border-t-0 first:pt-0">
                          <span className="truncate"><b>{x.canal}</b>{x.best && (
                            <span className="text-muted-foreground"> · melhor às {String(x.best.hora).padStart(2, "0")}h</span>
                          )}</span>
                          <span className="shrink-0 tabular-nums text-muted-foreground">
                            {x.best
                              ? `${((x.best.a / x.best.l) * 100).toFixed(0)}% (${x.best.a}/${x.best.l}) · geral ${x.geral.toFixed(0)}%`
                              : `sem hora com 5+ ligações · geral ${x.geral.toFixed(0)}%`}
                          </span>
                        </li>
                      ))}
                    </ul>
                  </div>
                </>
              ) : (
                <p className="text-sm text-muted-foreground">
                  Sem desfecho de ligação no período — o desfecho (atendida/não atendida) entrou na
                  coleta em 22/07; a seção acende conforme a coleta diária acumula.
                </p>
              )}
            </SectionCard>

            <SectionCard hint={<Hint area="prevendas/horarios" titulo="Melhor horário por origem do lead" />}
              headerClassName="min-h-[72px]"
              title="Padrão por origem do lead — origem × hora"
              subtitle="quando o lead de cada canal AGENDA · escala POR LINHA (compara o padrão independente do volume) · célula contornada = pico">
              {gOrigem && gOrigem.cells.length ? (
                <Heatmap rows={gOrigem.rows} cols={gOrigem.cols} cells={gOrigem.cells}
                  color="var(--chart-2)" rowScale dense tall scrollX rowLabelWidth={110}
                  legendLabel="agendamentos" />
              ) : (
                <p className="text-sm text-muted-foreground">Sem dados por origem no período.</p>
              )}
              <div className="mt-3">
                <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  Top janelas por origem (com o dia da semana)
                </div>
                <Table>
                  <TableHeader>
                    <TableRow className="bg-muted/40 hover:bg-muted/40">
                      <TableHead className={thCls}>Origem</TableHead>
                      <TableHead className={`${thCls} text-right`}>Agendamentos</TableHead>
                      <TableHead className={thCls}>Melhores janelas</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {Object.entries(d.por_origem)
                      .sort((a, b) => somaN(b[1]) - somaN(a[1]))
                      .map(([org, cels]) => (
                        <TableRow key={org}>
                          <TableCell className="font-medium">
                            {org}{somaN(cels) < 30 && <span className="ml-1 text-muted-foreground" title="amostra pequena (<30)">*</span>}
                          </TableCell>
                          <TableCell className="text-right tabular-nums">{somaN(cels)}</TableCell>
                          <TableCell className="text-sm text-muted-foreground">{topJanelas(cels)}</TableCell>
                        </TableRow>
                      ))}
                  </TableBody>
                </Table>
              </div>
            </SectionCard>
          </div>

          <SectionCard hint={<Hint area="prevendas/horarios" titulo="Melhores janelas por bundle" />}
            title="Padrão por bundle"
            subtitle="a melhor janela pode variar por plano — atenção às amostras pequenas">
            <Table>
              <TableHeader>
                <TableRow className="bg-muted/40 hover:bg-muted/40">
                  <TableHead className={thCls}>Bundle</TableHead>
                  <TableHead className={`${thCls} text-right`}>Agendamentos</TableHead>
                  <TableHead className={thCls}>Melhores janelas</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {Object.entries(d.por_bundle).map(([b, cels]) => (
                  <TableRow key={b}>
                    <TableCell className="font-medium">
                      {b}{somaN(cels) < 30 && <span className="ml-1 text-muted-foreground" title="amostra pequena (<30)">*</span>}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">{somaN(cels)}</TableCell>
                    <TableCell className="text-sm text-muted-foreground">{topJanelas(cels)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </SectionCard>

          <SectionCard hint={<Hint area="prevendas/horarios" titulo="Agendamentos por colaborador × hora" />}
            title="Padrão por colaborador — pessoa × hora"
            subtitle="escala POR LINHA · célula contornada = pico da pessoa · * = amostra pequena (<30)">
            <ColabGrade porColab={d.por_colab} horas={horasComerciais} />
          </SectionCard>
        </>
      )}
    </div>
  );
}

function ColabGrade({ porColab, horas }: {
  porColab: Record<string, Array<{ hora: number; n: number }>>; horas: number[];
}) {
  const rows = Object.keys(porColab).sort(
    (a, b) => soma(porColab[b]) - soma(porColab[a]));
  const cells: HeatmapCell[] = [];
  for (const k of rows) {
    for (const { hora, n } of porColab[k]) {
      if (n && horas.includes(hora)) cells.push({ row: rot(k, porColab[k]), col: `${hora}h`, value: n });
    }
  }
  if (!cells.length) return <p className="text-sm text-muted-foreground">Sem dados por colaborador.</p>;
  return (
    <Heatmap rows={rows.map((k) => rot(k, porColab[k]))} cols={horas.map((h) => `${h}h`)}
      cells={cells} color="var(--chart-4)" rowScale dense rowLabelWidth={110} legendLabel="agendamentos" />
  );
}

const soma = (v: Array<{ n: number }>) => v.reduce((s, c) => s + c.n, 0);
const rot = (k: string, v: Array<{ n: number }>) => (soma(v) < 30 ? `${k} *` : k);
