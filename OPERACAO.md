# Operação — atualizar e o que desativar

## Atualizar o app em produção

Da raiz do projeto local, com o código já commitado:

```powershell
.\deploy.cmd
```

(wrapper de `deploy\deploy.ps1`.) Empacota o `HEAD` do git, envia por `scp` e
roda `docker compose up -d --build` no servidor AWS. Não mexe em `.env` nem
no banco.

### Deploy de outra máquina/pessoa

Não precisa de conta própria na AWS pra rodar `deploy.cmd` — só pra
**administrar** a instância (ver IP, mexer no firewall, reiniciar, criar
chave nova) é que precisaria de login no console Lightsail.

Como funciona a chave: o `.pem` é a chave **privada** de SSH e **nunca fica
no servidor** — só a chave **pública** correspondente fica lá (em
`~/.ssh/authorized_keys` do usuário `ubuntu`), instalada pela AWS quando a
instância foi criada com a chave "default" da região. Ou seja, **cada
pessoa/máquina que for rodar `deploy.cmd` precisa ter uma cópia do arquivo
`.pem`** — sem ele, `scp`/`ssh` não autentica.

Pré-requisitos pra outra pessoa/máquina rodar o deploy:
1. Clonar o repositório (git).
2. Ter OpenSSH client instalado (`ssh`/`scp` no PATH — já vem por padrão no
   Windows 10/11).
3. Colocar o `lightsail.pem` em `Downloads\lightsail.pem` (ou passar
   `-KeyPath` customizado pro `deploy\deploy.ps1`) — copiado por canal
   seguro de quem já tem, nunca por e-mail/Slack aberto.
4. Rodar `.\deploy.cmd` na raiz do projeto.

Sem conta AWS própria, essa pessoa só **não consegue** administrar a
instância (console Lightsail, firewall, resize etc.) — o deploy de código via
SSH funciona normalmente com o `.pem`.

---

## O que desativar (e como)

O app **não pode rodar local e em produção ao mesmo tempo** — duplica a
rodada diária e o relatório no Slack. Rodando em produção (AWS), desative as
tarefas agendadas locais do Windows (se existirem — foram criadas por
`setup_tasks.ps1`; em máquinas onde nunca rodou esse script, os comandos
abaixo dão erro "não existe no sistema" porque não há nada a desativar):

```powershell
schtasks /Change /TN "IntegracommIA-RodadaDiaria" /DISABLE
schtasks /Change /TN "IntegracommIA-Painel" /DISABLE
```

- `IntegracommIA-Painel` — sobe o uvicorn local (`localhost:8000`) no boot.
- `IntegracommIA-RodadaDiaria` — roda a carteira completa + envia relatório
  ao Slack, todo dia às 08:10.

Conferir se estão desativadas:

```powershell
schtasks /Query /TN "IntegracommIA-RodadaDiaria" /V /FO LIST
schtasks /Query /TN "IntegracommIA-Painel" /V /FO LIST
```

(campo `Status` deve mostrar `Disabled`.)

Para voltar a rodar local (ex.: debug), reative as tarefas e **pare o app em
produção** para não duplicar de novo:

```powershell
schtasks /Change /TN "IntegracommIA-RodadaDiaria" /ENABLE
schtasks /Change /TN "IntegracommIA-Painel" /ENABLE
```
