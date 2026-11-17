[English](README.md) | Português

# exam-pdf-parser

[![CI](https://github.com/ErickBonruque/exam-pdf-parser/actions/workflows/ci.yml/badge.svg)](https://github.com/ErickBonruque/exam-pdf-parser/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.12%20%7C%203.13-blue)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

Extrai questões de múltipla escolha de PDFs de provas (enunciado, alternativas A–E, área, gabarito)
para Parquet ou JSONL com esquema validado. Medido contra os dados oficiais: 3.700 questões do ENEM
de 2020 a 2024.

## Resultado

40 cadernos do ENEM (5 anos × 8 cadernos regulares), comparados com os microdados do INEP
(`ITENS_PROVA`), que são uma fonte independente do PDF:

| Medida | Resultado |
|---|---|
| Questões encontradas (número + idioma) | 3.700 / 3.700 (100%) |
| Questões a mais | 0 |
| Área certa (LC, CH, CN, MT) | 100% |
| As 5 alternativas localizadas | 100% |
| Gabarito igual ao oficial | 3.676 / 3.676 (100%) |
| Anuladas detectadas | 24 / 24 |
| Texto legível (sem glifo perdido) | 95,6% |
| Mesmo texto do item nas 4 cores do caderno | 875 / 925 itens (94,6%) |
| Tempo / pico de memória | 93 s com 4 processos / 320 MB |

A última linha mede a qualidade do texto sem gabarito de texto: o mesmo item aparece nas 4 cores
em posições diferentes da página, então um extrator bom lê o mesmo texto nas 4.

Com a saída em Parquet, uma consulta DuckDB mostra que nenhuma letra é favorecida no gabarito:

```sql
SELECT substr(exam_id, 6, 4) AS ano, count(*) AS questoes,
       round(100 * avg((answer = 'A')::int), 1) AS "A", ...
FROM 'data/out/*.parquet' GROUP BY 1 ORDER BY 1;
```

| Ano | Questões | A % | B % | C % | D % | E % |
|---|---|---|---|---|---|---|
| 2020 | 740 | 19,1 | 18,0 | 23,5 | 22,4 | 16,9 |
| 2021 | 740 | 18,5 | 25,0 | 19,6 | 20,1 | 16,8 |
| 2022 | 740 | 21,2 | 20,1 | 21,2 | 17,9 | 19,6 |
| 2023 | 740 | 25,0 | 19,0 | 20,7 | 19,0 | 16,3 |
| 2024 | 740 | 17,4 | 19,6 | 21,2 | 22,8 | 19,0 |

## Por que existe

Provas e gabaritos de concursos e do ENEM são publicados como PDF de duas colunas, feito para
imprimir. Para estudar incidência de assunto, montar banco de questões ou treinar modelo, é preciso
transformar isso em tabela, e conferir se a extração está certa.

## Como rodar

Requer Python 3.12+ e [uv](https://docs.astral.sh/uv/).

```bash
uv sync
uv run exam-pdf enem download --years 2024 --dest data/enem
uv run exam-pdf parse data/enem/2024_PV_impresso_D1_CD1.pdf \
    --answer-key data/enem/2024_GB_impresso_D1_CD1.pdf -o questions.parquet
```

Para reproduzir a tabela acima, baixe os microdados do ENEM no
[portal do INEP](https://www.gov.br/inep/pt-br/acesso-a-informacao/dados-abertos/microdados/enem)
(basta o ZIP; o arquivo `ITENS_PROVA` é lido de dentro dele) e rode:

```bash
uv run exam-pdf enem download --years 2020-2024 --dest data/enem
uv run exam-pdf enem evaluate --years 2020-2024 --pdf-dir data/enem \
    --microdata-dir caminho/dos/microdados --out-dir data/out
```

## Como funciona

```
PDF ─► layout ─────────► segment ───────────► parse ─────────► export
       palavras, fontes   cabeçalho "QUESTÃO"   + gabarito       Parquet / JSONL
       calha, linhas      seções (área, idioma) pydantic valida
       rodapé corrido     alternativas A–E
                                                 evaluate ◄── microdados INEP
```

- **`layout`**: lê as palavras com posição e fonte (`pdfplumber`), descarta marca d'água (texto de
  1 pt) e código de barras, acha a calha entre as colunas e monta as linhas em ordem de leitura.
  O rodapé corrido é achado por repetição (mesma altura na maioria das páginas), não por texto.
- **`segment`**: separa as questões pelos cabeçalhos e guarda o contexto das seções (área, opção de
  inglês ou espanhol). As letras A–E são reconhecidas pela fonte própria em que são desenhadas, então
  um enunciado que começa com "A" não vira alternativa. Alternativas em grade (A B C / D E) são
  reordenadas.
- **`glyphs`**: nos PDFs de 2021, a fonte embutida não traz a tabela Unicode de 1/3 a 3/4 dos
  caracteres, e o texto sai como `(cid:12)` ou com letra trocada. O módulo lê o nome de cada glifo
  (`g68`) e converte o índice em caractere pela ordem de glifos da Arial. A ordem foi conferida no
  próprio texto ("CARTÃO", "África", "conflito"). Fontes com ordem desconhecida (Symbol, Cambria)
  viram `�` e a questão ganha um aviso, em vez de letra errada.
- **`evaluate`**: acha o código do caderno (`CO_PROVA`) pela cor lida no gabarito e pelo dicionário
  dos microdados, e compara questão por questão.

Decisões:
- `pdfplumber` (MIT) e não PyMuPDF (AGPL), para o projeto poder ser MIT.
- Cada questão passa por um modelo `pydantic` antes de ser gravada (letras em ordem, resposta
  entre as alternativas, anulada sem resposta). O que não dá para extrair vai em `warnings`, sem parar
  o processamento.
- Nenhum PDF, gabarito ou saída fica no repositório. Os testes geram PDFs sintéticos com `reportlab`.

## Saída

Uma linha por questão:

| Coluna | Tipo | Exemplo |
|---|---|---|
| `exam_id` | string | `enem-2024-d2-cd5` |
| `number` | int16 | `136` |
| `language` | string | `en`, `es` ou nulo |
| `area` | string | `MT` |
| `stem` | string | texto de apoio + comando |
| `alternatives` | list<struct<letter, text>> | `[{A, "2 400,00."}, …]` |
| `answer` | string | `C` |
| `annulled` | bool | `false` |
| `pages` | list<int16> | `[16]` |
| `has_image` | bool | imagem raster dentro da questão |
| `warnings` | list<string> | `["alternative A is empty (image?)"]` |

## Limitações

- Texto dentro de figura e fórmula não é confiável: rótulos de gráfico se misturam, `√` e frações
  perdem a estrutura. 2,2% das questões têm alternativas que são só imagem (texto vazio, com aviso).
- `has_image` vê só imagem raster; figura vetorial não conta.
- Só o perfil do ENEM está pronto e medido. Provas de banca (FGV, Cebraspe) precisam de perfil
  próprio e de PDFs baixados à mão: os termos de uso da FGV proíbem acesso automatizado, e este
  projeto não baixa nada desses sites.
- 164 questões (4,4%) ainda têm algum glifo perdido: 108 de 2021 e o resto em outros anos, quase
  sempre símbolo de fórmula em fonte Symbol ou Cambria.

## Licença

MIT. Os PDFs e microdados são publicados pelo INEP; este repositório não os redistribui.
