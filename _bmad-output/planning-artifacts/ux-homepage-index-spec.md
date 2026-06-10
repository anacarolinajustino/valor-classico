---
title: "UX Spec - Homepage e Index"
status: draft
created: 2026-05-29
updated: 2026-05-29
---

# UX Direction para Homepage (Valor Classico)

## Base visual observada no site atual

1. Identidade principal em preto/branco com acento verde-lima.
2. Hero com fotografia escura de carros antigos.
3. Tipografia de navegacao condensada e forte.
4. Mensagem emocional: "Carro antigo nao tem preco, tem Valor."

## Benchmark funcional observado (site Netlify com busca)

Elementos validos observados:

1. Fluxo de filtros encadeado: Marca -> Modelo -> Ano.
2. Campos dependentes iniciam desabilitados, reduzindo erro de preenchimento.
3. Botao "Limpar" para reset rapido da consulta.
4. Mensagem de estado vazio quando ainda nao ha filtros suficientes.

Pontos a evoluir na nova versao:

1. Alinhar nomenclatura de navegacao com marca Valor Classico (evitar labels desalinhadas).
2. Reforcar identidade visual da marca (verde-lima + logo atual).
3. Melhorar hierarquia visual da primeira dobra com CTA principal unico.
4. Exibir confianca da amostra e fontes usadas ja no bloco de resultado.

## Direcao recomendada

Manter DNA visual atual, mas com uma homepage mais orientada a produto e busca.

1. Manter verde-lima como cor de acento (CTA e indicadores).
2. Manter base neutra (preto/grafite/branco) para contraste.
3. Usar tipografia de titulo com personalidade vintage e corpo legivel.
4. Tornar a busca o centro da primeira dobra (above the fold).

## Tokens visuais (primeira versao)

### Cores

1. `--vc-accent: #72E05A` (verde-lima principal)
2. `--vc-accent-strong: #56C744` (hover/ativo)
3. `--vc-ink: #121212` (texto principal)
4. `--vc-ink-soft: #2F2F2F` (texto secundario)
5. `--vc-surface: #F5F5F5` (fundos claros)
6. `--vc-surface-dark: #1A1A1A` (blocos escuros)
7. `--vc-border: #D9D9D9` (linhas)

### Tipografia sugerida

1. Titulos/labels: Teko (ou equivalente condensada).
2. Frase de impacto: Playfair Display Italic (ou equivalente serifada).
3. Corpo/inputs: Inter ou Source Sans 3.

## Objetivo da homepage (MVP)

1. Usuario entende a proposta em 5 segundos.
2. Usuario inicia busca por modelo e ano sem friccao.
3. Usuario ve exemplo de resultado e entende a confianca da amostra.

## Estrutura recomendada de index.html

### 1. Header fixo

1. Logo no canto esquerdo.
2. Links: "Como funciona", "Fontes", "Contato".
3. Botao secundario: "Falar no WhatsApp".

### 2. Hero de produto

1. Frase principal com DNA atual.
2. Subtitulo objetivo: referencia de valor para carros antigos.
3. Card de busca no centro:
   - Campo marca/modelo (autocomplete)
   - Campo ano
   - Botao "Calcular media"
   - Botao secundario "Limpar"
4. Linha de confianca: "Baseado em anuncios reais de fontes especializadas".

### 3. Bloco "Como calculamos"

1. Coleta multi-fonte.
2. Limpeza e deduplicacao.
3. Media + mediana + faixa.
4. Score de confianca.

### 4. Bloco "Fontes"

1. Lista visual das fontes ativas por fase (portal-first no inicio).
2. Tag de status por fonte: ativa, parcial, planejada.

### 5. Bloco "Exemplo real"

1. Exemplo de consulta (ex.: Palio 2008).
2. Resultado simulado com:
   - preco medio
   - mediana
   - faixa tipica
   - tamanho da amostra
   - ultima atualizacao

### 6. Bloco "Para quem"

1. Colecionadores.
2. Lojistas.
3. Investidores em antigos.
4. Seguradoras e parceiros B2B.

### 7. Footer

1. Contato (telefone e e-mail).
2. CNPJ/razao social.
3. Direitos reservados.

## Estrutura semantica de HTML (ids sugeridos)

1. `#top-header`
2. `#hero-search`
3. `#how-it-works`
4. `#data-sources`
5. `#result-sample`
6. `#segments`
7. `#footer`

## Decisao de UX para inicio

1. O index deve ser landing + ferramenta de busca no mesmo arquivo na V1.
2. O foco da primeira dobra e converter para a acao de busca.
3. O visual deve preservar a identidade atual e evoluir em clareza de produto.
4. O fluxo de busca inicial sera encadeado (Marca -> Modelo -> Ano), com habilitacao progressiva dos campos.
5. Deve existir estado vazio explicito (ex.: "Selecione marca e modelo para ver resultado").

## Checklist de pronto do index (MVP)

1. Responsivo em mobile e desktop.
2. Contraste minimo AA para textos sobre imagens.
3. Fluxo de busca funcional com validacao.
4. Exibicao de loading, erro e vazio.
5. Bloco de confianca sempre visivel no resultado.
