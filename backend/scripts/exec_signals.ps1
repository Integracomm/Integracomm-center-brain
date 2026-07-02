# Caso-controle de EXECUCAO (ClickUp/Operacao Connector) — reconstrucao as-of-date.
# Fonte: mirror Supabase vhflfvdfjhncfioncwpl (anon key publica do codigo-fonte do HUB).
# subtarefas retem datas reais 2023->2026, entao reconstruimos a saude de execucao
# NA DATA DO CHURN (casos) vs HOJE (controle), sem vazamento (so subtasks <= AsOf).
$root=(Get-Item $PSScriptRoot).Parent.Parent.FullName
$D=Join-Path $root 'data'
$base="https://vhflfvdfjhncfioncwpl.supabase.co/rest/v1"
$anon="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InZoZmxmdmRmamhuY2Zpb25jd3BsIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzQ2MDcwNDksImV4cCI6MjA5MDE4MzA0OX0.tDrlST6rXBQzImaFs0HnikauwjEx3wr1DnWqz6atr0Q"
$h=@{ apikey=$anon; Authorization="Bearer $anon" }
function Norm($s){ if(-not $s){return ''}; $x=$s.ToLower().Normalize([Text.NormalizationForm]::FormD); $x=($x.ToCharArray()|Where-Object{[Globalization.CharUnicodeInfo]::GetUnicodeCategory($_) -ne 'NonSpacingMark'}) -join ''; $x=$x -replace '^\s*\[[^\]]*\]\s*',''; $x=($x -split '\|')[0]; $x=$x -replace 'integracomm','' -replace '[^a-z0-9 ]',' ' -replace '\s+',' '; return $x.Trim() }
function D2($v){ if($null -eq $v -or $v -eq ''){return $null}; try { return [datetime]$v } catch { return $null } }

# clientes: nome -> id
$cli=Invoke-RestMethod -Uri "$base/clientes?select=id,nome_cliente&limit=5000" -Headers $h -TimeoutSec 60
$nameToId=@{}; foreach($r in $cli){ $n=Norm $r.nome_cliente; if($n -and -not $nameToId.ContainsKey($n)){$nameToId[$n]=$r.id} }

# coortes -> (cliente_id, AsOf)
$today=[datetime]'2026-06-26'
$coh=@()
foreach($r in Import-Csv "$D\cases_expanded.csv"){ $id=$nameToId[(Norm $r.cliente)]; if($id -and $r.date){ $coh+=[pscustomobject]@{cohort='caso';cliente=$r.cliente;cliente_id=$id;asof=([datetime]$r.date)} } }
$ctrlAll=Import-Csv "$D\controls_active_bundles.csv" | Sort-Object { Get-Random } | Select-Object -First 70
foreach($r in $ctrlAll){ $id=$nameToId[(Norm $r.cliente)]; if($id){ $coh+=[pscustomobject]@{cohort='controle';cliente=$r.cliente;cliente_id=$id;asof=$today} } }
"Coorte mapeada p/ cliente_id: casos=$((@($coh|Where-Object{$_.cohort -eq 'caso'})).Count) controle=$((@($coh|Where-Object{$_.cohort -eq 'controle'})).Count)"

# pull subtarefas para os cliente_ids (em lotes)
$ids=@($coh.cliente_id | Sort-Object -Unique)
$subsByCli=@{}
for($i=0;$i -lt $ids.Count;$i+=40){
  $chunk=$ids[$i..([math]::Min($i+39,$ids.Count-1))]
  $inlist=($chunk -join ',')
  $url="$base/subtarefas?select=cliente_id,data_vencimento,data_conclusao&cliente_id=in.($inlist)&limit=10000"
  try { $rows=Invoke-RestMethod -Uri $url -Headers $h -TimeoutSec 90 } catch { $rows=@() }
  foreach($s in $rows){ if(-not $subsByCli.ContainsKey($s.cliente_id)){$subsByCli[$s.cliente_id]=@()}; $subsByCli[$s.cliente_id]+=$s }
}
"Subtarefas carregadas p/ $($subsByCli.Count) clientes."

# metricas as-of-date (sem vazamento: so vencimentos <= AsOf)
function ExecMetrics($subs,$asof){
  $r=@{ pct_no_prazo=$null; atrasadas_abertas=0; concl_30=0; concl_30_60=0; n_venc=0 }
  if(-not $subs){ return $r }
  $noPrazo=0;$atrasadas=0
  foreach($s in $subs){
    $dv=D2 $s.data_vencimento; $dc=D2 $s.data_conclusao
    if($dv -and $dv -le $asof){
      $r.n_venc++
      if($dc -and $dc -le $dv){ $noPrazo++ }
      elseif($dc -and $dc -le $asof -and $dc -gt $dv){ $atrasadas++ }   # concluida com atraso
      elseif(-not $dc -or $dc -gt $asof){ $atrasadas++; $r.atrasadas_abertas++ }  # vencida e nao concluida ate AsOf
    }
    if($dc -and $dc -le $asof -and $dc -ge $asof.AddDays(-30)){ $r.concl_30++ }
    if($dc -and $dc -lt $asof.AddDays(-30) -and $dc -ge $asof.AddDays(-60)){ $r.concl_30_60++ }
  }
  $den=$noPrazo+$atrasadas
  if($den -gt 0){ $r.pct_no_prazo=[math]::Round($noPrazo/$den*100,1) }
  return $r
}

$out=@()
foreach($c in $coh){
  $m=ExecMetrics $subsByCli[$c.cliente_id] $c.asof
  $out+=[pscustomobject]@{ cohort=$c.cohort; cliente=$c.cliente; asof=$c.asof.ToString('yyyy-MM-dd'); pct_no_prazo=$m.pct_no_prazo; atrasadas_abertas=$m.atrasadas_abertas; concl_30=$m.concl_30; concl_30_60=$m.concl_30_60; n_venc=$m.n_venc }
}
$out | Export-Csv "$D\exec_signals.csv" -NoTypeInformation -Encoding UTF8
function Avg($rows,$p){ $v=@($rows|Where-Object{$_.$p -ne $null -and $_.$p -ne ''}|ForEach-Object{[double]$_.$p}); if($v.Count){[math]::Round(($v|Measure-Object -Average).Average,1)}else{0} }
$ca=$out|Where-Object{$_.cohort -eq 'caso'}; $co=$out|Where-Object{$_.cohort -eq 'controle'}
"=== EXECUCAO as-of-date (caso n=$($ca.Count) vs controle n=$($co.Count)) ==="
"% no prazo (acumulado ate AsOf):        casos=$(Avg $ca 'pct_no_prazo')%  controle=$(Avg $co 'pct_no_prazo')%"
"atrasadas em aberto na data (media):     casos=$(Avg $ca 'atrasadas_abertas')  controle=$(Avg $co 'atrasadas_abertas')"
"conclusoes ultimos 30d (ritmo, media):   casos=$(Avg $ca 'concl_30')  controle=$(Avg $co 'concl_30')"
"trajetoria ritmo (30-60d -> 0-30d):      casos=$(Avg $ca 'concl_30_60')->$(Avg $ca 'concl_30')  controle=$(Avg $co 'concl_30_60')->$(Avg $co 'concl_30')"
"casos com algum vencimento avaliavel:    $((@($ca|Where-Object{[int]$_.n_venc -gt 0})).Count)/$($ca.Count)  controle: $((@($co|Where-Object{[int]$_.n_venc -gt 0})).Count)/$($co.Count)"