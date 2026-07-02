# Passo 3a — sinais estruturais (sem Claude) caso x controle, a partir das mensagens.
# Para cada grupo da coorte, puxa mensagens na janela de 90d (filtro group_id + cursor),
# separa cliente vs equipe (sender_name ~ INTEGRACOMM = equipe) e computa:
#   client_share, tendência de iniciativa (1ª metade vs 2ª metade), comprimento médio
#   do cliente (tendência), latência de resposta do cliente.
# Também soma caracteres (cliente+equipe) p/ estimar custo do 3b (tom via Claude).
$root=(Get-Item $PSScriptRoot).Parent.Parent.FullName
$dataDir=Join-Path $root 'data'
$lines=Get-Content (Join-Path $root '.env')
$URL=(($lines|Where-Object{$_ -match '^WHATSAPP_READ_API_URL='}) -split '=',2)[1].Trim()
$KEY=(($lines|Where-Object{$_ -match '^WHATSAPP_READ_API_KEY='}) -split '=',2)[1].Trim()
$hh=@{ 'x-api-key'=$KEY }

function Norm($s){ if(-not $s){return ''}; $x=$s.ToLower().Normalize([Text.NormalizationForm]::FormD); $x=($x.ToCharArray()|Where-Object{[Globalization.CharUnicodeInfo]::GetUnicodeCategory($_) -ne 'NonSpacingMark'}) -join ''; $x=$x -replace '^\s*\[[^\]]*\]\s*',''; $x=($x -split '\|')[0]; $x=$x -replace 'integracomm','' -replace '[^a-z0-9 ]',' ' -replace '\s+',' '; return $x.Trim() }
function ExId($s){ if($s -match 'id\s*:\s*([a-z0-9_-]+)'){ return $matches[1].ToLower() }; return $null }

$groups=Import-Csv "$dataDir\wa_groups.csv"; $byId=@{};$byName=@{}
foreach($g in $groups){ $i=ExId $g.name; if($i){$byId[$i]=$g}; $nn=Norm $g.name; if($nn -and -not $byName.ContainsKey($nn)){$byName[$nn]=$g} }

function PullMsgs($groupId,$startDt,$endDt){
  $msgs=@();$c=$null;$cid=$null
  while($true){
    $q="group_id=$groupId&limit=1000&order=desc"; if($c){$q+="&cursor=$([uri]::EscapeDataString($c))&cursor_id=$cid"}
    try { $r=Invoke-RestMethod -Uri "$URL/messages`?$q" -Headers $hh -TimeoutSec 90 } catch { break }
    if(-not $r.data){break}
    $stop=$false
    foreach($m in $r.data){ $rt=[datetime]$m.received_at; if($rt -lt $startDt){$stop=$true;break}; if($rt -le $endDt){ $msgs+=$m } }
    if($stop -or -not $r.next_cursor -or @($r.data).Count -eq 0){break}
    $c=$r.next_cursor;$cid=$r.next_cursor_id
  }
  return $msgs
}

