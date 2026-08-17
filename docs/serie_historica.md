# Série histórica mensal

Como cada mês vira um ponto da série sem que a coleta seguinte o apague.

O funcionamento está no cabeçalho de `src/pipeline/serie_historica.py`. Este
documento é o procedimento.

## A regra

**Feche o mês antes de coletar o próximo.**

```
python scripts/fechar_competencia.py 2026-08            # diagnóstico
python scripts/fechar_competencia.py 2026-08 --aplicar  # fecha
# só então rodar a coleta de setembro
```

O script sem `--aplicar` só diagnostica. Sem argumento nenhum, mostra o
panorama: o que há na base ativa e o que já virou série.

## Por que isso é obrigatório

`anuncios` é o retrato do mercado **agora**, e o upsert é destrutivo:

```sql
ON CONFLICT (fonte, url) DO UPDATE SET preco = EXCLUDED.preco, ...
```

Todo anúncio que continuar no ar tem o preço do mês anterior substituído, sem
cópia. Coletar setembro sem ter fechado agosto torna o índice de agosto
irreproduzível.

Há um segundo problema, menos óbvio: **a coleta nunca apaga**. Anúncio que
saiu do ar fica na base com a `ultima_vista` velha e continua entrando nas
estatísticas do mês seguinte como se estivesse vivo. Antes do primeiro
fechamento havia 82 anúncios de junho ainda pesando nos números publicados
como julho.

## O que "fechar" faz

1. Copia pro `anuncios_snapshot` os anúncios **vistos na competência**, com o
   registro cru — preço, título, url, tudo.
2. Apaga da base ativa os que **não** foram vistos. Eles continuam nos
   snapshots dos meses em que existiram.

A competência de um anúncio é a **`ultima_vista`**, não a data em que o
script rodou: uma coleta atravessa dias (julho teve lote em 14 e em 23) e
pode ser refeita semanas depois.

## Por que guardar o anúncio cru

São ~33 mil linhas por mês, o que é nada pro Postgres, e compra o que o
agregado não compraria: **recalcular o índice de qualquer mês passado**
quando a curva for recalibrada ou a curadoria do catálogo avançar. Guardando
só médias, cada mês ficaria congelado com a fórmula vigente na época.

## A trava da fonte não coletada

Apagar "tudo que não foi visto" destruiria uma fonte inteira que simplesmente
não foi coletada no mês — coletar só a OLX em agosto varreria os 5 mil
anúncios da Webmotors.

A purga é restrita às fontes que **têm** anúncio na competência. Fonte sem
nenhum não foi coletada, fica intacta, e o diagnóstico a reporta em
"INTOCADAS". Vale conferir essa lista a cada fechamento: fonte que aparece
ali é fonte que a coleta esqueceu.

## Fechar duas vezes

É erro, de propósito. A segunda passada aconteceria depois de uma coleta nova
ter mexido nos preços, e sobrescreveria o mês em silêncio com números que já
não são os daquele mês. `--refazer` força, quando é isso mesmo que se quer.

`reabrir()` apaga um snapshot, para corrigir um fechamento feito com a
competência errada. **Não devolve à base ativa o que foi purgado** — aquilo
era anúncio morto, e voltar a contá-lo refaria o problema.

## Histórico

**2026-07 fechada em 2026-08-17**: 33.266 anúncios no snapshot, 82 removidos
da base ativa (sobra de junho, toda de loja especializada). O índice
publicado não se moveu — mediana de mercado R$ 32.900 sobre 31.593 anúncios
generalistas e valor de coleção R$ 52.894, idênticos antes e depois, porque a
curva lê apenas fontes generalistas e nenhum dos 82 era de marketplace.

## O que ainda não existe

Ler a série de volta. Os snapshots estão gravados, mas nada no painel nem no
site compara dois meses ainda — o dashboard e a exportação continuam olhando
só a base ativa. É o próximo passo, e agora dá pra fazer sem pressa: o dado
está guardado.

Há também uma tabela `historico_precos` no schema, com `upsert_preco()`, que
nunca foi ligada ao pipeline e está vazia. Ela é de um desenho anterior
(agregado por marca/modelo/ano, sem versão) e foi substituída por esta série.
