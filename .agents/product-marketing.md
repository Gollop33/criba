# Product Marketing Context

**Document version:** v1
**Last updated:** 2026-09-30

> Este documento es la base que leen TODAS las demás skills de marketing.
> Si cambia algo del posicionamiento, se actualiza aquí primero.

---

## Product Overview

**One-liner:** Ofertas do Mercado Livre e da Amazon com **preço conferido** — o único grupo onde o cupom que aparece é o cupom que aplica.

**What it does:** Um robô monitora Mercado Livre e Amazon 24 horas por dia, confere o preço real de cada produto contra a API oficial, e publica os achados no grupo do WhatsApp a cada 1-10 minutos. Também mantém um site com o catálogo completo, organizado por categoria.

**Product category:** Achadinhos / Ofertas / Cupons / Promoções (Brasil)

**Product type:** Canal de WhatsApp + site (modelo de afiliado)

**Business model:** Comissão de afiliado. Mercado Livre (tag `ja20250119201346`) e Amazon (tag `criba20-20`). O usuário não paga nada — o preço é o mesmo, a comissão vem da loja.

---

## Target Audience

**Target:** Consumidor brasileiro que compra online e quer pagar menos. B2C puro. Classe média e média-baixa, 25-55 anos, compra pelo celular, paga com Pix.

**Primary use case:** Quero comprar X mas não sei se o preço está bom, nem quero ficar procurando cupom em dez lugares.

**Jobs to be done:**
- "Quero saber se esse preço vale a pena ANTES de comprar"
- "Quero o cupom que funciona de verdade, não um que dá erro no checkout"
- "Quero ver as ofertas boas sem ter que garimpar sozinho"

**Use cases:**
- Comprar eletrodoméstico / celular / ferramenta com desconto real
- Presente de aniversário ou Natal com preço bom
- Repor item de casa (pet, limpeza, cozinha) quando aparece barato

---

## Personas

Produto B2C: não há múltiplos stakeholders na compra. Persona única:

| Persona | Cares about | Challenge | Value we promise |
|---------|-------------|-----------|------------------|
| Comprador do dia a dia | Pagar menos sem perder tempo | Não tem como saber se o cupom vai funcionar | Preço conferido + cupom que aplica |

---

## Problems & Pain Points

**Core problem:** Os grupos de ofertas do Brasil enchem o celular de posts, mas boa parte **mente**: preço desatualizado, cupom que não aplica, "Pix 5% OFF" que não existe no checkout. A pessoa perde tempo e se frustra.

**Why alternatives fall short:**
- Outros grupos publicam cupom **por categoria**, sem conferir se aquele produto está na lista de elegíveis. Resultado no checkout: *"Este cupom não se aplica a esta compra."*
- Publicam preço **scrapeado horas antes** e quando a pessoa clica já mudou
- Inventam desconto Pix em produto que não tem
- Repostam o mesmo produto em preço pior

**What it costs them:** Tempo (abrir dez links) e dinheiro (comprar achando que vai pagar R$ 809 e pagar R$ 1.216).

**Emotional tension:** Desconfiança. *"Será que esse preço é real mesmo?"* — e a raiva de ver o cupom dar erro na hora de fechar.

---

## Competitive Landscape

**Direct:** Outros canais de achadinhos (grupos de WhatsApp/Telegram, Pelando, Promobit) — falls short porque publicam em volume e sem conferir preço nem cupom.

**Secondary:** O próprio buscador do Mercado Livre / Amazon — falls short porque mostra preço de tabela e não avisa quando cai, e o cupom fica escondido.

**Indirect:** Não procurar e comprar no primeiro lugar que aparecer — falls short porque paga mais caro sem saber.

---

## Differentiation

**Key differentiators:**
- **Preço conferido contra a API oficial do Mercado Livre** antes de publicar — e corrigido se estiver diferente
- **Cupom só quando o Mercado Livre confirma** que aquele produto tem cupom (medido: só 14,5% têm)
- **Pix só quando existe desconto real** (medido: 28% dos produtos, de 5% a 26%)
- **Oferta morta é descartada** — se o produto saiu do ar, não vai pro grupo
- Publicação a cada 1-10 minutos, não 50 posts de uma vez

**How we do it differently:** Em vez de adivinhar, o robô **lê o que o próprio Mercado Livre publica** sobre cada produto (três preços: normal, com Pix, com cupom) e valida contra a API.

**Why that's better:** O preço que está no post é o preço que a pessoa paga no checkout. Verificado de ponta a ponta.

**Why customers choose us:** Porque podem conferir. Um canal que diz *"Com cupom: R$ 1076"* e a pessoa paga R$ 1.076,49 — isso vira confiança, e confiança vira recompra pelo link.

---

