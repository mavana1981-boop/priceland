"""
Scrapers ComparaPreço DF
========================
ConectorGoogleShopping  → Google Shopping filtrado para Brasília
ConectorNFCe            → QR Code do cupom fiscal SEFAZ-DF
ScraperManager          → orquestra tudo, fallback para mock
"""

import asyncio
import re
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from urllib.parse import quote_plus


# ── Resultado padronizado ─────────────────────────────────────────────────────

@dataclass
class ResultadoPreco:
    nome_produto: str
    preco: float
    loja: str
    url: str
    ean: Optional[str] = None
    fonte: str = 'google_shopping'
    imagem: Optional[str] = None
    coletado_em: datetime = field(default_factory=datetime.utcnow)


# ── Utilitário ────────────────────────────────────────────────────────────────

def _limpar_preco(texto: str) -> Optional[float]:
    """'R$\xa018,90' → 18.90"""
    texto = texto.replace('\xa0', '').replace('\u202f', '').replace(' ', '')
    match = re.search(r'[\d]+[.,][\d]{2}', texto)
    if not match:
        return None
    return float(match.group().replace('.', '').replace(',', '.'))


# ── Conector Google Shopping ──────────────────────────────────────────────────

class ConectorGoogleShopping:
    """
    Busca no Google Shopping filtrando por Brasília (gl=BR, hl=pt-BR, near=Brasília).
    Usa Crawl4AI (Playwright headless) com modo stealth para evitar bloqueio.

    URL: https://www.google.com/search?q={termo}&tbm=shop&gl=BR&hl=pt-BR&near=Brasília
    """

    SELETORES = {
        # Container de cada card de produto no Google Shopping
        'cards':  'div.sh-dgr__content, div.KZmu8e, .i0X6df',
        # Título do produto
        'titulo': 'h3.tAxDx, h4.xsUMfe, [data-item-index] h3, .sh-np__product-title',
        # Preço
        'preco':  'span.a8Pemb, span.HRLxBb, .sh-np__current-price',
        # Nome da loja / vendedor
        'loja':   'div.aULzUe, span.E5ocAb, .sh-np__seller-info',
        # Link do produto
        'link':   'a.shntl, a[data-sh-or]',
        # Imagem (opcional)
        'imagem': 'img.ArOc1c, img[data-atf]',
    }

    def _url(self, produto: str) -> str:
        q = quote_plus(produto)
        return (
            f"https://www.google.com/search"
            f"?q={q}"
            f"&tbm=shop"
            f"&gl=BR"
            f"&hl=pt-BR"
            f"&near=Bras%C3%ADlia%2C+DF"
        )

    async def buscar(self, produto: str, max_resultados: int = 10) -> list[ResultadoPreco]:
        """
        Busca no Google Shopping e extrai resultados via parsing heurístico.
        Não depende de classes CSS específicas (que o Google muda constantemente).
        Estratégia: localiza todos os preços R$ no HTML e extrai o contexto ao redor.
        """
        try:
            from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig

            url = self._url(produto)
            bc  = BrowserConfig(
                headless=True,
                browser_type='chromium',
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
            )
            rc = CrawlerRunConfig(
                page_timeout=30000,
                js_code="window.scrollTo(0, 600);",
                simulate_user=True,
                magic=True,
                scan_full_page=True,
                delay_before_return_html=3.0,
            )

            async with AsyncWebCrawler(config=bc) as crawler:
                result = await crawler.arun(url=url, config=rc)

            if not result.success or not result.html:
                print(f"[GoogleShopping] fetch falhou: {result.error_message}")
                return []

            return self._parse_heuristico(result.html, url, max_resultados)

        except Exception as e:
            print(f"[GoogleShopping] erro: {e}")
            return []

    def _parse_heuristico(self, html: str, url_busca: str, max_resultados: int) -> list[ResultadoPreco]:
        """
        Extração resiliente a mudanças de layout:
        1. Encontra todos os blocos <a> ou <div> que contenham um preço R$ X,XX
        2. Sobe na árvore até achar um container com título plausível
        3. Extrai título, preço, loja e link
        """
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, 'html.parser')

        # Remove scripts/styles para limpar o texto
        for tag in soup(['script', 'style', 'noscript']):
            tag.decompose()

        preco_re = re.compile(r'R\$\s*([\d.]+,\d{2})')
        vistos   = set()
        saida    = []

        # Encontra todos os elementos folha que contêm exatamente um preço
        for el in soup.find_all(string=preco_re):
            if len(saida) >= max_resultados:
                break

            match = preco_re.search(str(el))
            if not match:
                continue
            preco = _limpar_preco(match.group(0))
            if not preco or preco < 0.5 or preco > 100000:
                continue

            # Sobe na árvore procurando um container com texto rico (card do produto)
            container = el.parent
            for _ in range(6):
                if container is None:
                    break
                texto = container.get_text(' ', strip=True)
                # container de card típico: tem o preço E um título com 15+ chars
                if len(texto) > 40 and len(texto) < 600:
                    break
                container = container.parent

            if container is None:
                continue

            texto_full = container.get_text(' | ', strip=True)

            # Título: maior trecho de texto que não seja preço nem termos genéricos
            partes = [p.strip() for p in texto_full.split('|')]
            titulo = ''
            loja   = 'Google Shopping'
            for p in partes:
                if preco_re.search(p):
                    continue
                low = p.lower()
                if any(skip in low for skip in ('frete', 'avalia', 'estrela', 'parcel', 'em até', 'cupom', 'oferta', 'comparar')):
                    continue
                if len(p) > len(titulo) and len(p) > 12:
                    titulo = p
                # loja: trecho curto que parece nome de estabelecimento
                elif 3 < len(p) < 35 and not p.replace('.','').replace(',','').isdigit():
                    loja = p

            if not titulo:
                continue

            # dedup por título+preço
            chave = (titulo[:50], preco)
            if chave in vistos:
                continue
            vistos.add(chave)

            # Link: procura <a href> no container
            link = url_busca
            a_tag = container.find('a', href=True)
            if a_tag:
                href = a_tag['href']
                link = 'https://www.google.com' + href if href.startswith('/') else href

            saida.append(ResultadoPreco(
                nome_produto=titulo[:150],
                preco=preco,
                loja=loja[:80],
                url=link,
                fonte='google_shopping',
            ))

        print(f"[GoogleShopping] parsing heurístico: {len(saida)} resultados")
        return saida


