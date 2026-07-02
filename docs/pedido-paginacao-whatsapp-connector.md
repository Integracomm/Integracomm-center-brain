# Pedido técnico — paginação por `group_id` na edge function `growth-agent-read`

**Para:** time que mantém o WhatsApp Connector (Lovable Cloud, projeto `mjqlcwtmesghotdaykvp`)
**De:** ferramenta de IA / agente de Growth (consumidor read-only)
**Endpoint:** `growth-agent-read/messages`

## Problema
O endpoint `/messages` aceita `group_id` **só na 1ª página e com `limit` pequeno**. Combinando `group_id` com paginação por cursor, ou com `limit` ≥ ~100, a resposta volta **HTTP 546**:

| Requisição | Resultado |
|---|---|
| `/messages?group_id=X&limit=50` | 200 ✅ (1ª página) |
| `/messages?group_id=X&limit=50&cursor=...&cursor_id=...` | **546** ❌ (2ª página) |
| `/messages?group_id=X&limit=100` | **546** ❌ |
| `/messages?limit=500` (sem group_id) | 200 ✅, mas cap de 500/página e ~24 MB/página |

Consequência: para ler o histórico de **um** grupo, ou só pego as ~50 mensagens mais recentes (sem paginar), ou teria que baixar a tabela inteira sem filtro (gigabytes). Isso impede extrair os sinais de relacionamento por conta (frequência/comprimento das mensagens) com a janela completa.

## O que precisamos
Suportar **`group_id` + paginação por cursor**, com o mesmo envelope que o caminho sem filtro já usa:

**Request (query params):**
- `group_id` (uuid) — filtro
- `limit` (int, permitir até 1000)
- `order` (`asc`|`desc`)
- `cursor` (timestamp `received_at` da última linha da página anterior)
- `cursor_id` (uuid `id`, desempate)

**Response (igual ao atual):**
```json
{ "data": [...], "next_cursor": "...", "next_cursor_id": "...", "count": N }
```

## Sugestão de implementação (keyset pagination)
A query deve filtrar por grupo e paginar por chave composta `(received_at, id)`:

```sql
SELECT id, group_id, sender_name, sender_phone, message_text,
       message_type, audio_transcription, received_at
FROM messages
WHERE group_id = $group_id
  AND ($cursor IS NULL OR (received_at, id) < ($cursor, $cursor_id))  -- '<' p/ order=desc
ORDER BY received_at DESC, id DESC
LIMIT $limit;
```

Provável causa do 546 hoje: sem índice adequado, a query com `group_id` + cursor faz scan/timeout. Recomendado:

```sql
CREATE INDEX IF NOT EXISTS idx_messages_group_received
  ON public.messages (group_id, received_at DESC, id DESC);
```

## Aceite
- `/messages?group_id=X&limit=1000&order=desc` → 200.
- Encadear `cursor`/`cursor_id` da resposta percorre **todo** o histórico do grupo sem 546.
- Sem mudança de contrato/segurança (continua read-only, mesma auth `x-api-key`).