## Objections

| Objection | Response |
|-----------|----------|
| "Mais um grupo de ofertas? Já estou em cinco" | os cinco publicam cupom que dá erro. Aqui o preço é conferido antes de sair |
| "Será que o cupom funciona?" | o cupom só aparece quando o Mercado Livre confirma que aquele produto tem. Medimos: de 400 produtos, só 58 têm — e só esses são publicados |
| "Vai encher meu celular de mensagem?" | 1 post a cada 1 a 10 minutos, e cada um com produto diferente |
| "É golpe?" | o link é o oficial da loja, com tag de afiliado. O preço é o mesmo, a loja paga a comissão |

**Anti-persona:** quem procura produto muito específico e não pode esperar (o grupo não é buscador); quem não usa Pix (perde o maior desconto).

---

## Switching Dynamics

**Push:** Cansado de abrir link e o cupom dar erro. Cansado de preço que mudou.
**Pull:** Saber que o preço foi conferido, e que o cupom aplica.
**Habit:** Já está em outros grupos e não quer sair / não quer silenciar os outros.
**Anxiety:** Que seja mais um canal de spam. Que o link seja suspeito.

---

## Customer Language

**How they describe the problem:**
- "o cupom não aplica"
- "quando abri já tinha mudado o preço"
- "só quero saber se vale a pena"
- "esse preço tá bom?"

**How they describe us:**
- (a preencher com os primeiros comentários do grupo)

**Words to use:** achadinho, achado, promoção, cupom, Pix, frete grátis, vale a pena, verificado, conferido, baixou de preço

**Words to avoid:** jargão técnico (API, scrape, endpoint), "melhor preço do mercado" (promessa grande demais), "imperdível" em tudo (vira ruído)

**Glossary:**

| Term | Meaning |
|------|---------|
| Achadinho | Oferta boa encontrada, "achado" |
| Cupom | Código/campanha de desconto do Mercado Livre |
| Pix | Pagamento instantâneo; costuma ter desconto |
| BAJÓ DE PRECIO / BAIXOU | Mesmo produto republicado mais barato |
| Frete grátis | Envio sem custo (decide muita compra no Brasil) |

---

## Brand Voice

**Tone:** Direto, casual, brasileiro. Fala como amigo que entende de preço — não como loja.

**Style:** Frases curtas. Preço na frente. Zero enrolação.

**Personality:** Confiável, rápido, honesto.

**Regra absoluta:** **nunca inventar dado.** Se não dá pra conferir, não publica. Já custou caro: o bot já publicou cupom que não aplicava e Pix que não existia, e o usuário descobriu no checkout.

---

## Proof Points

**Metrics (medidos no sistema, 2026-09-30):**
- 478 ofertas no catálogo (Mercado Livre + Amazon)
- 12 categorias
- 28% dos produtos com desconto Pix real (5% a 26%)
- 14,5% com cupom confirmado pelo Mercado Livre
- Verificação de ponta a ponta contra o checkout real: post dizia `Com cupom: R$ 1076` e o Mercado Livre cobrou **R$ 1.076,49**

**Value themes:**

| Theme | Proof |
|-------|-------|
| Preço é real | conferido contra a API antes de cada publicação |
| Cupom aplica | só publica se o ML confirmar que o produto tem cupom |
| Pix é real | o % vem da diferença entre o preço normal e o preço Pix do ML |
| Não manda link morto | 404 no catálogo = oferta descartada |
| Não repete por repetir | só repete produto se o preço baixou, com selo "baixou de preço" |

---

## Goals

**Business goal:** Gerar receita de afiliado — o usuário disse: *"caro o barato, solo que ganemos como afiliados"*.

**Conversion action:** **Entrar no grupo do WhatsApp.**
`https://chat.whatsapp.com/JNPVP3apwZw2aKizBZovvC`

**Current metrics:**
- Meta: ~150 publicações/dia
- Publicando: 14 no dia do registro (cadência de 1-10 min entre 8h e 22h BRT)
- Visitantes do site: acompanhados pelo GA4 (`G-NFQTYQ0HXH`)

**O funil é:**
```
Google / redes sociais  ->  site (achadinhosnozap.com.br)
                                  |
                                  v
                         Entrar no grupo do WhatsApp
                                  |
                                  v
                      clicar no link -> comprar -> comissão
```

**Prioridade de marketing:** o gargalo atual é **entrada de gente no grupo**. O robô já publica bem; falta o topo do funil (Google e redes sociais).

---

## Changelog

- v1 (2026-09-30) — Contexto inicial, redigido a partir do próprio projeto (código, dados medidos e histórico de correções). O diferencial central é a verificação de preço/cupom contra o Mercado Livre, que nasceu de erros reais encontrados no checkout.
