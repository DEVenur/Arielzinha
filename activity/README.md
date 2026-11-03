# Web Player — Discord Activity

A Activity é servida em `/activity/` pelo mesmo servidor HTTP do projeto. As rotas RPC existentes (`/` e `/ws`) são preservadas.

## Configuração

Defina estas variáveis no ambiente do bot:

- `DISCORD_CLIENT_ID`: Application ID da aplicação Discord configurada para a Activity.
- `DISCORD_CLIENT_SECRET`: OAuth2 Client Secret dessa aplicação. Mantenha-o apenas no backend.
- `ACTIVITY_SESSION_SECRET`: segredo aleatório persistente para assinar o cookie de sessão. Gere com `python -c "import secrets; print(secrets.token_urlsafe(48))"`.

No Discord Developer Portal, configure a URL pública da Activity e habilite os escopos OAuth2 `identify` e `guilds`. O cliente usa o Embedded App SDK 2.5.0.

## Estado desta primeira etapa

- Inicialização do Embedded App SDK e autenticação OAuth2.
- Troca do código OAuth no backend e validação da identidade com a API do Discord.
- Cookie de sessão HttpOnly, Secure e SameSite=None; o token OAuth só é devolvido ao SDK no navegador para concluir `authenticate()`.
- API de leitura dos servidores em comum com os bots e do estado atual dos players.
- Nenhum comando de reprodução ou streaming é exposto nesta etapa.

O streaming não é encaminhado pelo Lavalink nesta implementação. Será necessário projetar uma saída de áudio própria antes de disponibilizar reprodução no navegador.