# ── Conector NFC-e SEFAZ-DF ──────────────────────────────────────────────────

class ConectorNFCe:
    """
    Lê QR Code do cupom fiscal do DF.
    Endpoint: http://www.fazenda.df.gov.br/nfce/qrcode?chNFe=...
    Retorna HTML com tabela de itens (padrão DANFE Web nacional).
    """

    async def processar_qrcode(self, qrcode_url: str) -> list[ResultadoPreco]:
        try:
            from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig
            bc = BrowserConfig(headless=True, browser_type='chromium')
            rc = CrawlerRunConfig(page_timeout=15000)
            async with AsyncWebCrawler(config=bc) as crawler:
                result = await crawler.arun(url=qrcode_url, config=rc)
            if not result.success:
                return []
            return self._parse_html(result.html or '', qrcode_url)
        except Exception as e:
            print(f"[NFCe] erro: {e}")
            return []

    def _parse_html(self, html: str, url: str) -> list[ResultadoPreco]:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, 'html.parser')
        loja_el = soup.select_one('#NFe > table > tbody > tr:first-child td')
        loja    = loja_el.get_text(strip=True) if loja_el else 'Loja NFC-e'
        resultados = []
        for row in soup.select('tr.Item'):
            cols = row.find_all('td')
            if len(cols) < 3:
                continue
            nome  = cols[0].get_text(strip=True)
            total = cols[2].get_text(strip=True)
            preco = _limpar_preco(total)
            ean   = row.get('data-ean')
            if preco and nome:
                resultados.append(ResultadoPreco(
                    nome_produto=nome, preco=preco,
                    loja=loja, url=url, ean=ean, fonte='nfce',
                ))
        return resultados


# ── Mock para desenvolvimento ─────────────────────────────────────────────────