function GroupSignals($grp,$endDate){
  # Janela corrigida: ancora o INÍCIO em max(churn-90d, primeira mensagem do grupo)
  # para nao confundir 'ausencia de dados' (WhatsApp comeca ~abr/2026) com 'silencio'.
  $end=[datetime]$endDate; $start=$end.AddDays(-90)
  $msgs=PullMsgs $grp.id $start $end
  $res=[ordered]@{ n=$msgs.Count; n_cli=0; n_eq=0; cli_share=0; init_h1=0; init_h2=0; len_h1=0; len_h2=0; lat_cli_h=0; chars=0; span_days=0 }
  if($msgs.Count -eq 0){ return $res }
  $sorted=$msgs | Sort-Object { [datetime]$_.received_at }
  $dataStart=[datetime]$sorted[0].received_at
  $mid=$dataStart.AddSeconds(($end-$dataStart).TotalSeconds/2)   # metade do periodo COM dados
  $res.span_days=[math]::Round(($end-$dataStart).TotalDays,0)
  $lh1=@();$lh2=@();$lat=@();$prevTeam=$null
  foreach($m in $sorted){
    $isTeam = ($m.sender_name -match 'INTEGRACOMM')
    $txt = if($m.message_text){$m.message_text}elseif($m.audio_transcription){$m.audio_transcription}else{''}
    $res.chars += $txt.Length
    $rt=[datetime]$m.received_at
    if($isTeam){ $res.n_eq++; $prevTeam=$rt }
    else {
      $res.n_cli++
      if($rt -lt $mid){ $res.init_h1++; $lh1+=$txt.Length } else { $res.init_h2++; $lh2+=$txt.Length }
      if($prevTeam){ $gap=($rt-$prevTeam).TotalHours; if($gap -ge 0 -and $gap -le 168){ $lat+=$gap }; $prevTeam=$null }
    }
  }
  $res.cli_share = if($res.n){[math]::Round($res.n_cli/$res.n,3)}else{0}
  $res.len_h1 = if($lh1.Count){[math]::Round(($lh1|Measure-Object -Average).Average,0)}else{0}
  $res.len_h2 = if($lh2.Count){[math]::Round(($lh2|Measure-Object -Average).Average,0)}else{0}
  $res.lat_cli_h = if($lat.Count){[math]::Round(($lat|Measure-Object -Average).Average,1)}else{-1}
  return $res
}

# Casos com sinal (re-match p/ obter o grupo)
$cases=Import-Csv "$dataDir\cases_expanded.csv" | Where-Object { [int]$_.dias -gt 0 }
$ctrlAll=Import-Csv "$dataDir\controls_active_bundles.csv"
$ctrlSample = $ctrlAll | Sort-Object { Get-Random } | Select-Object -First 45   # amostra de controle

$out=@()
foreach($c in $cases){ $g=$null;$i=ExId $c.cliente; if($i -and $byId.ContainsKey($i)){$g=$byId[$i]}elseif($byName.ContainsKey((Norm $c.cliente))){$g=$byName[(Norm $c.cliente)]}; if(-not $g){continue}; $s=GroupSignals $g $c.date; $row=[pscustomobject]($s + @{cohort='caso';cliente=$c.cliente}); $out+=$row }
foreach($c in $ctrlSample){ $g=$byName[(Norm $c.cliente)]; if(-not $g){continue}; $s=GroupSignals $g $c.date; $row=[pscustomobject]($s + @{cohort='controle';cliente=$c.cliente}); $out+=$row }
$out | Export-Csv "$dataDir\signals_3a.csv" -NoTypeInformation -Encoding UTF8

function Avg($rows,$prop){ $v=@($rows | Where-Object{ $_.$prop -ne $null } | ForEach-Object{ [double]$_.$prop }); if($v.Count){[math]::Round(($v|Measure-Object -Average).Average,2)}else{0} }
$ca=$out|Where-Object{$_.cohort -eq 'caso'}; $co=$out|Where-Object{$_.cohort -eq 'controle'}
"=== 3a SINAIS ESTRUTURAIS - JANELA CORRIGIDA (caso n=$($ca.Count) vs controle n=$($co.Count)) ==="
"span de dados disponivel (dias):           casos=$(Avg $ca 'span_days')  controle=$(Avg $co 'span_days')"
"cliente_share (msgs do cliente / total):  casos=$(Avg $ca 'cli_share')  controle=$(Avg $co 'cli_share')"
"iniciativa cliente metade1 -> metade2:     casos=$(Avg $ca 'init_h1')->$(Avg $ca 'init_h2')  controle=$(Avg $co 'init_h1')->$(Avg $co 'init_h2')"
"compr. msg cliente metade1 -> metade2:     casos=$(Avg $ca 'len_h1')->$(Avg $ca 'len_h2')  controle=$(Avg $co 'len_h1')->$(Avg $co 'len_h2')"
"latencia resposta cliente (horas):         casos=$(Avg $ca 'lat_cli_h')  controle=$(Avg $co 'lat_cli_h')"
$totalChars=($out|Measure-Object chars -Sum).Sum
"--- VOLUME p/ 3b: total chars (cliente+equipe) nas janelas = $totalChars  (~$([math]::Round($totalChars/4)) tokens) sobre $($out.Count) grupos ---"