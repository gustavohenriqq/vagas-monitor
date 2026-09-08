# Logos das plataformas

Cada arquivo é a marca da plataforma de onde as vagas vêm, usada para
identificar a origem de cada anúncio no painel. Estão versionados aqui em vez
de carregados do site de origem: apontar para fora criaria dependência de rede
a cada visita e vazaria um referer do visitante para terceiros.

| Arquivo | Origem | Observação |
|---|---|---|
| `greenhouse.svg` | [Simple Icons](https://simpleicons.org) | CC0 |
| `workday.svg` | [Wikimedia Commons](https://commons.wikimedia.org/wiki/File:Workday_2024_logo.svg) | domínio público |
| `gupy.svg` | gupy.io | marca da própria plataforma |
| `inhire.svg` | inhire.com.br | marca da própria plataforma |
| `recrutei.svg` | recrutei.com.br | marca da própria plataforma |
| `lever.svg` | jobs.lever.co | marca da própria plataforma |
| `ashby.svg` | ashbyhq.com | marca da própria plataforma |
| `remotive.svg` | remotive.com | marca da própria plataforma |
| `wwr.svg` | weworkremotely.com | marca da própria plataforma |
| `recruitee.svg` | recruitee.com | é a marca da **Tellent**, que comprou a Recruitee |
| `smartrecruiters.svg` | smartrecruiters.com | lockup **SmartRecruiters + SAP**, que a comprou em set/2025; o site deles só publica essa versão |

## Ajustes aplicados

- **`width` e `height` na raiz de todos.** Sem dimensão intrínseca, o `<img>`
  conhece só a proporção e o navegador parte do tamanho padrão de 300×150
  antes de aplicar os limites do CSS — foi o que fazia o Ashby estourar o card.
- **`viewBox` do Ashby** vinha em minúsculas. Em HTML o navegador tolera, mas
  num `.svg` externo, que é XML, o nome do atributo diferencia maiúsculas.
- **Cor.** Os monocromáticos escuros (`wwr`, `inhire`, `greenhouse`, `lever`)
  são forçados a branco por filtro CSS, senão sumiriam no fundo preto. Os
  coloridos ficam na cor original — inverter mataria a identidade da marca, e
  os que têm fundo próprio virariam um bloco branco sólido.

As marcas pertencem às respectivas empresas. O uso aqui é apenas para
identificar a fonte de cada vaga.
