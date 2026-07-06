# Deploy na AWS — passo a passo (≈30 min)

Arquitetura: **1 instância Lightsail** (Ubuntu 24.04) rodando Docker Compose com
3 serviços — app (FastAPI), Postgres 18 e Caddy (HTTPS automático via Let's
Encrypt). Rodada diária das 06:00 + checagem NPS do dia 2 via cron do servidor.
Custo: ~US$ 12/mês (plano 2 GB RAM; o de 1 GB fica apertado para o build).

## 1. Criar a instância (console AWS)
1. <https://lightsail.aws.amazon.com> → **Create instance**.
2. Região: **São Paulo (sa-east-1)** · Plataforma: **Linux** · Blueprint: **Ubuntu 24.04 LTS**.
3. Plano: **US$ 12 (2 GB RAM / 2 vCPU / 60 GB)**.
4. Nome: `integracomm-ia` → **Create instance**.
5. Aba **Networking** da instância:
   - **Attach static IP** (grátis enquanto anexado) — anote o IP.
   - **Firewall**: adicionar regra **HTTPS (443)** (HTTP 80 e SSH 22 já vêm).

## 2. Apontar o domínio
No seu provedor de DNS, crie um registro **A**:
```
ia.integracomm.com.br  →  <IP estático da instância>
```
(qualquer subdomínio serve; anote o que escolher.)

## 3. Montar o pacote (na máquina ONDE RODA O SISTEMA HOJE)
```powershell
cd "C:\Users\USUARIO\Desktop\Nova aplicação Integracomm"
powershell -ExecutionPolicy Bypass -File deploy\make_bundle.ps1
```
Gera `Downloads\integracomm_bundle.tar.gz` — pacote **autossuficiente**: código
(versão commitada no git) + dump do banco + caches (`data/`) + `.env` do
servidor com segredos novos. Só esta máquina consegue gerá-lo (o banco e o
`.env` vivem aqui).

> **Deploy a partir de OUTRA máquina?** Basta transferir esse único arquivo
> para ela (drive, pendrive etc.) e seguir os passos 4-5 de lá — o git não é
> necessário na máquina de deploy (e o bundle carrega o que o git de propósito
> NÃO tem: segredos, dump e caches). Dica: gere o bundle no DIA do deploy para
> o banco migrar com os dados mais recentes.

## 4. Enviar ao servidor
Baixe a chave SSH da instância (console Lightsail → Account → SSH keys → default da região) para `Downloads\lightsail.pem`, então:
```powershell
cd $env:USERPROFILE\Downloads
scp -i lightsail.pem integracomm_bundle.tar.gz ubuntu@<IP>:/tmp/
ssh -i lightsail.pem ubuntu@<IP>
```

## 5. No servidor: extrair, configurar domínio e subir
```bash
sudo mkdir -p /opt/integracomm && sudo chown ubuntu /opt/integracomm
tar -xzf /tmp/integracomm_bundle.tar.gz -C /opt/integracomm
cd /opt/integracomm
nano .env        # preencha a 1ª linha: DOMAIN=ia.integracomm.com.br
sudo bash deploy/bootstrap.sh
```
O bootstrap instala o Docker, sobe os 3 serviços, restaura o banco local,
instala o cron das 06:00 e faz um smoke test. Ao final, acesse
**https://ia.integracomm.com.br** (1º acesso emite o certificado, ~30 s).

## 6. Validar
- Login admin: `adm@integracomm.com.br` + a MESMA senha do painel local.
- Tela de login → **Criar sua conta** (fluxo dos gestores) → a conta aparece
  **pendente** no hub do admin → aprovar → gestor entra.
- Relatório individual de um cliente (1ª geração pós-boot leva ~2 min até o
  cache do ClickUp aquecer; depois 1-2 s).

## 7. Desativar as tarefas locais (evita relatório DUPLICADO no Slack)
No seu Windows, PowerShell **como administrador**:
```powershell
schtasks /Change /TN "IntegracommIA-RodadaDiaria" /DISABLE
schtasks /Change /TN "IntegracommIA-Painel" /DISABLE
```
(Para voltar ao local um dia: `/ENABLE`.)

## Operação
| tarefa | comando (no servidor, em /opt/integracomm) |
|---|---|
| ver serviços | `docker compose -f deploy/docker-compose.yml ps` |
| logs do app | `docker compose -f deploy/docker-compose.yml logs -f app` |
| log da rodada diária | `tail -100 logs/cron_diario.log` |
| reiniciar | `docker compose -f deploy/docker-compose.yml restart app` |
| atualizar código | novo bundle → extrair por cima → `up -d --build` |
| rodada manual agora | `docker compose -f deploy/docker-compose.yml exec -T app sh /app/deploy/daily_run.sh` |
| backup do banco | `docker compose -f deploy/docker-compose.yml exec -T db pg_dump -U integracomm_app -Fc integracomm_ia > backup_$(date +%F).dump` |

## Segurança (fica registrado)
- Senhas dos gestores: hash bcrypt no banco; contas nascem pendentes; rate-limit
  de login (5 falhas/5 min). Cookie de sessão `secure` + httponly sob HTTPS.
- O `.env` do servidor carrega os MESMOS tokens read-only do local (ClickUp,
  WhatsApp, Slack). Depois que o piloto validar, rotacionar os tokens
  (pendência já registrada) — trocar no `.env` do servidor e `restart app`.
- Banco não é exposto na internet (sem porta publicada; só a rede interna do
  compose). SSH só por chave.
