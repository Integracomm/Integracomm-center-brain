import { CalendarRange, Rocket } from "lucide-react";
import { useState } from "react";
import { useApi } from "@/hooks/use-api";
import { Hint } from "@/components/hint";
import { LoadingSkeleton, ErrorState } from "@/components/states";
import { SectionCard } from "@/components/blocks/section-card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { formatBRL, formatNumber, formatPct } from "@/lib/format";

// Marketing · Planejador de Lançamento (Lote 4) — /api/marketing/planejador
// inverte o lag: meta por bundle + data → quando lançar, quantos leads,
// que orçamento e com quais estratégias. Mesmas regras da tela HTML.

interface Payload {
  canal: string; alvo: string | null; total_pedido: number; sem_base: boolean;
  plano: {
    linhas: Array<{ bundle: string; bookings: number; taxa_pct?: number | null;
      leads_necessarios?: number; orcamento?: number; sem_historico: boolean }>;
    total_leads: number; total_orcamento: number; cpl_90d: number | null;
    lancar_ate: string; janela_p25: string; janela_p75: string;
    lag_mediana_d: number; lag_p25_d: number; lag_p75_d: number; atrasado: boolean;
    recomendacoes: Array<{ bundle: string; itens: Array<{ tipo: string; nome: string; bookings: number }> }>;
  } | null;
}

const thCls = "text-xs font-semibold uppercase tracking-wide text-muted-foreground";
const numCls = "text-right tabular-nums";
const BUNDLES = ["B1", "B2", "B3", "B4", "B5"];
const dbr = (iso: string) => iso.split("-").reverse().join("/");

