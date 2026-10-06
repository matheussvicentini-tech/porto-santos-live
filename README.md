# Porto de Santos — versão gratuita com atualização automática

## O que foi preparado
- Site estático em `public/index.html`
- Dados em `public/navios.json`
- Coletor em `scripts/update_navios.py`
- GitHub Actions em `.github/workflows/atualizar.yml`
- Atualização programada a cada 5 minutos
- Favoritos salvos no navegador
- Notificações do navegador quando a página estiver aberta e detectar alteração

As fontes incluem as páginas públicas da Autoridade Portuária de Santos para navios esperados, atracações programadas, atracados e fundeados, além da lista pública de atracação da Santos Brasil.

## Como publicar gratuitamente

1. Crie um repositório GitHub chamado `porto-santos-live`.
2. Envie TODOS os arquivos desta pasta, mantendo a estrutura:
   - `.github/workflows/atualizar.yml`
   - `public/index.html`
   - `public/navios.json`
   - `public/atualizacao.json`
   - `requirements.txt`
   - `scripts/update_navios.py`
   - `README.md`
3. No GitHub, abra **Actions** e execute `Atualizar navios do Porto de Santos` manualmente uma vez.
4. Depois vá em **Settings > Pages**.
5. Em **Build and deployment**, selecione **Deploy from a branch**.
6. Escolha `main` e a pasta `/public`.
7. Salve. O GitHub fornecerá o endereço do site.
8. A Action continuará atualizando `navios.json` a cada 5 minutos.

## Observação importante
O GitHub pode atrasar execuções agendadas; portanto, “5 minutos” é o intervalo programado, não uma garantia de atualização exatamente a cada 5 minutos.

Também há uma diferença entre “atualizar o site” e “notificação push”. Nesta versão gratuita, as notificações do navegador funcionam quando o usuário mantém o site aberto. Push em segundo plano, inclusive com o navegador fechado, exige uma infraestrutura adicional de notificações.

## Fontes
- Autoridade Portuária de Santos: https://www.portodesantos.com.br/informacoes-operacionais/operacoes-portuarias/navegacao-e-movimento-de-navios/
- Santos Brasil: https://www.santosbrasil.com.br/v2021/lista-de-atracacao