MOCK_DATA: dict[str, list[ResultadoPreco]] = {
    'arroz': [
        ResultadoPreco('Arroz Camil Parboilizado 5kg',       18.90, 'Carrefour Brasília',       'https://mercado.carrefour.com.br/arroz-camil-5kg',   ean='7896006751335'),
        ResultadoPreco('Arroz Camil 5kg',                    19.90, 'Pão de Açúcar Asa Norte',  'https://www.paodeacucar.com/produto/arroz-camil',    ean='7896006751335'),
        ResultadoPreco('Arroz Tio João Longo Fino 5kg',      17.50, 'Atacadão Taguatinga',      'https://www.atacadao.com.br/arroz-tio-joao',         ean='7891895013718'),
        ResultadoPreco('Arroz Tio João 5kg',                 18.20, 'Assaí Gama',               'https://www.assai.com.br/arroz-tio-joao',            ean='7891895013718'),
        ResultadoPreco('Arroz Prato Fino Tipo 1 5kg',        16.80, 'Supermercados BH',         'https://www.supermercadosbh.com.br/arroz-prato-fino', ean='7896006750001'),
        ResultadoPreco('Arroz Camil Parboilizado 5kg',       20.50, 'Extra.com.br',             'https://www.extra.com.br/arroz-camil',               ean='7896006751335'),
    ],
    'leite': [
        ResultadoPreco('Leite Integral Italac 1L',           4.29,  'Carrefour Brasília',       'https://mercado.carrefour.com.br/leite-italac',      ean='7898215151854'),
        ResultadoPreco('Leite Integral Parmalat 1L',         4.89,  'Pão de Açúcar Asa Norte',  'https://www.paodeacucar.com/produto/leite-parmalat', ean='7891097000885'),
        ResultadoPreco('Leite Integral Ninho 1L',            6.49,  'Atacadão Taguatinga',      'https://www.atacadao.com.br/leite-ninho',            ean='7891000100103'),
        ResultadoPreco('Leite Integral Betânia 1L',          3.99,  'Assaí Gama',               'https://www.assai.com.br/leite-betania',             ean='7896183200014'),
        ResultadoPreco('Leite UHT Integral Piracanjuba 1L',  4.59,  'Supermercados BH',         'https://www.supermercadosbh.com.br/leite-piracanjuba', ean='7896259410119'),
    ],
    'feijao': [
        ResultadoPreco('Feijão Carioca Camil 1kg',           8.90,  'Carrefour Brasília',       'https://mercado.carrefour.com.br/feijao-camil',      ean='7896006752226'),
        ResultadoPreco('Feijão Carioca Kicaldo 1kg',         9.20,  'Pão de Açúcar Asa Norte',  'https://www.paodeacucar.com/produto/feijao-kicaldo', ean='7896004003820'),
        ResultadoPreco('Feijão Preto Camil 1kg',             9.50,  'Atacadão Taguatinga',      'https://www.atacadao.com.br/feijao-preto-camil',     ean='7896006752004'),
        ResultadoPreco('Feijão Carioca TF 1kg',              7.80,  'Assaí Gama',               'https://www.assai.com.br/feijao-tf',                 ean='7896084100010'),
    ],
    'cafe': [
        ResultadoPreco('Café Pilão Tradicional 500g',       14.90,  'Carrefour Brasília',       'https://mercado.carrefour.com.br/cafe-pilao',        ean='7896089010011'),
        ResultadoPreco('Café 3 Corações 500g',              13.50,  'Pão de Açúcar Asa Norte',  'https://www.paodeacucar.com/produto/cafe-3coracoes', ean='7896045100065'),
        ResultadoPreco('Café Melitta Tradicional 500g',     12.90,  'Atacadão Taguatinga',      'https://www.atacadao.com.br/cafe-melitta',           ean='7891021009011'),
        ResultadoPreco('Café Pilão 500g',                   15.20,  'Extra.com.br',             'https://www.extra.com.br/cafe-pilao',                ean='7896089010011'),
    ],
    'oleo': [
        ResultadoPreco('Óleo de Soja Liza 900ml',            7.90,  'Carrefour Brasília',       'https://mercado.carrefour.com.br/oleo-liza',         ean='7896036090398'),
        ResultadoPreco('Óleo de Soja Soya 900ml',            8.20,  'Pão de Açúcar Asa Norte',  'https://www.paodeacucar.com/produto/oleo-soya',     ean='7891107101621'),
        ResultadoPreco('Óleo de Soja Liza 900ml',            7.50,  'Atacadão Taguatinga',      'https://www.atacadao.com.br/oleo-liza',              ean='7896036090398'),
    ],
}

def buscar_mock(termo: str) -> list[ResultadoPreco]:
    termo_lower = termo.lower()
    for chave, resultados in MOCK_DATA.items():
        if chave in termo_lower:
            return resultados
    todos = [r for lista in MOCK_DATA.values() for r in lista if termo_lower in r.nome_produto.lower()]
    return todos or MOCK_DATA['arroz']


# ── Manager ───────────────────────────────────────────────────────────────────

class ScraperManager:
    """
    Em produção  (usar_mock=False): busca no Google Shopping via Crawl4AI.
    Em dev       (usar_mock=True) : retorna dados simulados imediatamente.
    Fallback automático para mock se o scraping falhar.
    """

    def __init__(self, usar_mock: bool = False):
        self.usar_mock = usar_mock
        self.google   = ConectorGoogleShopping()
        self.nfce     = ConectorNFCe()

    async def buscar_todos(self, produto: str) -> list[ResultadoPreco]:
        if self.usar_mock:
            return buscar_mock(produto)
        resultados = await self.google.buscar(produto)
        if not resultados:
            print("[Manager] Google Shopping falhou → usando mock")
            return buscar_mock(produto)
        return resultados

    def buscar_sync(self, produto: str) -> list[ResultadoPreco]:
        return asyncio.run(self.buscar_todos(produto))
