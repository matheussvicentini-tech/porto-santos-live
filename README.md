# Porto Santos Live — produção

## Fontes
O coletor consulta as páginas públicas da Autoridade Portuária de Santos (APS):
- Esperados — Carga
- Esperados — Passageiros
- Atracações Programadas
- Atracados — Porto/Terminais
- Fundeados

Também consulta a Lista de Atracação da Santos Brasil.

## Deploy
1. Suba esta pasta em um repositório GitHub.
2. No Render: New > Blueprint e selecione o repositório.
3. O render.yaml cria o Web Service e o PostgreSQL.
4. Configure no Render:
   - VAPID_PUBLIC_KEY
   - VAPID_PRIVATE_KEY
   - VAPID_SUBJECT (ex.: mailto:seuemail@dominio.com)

Gere as chaves VAPID com:
npx web-push generate-vapid-keys

## Atualização
O servidor coleta as fontes a cada 60 segundos. O painel também consulta a API a cada 60 segundos.

## Observação
As páginas públicas podem mudar sua estrutura. O parser é deliberadamente tolerante, mas deve ser monitorado pelo endpoint /api/health.