export function MktPlanejadorPage() {
  const em60 = new Date(Date.now() + 60 * 86400000).toISOString().slice(0, 10);
  const [qtd, setQtd] = useState<Record<string, string>>({});
  const [alvo, setAlvo] = useState(em60);
  const [canal, setCanal] = useState("Meta Ads");
  const [params, setParams] = useState<string | null>(null);
  const q = useApi<Payload>(params ?? "/api/marketing/planejador");
  const d = q.data;

  const planejar = () => {
    const p = new URLSearchParams({ alvo, canal });
    BUNDLES.forEach((b) => { if (qtd[b]) p.set(`q${b}`, qtd[b]); });
    setParams(`/api/marketing/planejador?${p}`);
  };

  return (
    <div className="space-y-6">
      <header>
        <h1 className="font-display inline-flex items-center gap-2 text-2xl font-bold tracking-tight">Planejador de Lançamento<Hint area="marketing/planejador" titulo="_intro" /></h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Meta por bundle + data — o planejador inverte o lag e responde quando lançar, quantos leads,
          que orçamento e com quais estratégias.
        </p>
      </header>

      <div className="flex flex-wrap items-end gap-3 rounded-xl border border-border bg-card p-4">
        {BUNDLES.map((b) => (
          <label key={b} className="text-xs text-muted-foreground">
            {b}
            <Input type="number" min="0" placeholder="0" className="mt-1 w-[72px]"
              value={qtd[b] ?? ""} onChange={(e) => setQtd({ ...qtd, [b]: e.target.value })} />
          </label>
        ))}
        <label className="text-xs text-muted-foreground">
          resultado até
          <div className="mt-1 flex items-center gap-2">
            <CalendarRange className="h-4 w-4" />
            <Input type="date" value={alvo} onChange={(e) => setAlvo(e.target.value)} className="w-[160px]" />
          </div>
        </label>
        <label className="text-xs text-muted-foreground">
          canal
          <Select value={canal} onValueChange={setCanal}>
            <SelectTrigger className="mt-1 w-[150px]"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="Meta Ads">Meta Ads</SelectItem>
              <SelectItem value="Google Ads">Google Ads</SelectItem>
            </SelectContent>
          </Select>
        </label>
        <Button onClick={planejar}><Rocket className="mr-1 h-4 w-4" /> Planejar</Button>
      </div>
      <p className="-mt-3 text-xs text-muted-foreground">
        informe quantos bookings quer de cada bundle (ex.: 15 em B1 e 20 em B2) e a data-limite do resultado
      </p>

      {q.loading && params && <LoadingSkeleton rows={5} />}
      {q.error && <ErrorState message={q.error} onRetry={q.refetch} />}
      {d && d.sem_base && (
        <p className="rounded-xl border border-warning/40 bg-card p-4 text-sm text-muted-foreground">
          Sem base histórica suficiente neste canal (lag, CPL ou leads indisponíveis).
        </p>
      )}
      {d?.plano && (
        <>
          <SectionCard hint={<Hint area="marketing/planejador" titulo="Plano de lançamento" />}
            title={`Plano: ${d.total_pedido} bookings via ${d.canal}${d.alvo ? ` até ${dbr(d.alvo)}` : ""}`}
            subtitle={`taxa por bundle = bookings do bundle ÷ leads totais do canal (180d) · CPL 90d: ${d.plano.cpl_90d != null ? formatBRL(d.plano.cpl_90d) : "—"}`}>
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className={thCls}>Bundle</TableHead>
                    <TableHead className={`${thCls} text-right`}>Bookings</TableHead>
                    <TableHead className={`${thCls} text-right`}>Taxa lead→booking (180d)</TableHead>
                    <TableHead className={`${thCls} text-right`}>Leads necessários</TableHead>
                    <TableHead className={`${thCls} text-right`}>Orçamento</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {d.plano.linhas.map((l) => (
                    <TableRow key={l.bundle}>
                      <TableCell className="font-medium">{l.bundle}</TableCell>
                      <TableCell className={numCls}>{l.bookings}</TableCell>
                      {l.sem_historico ? (
                        <TableCell colSpan={3} className="text-sm text-muted-foreground">
                          sem booking histórico deste bundle no canal (180d) — sem base p/ estimar;
                          considere Indicações/LinkedIn ou outro canal
                        </TableCell>
                      ) : (
                        <>
                          <TableCell className={numCls}>{l.taxa_pct != null ? formatPct(l.taxa_pct, 2) : "—"}</TableCell>
                          <TableCell className={numCls}>{formatNumber(l.leads_necessarios ?? 0)}</TableCell>
                          <TableCell className={numCls}>{formatBRL(l.orcamento ?? 0)}</TableCell>
                        </>
                      )}
                    </TableRow>
                  ))}
                  <TableRow className="border-t-2">
                    <TableCell className="font-semibold">Total</TableCell>
                    <TableCell className={`${numCls} font-semibold`}>{d.total_pedido}</TableCell>
                    <TableCell />
                    <TableCell className={`${numCls} font-semibold`}>{formatNumber(d.plano.total_leads)}</TableCell>
                    <TableCell className={`${numCls} font-semibold`}>{formatBRL(d.plano.total_orcamento)}</TableCell>
                  </TableRow>
                </TableBody>
              </Table>
            </div>

            <div className="mt-4 overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className={thCls}>Janela de lançamento</TableHead>
                    <TableHead className={`${thCls} text-right`}>Mediana</TableHead>
                    <TableHead className={`${thCls} text-right`}>p25–p75</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  <TableRow>
                    <TableCell>Lançar a campanha até</TableCell>
                    <TableCell className={`${numCls} font-semibold`}>{dbr(d.plano.lancar_ate)}</TableCell>
                    <TableCell className={numCls}>
                      {dbr(d.plano.janela_p25).slice(0, 5)} — {dbr(d.plano.janela_p75).slice(0, 5)}
                    </TableCell>
                  </TableRow>
                  <TableRow>
                    <TableCell>Lag até 1º booking</TableCell>
                    <TableCell className={numCls}>{d.plano.lag_mediana_d} dias</TableCell>
                    <TableCell className={numCls}>{d.plano.lag_p25_d}–{d.plano.lag_p75_d} dias</TableCell>
                  </TableRow>
                </TableBody>
              </Table>
            </div>

            {d.plano.atrasado && (
              <p className="mt-3 rounded-lg border border-destructive/40 p-3 text-sm text-destructive">
                ⚠ A data-limite mediana já passou — cenário conservador inviável; reduza a meta,
                antecipe por outro canal ou reveja a data.
              </p>
            )}
            <p className="mt-3 text-xs text-muted-foreground">
              Use o p75 como cenário de risco.
            </p>
          </SectionCard>

          {d.plano.recomendacoes.length > 0 && (
            <SectionCard hint={<Hint area="marketing/planejador" titulo="Estratégias e criativos recomendados" />}
              title="Estratégias e criativos recomendados"
              subtitle="histórico de quem já converteu cada bundle — base p/ replicar/iterar">
              <div className="space-y-3">
                {d.plano.recomendacoes.map((r) => (
                  <div key={r.bundle}>
                    <div className="text-sm font-semibold">{r.bundle} — o que já FECHOU esse bundle neste canal:</div>
                    <ul className="mt-1 space-y-1 text-sm text-muted-foreground">
                      {r.itens.map((i) => (
                        <li key={`${i.tipo}-${i.nome}`}>{i.tipo} <b className="text-foreground">{i.nome}</b> ({i.bookings} bookings)</li>
                      ))}
                    </ul>
                  </div>
                ))}
              </div>
            </SectionCard>
          )}
        </>
      )}
    </div>
  );
}
