# Operação — atualizar e o que desativar

## Atualizar o app em produção

Da raiz do projeto local, com o código já commitado:

```powershell
.\deploy.cmd
```

(wrapper de `deploy\deploy.ps1`.) Empacota o `HEAD` do git, envia por `scp` e
roda `docker compose up -d --build` no servidor AWS. Não mexe em `.env` nem
no banco.

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
