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
| `smartrecruiters.svg` | smartrecruiters.com | recortado, ver abaixo |

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

## O recorte do SmartRecruiters

A SAP comprou a SmartRecruiters em setembro de 2025, e desde então o site
deles só publica o lockup conjunto — não há versão isolada (todos os caminhos
para uma dão 404). Como a SAP não é uma fonte que o monitor consulta, a linha
"An SAP company" foi removida do arquivo.

O recorte foi cirúrgico e verificável: medindo a extensão vertical de cada
traçado, os 15 primeiros formam o wordmark (y de 0,9 a 57,1) e o décimo sexto,
sozinho, desenha a linha do SAP (y de 72,4 a 105,8). Só ele saiu, e o
`viewBox` passou de 109 para 60 de altura. A proporção foi de 5,06 para 9,20,
o que moveu o logo para a faixa de tamanho `xwide` no painel.

Isso é alteração de marca de terceiro. O rótulo do card continua dizendo
"ATS corporativo · SAP", então a informação não se perde.

## Licença

As marcas pertencem às respectivas empresas. O uso aqui é apenas para
identificar a fonte de cada vaga.
