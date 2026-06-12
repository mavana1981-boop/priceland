"""
scrapers/
  base.py          → classe abstrata ConectorBase
  carrefour.py     → ConectorCarrefour
  paodeacucar.py   → ConectorPdA
  nfce.py          → ConectorNFCe (QR Code SEFAZ-DF)
  manager.py       → ScraperManager (orquestra todos)
"""

import asyncio
import re
import xml.etree.ElementTree as ET
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from urllib.parse import urlparse, parse_qs

# ── Resultado padronizado ─────────────────────────────────────────────────────

@dataclass
class ResultadoPreco:
    nome_produto: str
    preco: float
    loja: str
    url: str
    ean: Optional[str] = None
    fonte: str = 'scraping'
    coletado_em: datetime = None

    def __post_init__(self):
        if self.coletado_em is None:
            self.coletado_em = datetime.utcnow()


# ── Base abstrata ─────────────────────────────────────────────────────────────

class ConectorBase(ABC):
    nome_loja: str = ''
    url_busca: str = ''

    @abstractmethod
    async def buscar(self, produto: str) -> list[ResultadoPreco]:
        """Recebe termo de busca, devolve lista de ResultadoPreco."""
        ...

    def _limpar_preco(self, texto: str) -> Optional[float]:
        """'R$\xa012,90' → 12.90"""
        texto = texto.replace('\xa0', '').replace(' ', '')
        match = re.search(r'[\d]+[.,][\d]{2}', texto)
        if not match:
            return None
        return float(match.group().replace('.', '').replace(',', '.'))


# ── Conector Carrefour ────────────────────────────────────────────────────────

class ConectorCarrefour(ConectorBase):
    nome_loja = 'Carrefour'
    url_busca = 'https://mercado.carrefour.com.br/{produto}'

    async def buscar(self, produto: str) -> list[ResultadoPreco]:
        try:
            from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig
            from crawl4ai.extraction_strategy import JsonCssExtractionStrategy

            schema = {
                "name": "produtos_carrefour",
                "baseSelector": "[data-testid='product-card']",
                "fields": [
                    {"name": "nome",  "selector": "[data-testid='product-title']",  "type": "text"},
                    {"name": "preco", "selector": "[data-testid='product-selling-price']", "type": "text"},
                    {"name": "link",  "selector": "a", "type": "attribute", "attribute": "href"},
                ]
            }

            url = f"https://mercado.carrefour.com.br/{produto.replace(' ', '%20')}"
            bc  = BrowserConfig(headless=True, browser_type='chromium')
            rc  = CrawlerRunConfig(
                extraction_strategy=JsonCssExtractionStrategy(schema),
                wait_for="css:[data-testid='product-card']",
                page_timeout=15000,
            )

            async with AsyncWebCrawler(config=bc) as crawler:
                result = await crawler.arun(url=url, config=rc)

            if not result.success or not result.extracted_content:
                return []

            import json
            itens = json.loads(result.extracted_content)
            saida = []
            for item in itens[:5]:
                preco = self._limpar_preco(item.get('preco', ''))
                if preco and item.get('nome'):
                    saida.append(ResultadoPreco(
                        nome_produto=item['nome'],
                        preco=preco,
                        loja=self.nome_loja,
                        url=item.get('link', url),
                        fonte='scraping',
                    ))
            return saida

        except Exception as e:
            print(f"[Carrefour] erro: {e}")
            return []


# ── Conector Pão de Açúcar ────────────────────────────────────────────────────

class ConectorPdA(ConectorBase):
    nome_loja = 'Pão de Açúcar'
    url_busca = 'https://www.paodeacucar.com/busca?terms={produto}'

    async def buscar(self, produto: str) -> list[ResultadoPreco]:
        try:
            from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig
            from crawl4ai.extraction_strategy import JsonCssExtractionStrategy

            schema = {
                "name": "produtos_pda",
                "baseSelector": ".product-card",
                "fields": [
                    {"name": "nome",  "selector": ".product-card__description", "type": "text"},
                    {"name": "preco", "selector": ".product-card__selling-price", "type": "text"},
                    {"name": "link",  "selector": "a.product-card__link", "type": "attribute", "attribute": "href"},
                    {"name": "ean",   "selector": "[data-ean]", "type": "attribute", "attribute": "data-ean"},
                ]
            }

            url = f"https://www.paodeacucar.com/busca?terms={produto.replace(' ', '+')}"
            bc  = BrowserConfig(headless=True, browser_type='chromium')
            rc  = CrawlerRunConfig(
                extraction_strategy=JsonCssExtractionStrategy(schema),
                wait_for="css:.product-card",
                page_timeout=15000,
            )

            async with AsyncWebCrawler(config=bc) as crawler:
                result = await crawler.arun(url=url, config=rc)

            if not result.success or not result.extracted_content:
                return []

            import json
            itens = json.loads(result.extracted_content)
            saida = []
            for item in itens[:5]:
                preco = self._limpar_preco(item.get('preco', ''))
                if preco and item.get('nome'):
                    saida.append(ResultadoPreco(
                        nome_produto=item['nome'],
                        preco=preco,
                        loja=self.nome_loja,
                        url='https://www.paodeacucar.com' + item.get('link', ''),
                        ean=item.get('ean'),
                        fonte='scraping',
                    ))
            return saida

        except Exception as e:
            print(f"[PdA] erro: {e}")
            return []


# ── Conector NFC-e SEFAZ-DF ──────────────────────────────────────────────────

class ConectorNFCe(ConectorBase):
    """
    Lê QR Code do cupom fiscal do DF.
    URL do QR Code → GET na SEFAZ → parse do HTML/XML retornado.

    Endpoint DF: http://www.fazenda.df.gov.br/nfce/qrcode?
    Parâmetros: chNFe (chave 44 dígitos) + cHashQRCode
    """
    nome_loja = 'NFC-e SEFAZ-DF'

    async def buscar(self, produto: str) -> list[ResultadoPreco]:
        # NFC-e não usa busca por texto — entrada é via QR Code
        return []

    async def processar_qrcode(self, qrcode_url: str) -> list[ResultadoPreco]:
        """
        Recebe a URL decodificada do QR Code do cupom fiscal.
        Faz GET na SEFAZ e extrai itens + preços do XML retornado.
        """
        try:
            from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig

            bc = BrowserConfig(headless=True, browser_type='chromium')
            rc = CrawlerRunConfig(page_timeout=15000)

            async with AsyncWebCrawler(config=bc) as crawler:
                result = await crawler.arun(url=qrcode_url, config=rc)

            if not result.success:
                return []

            return self._parse_nfce_html(result.html or '', qrcode_url)

        except Exception as e:
            print(f"[NFCe] erro: {e}")
            return []

    def _parse_nfce_html(self, html: str, url: str) -> list[ResultadoPreco]:
        """
        Extrai itens da NFC-e retornada pela SEFAZ-DF.
        O HTML segue layout padrão nacional com tabela de produtos.
        """
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, 'html.parser')

        # Nome da loja no topo do cupom
        loja_el = soup.select_one('#NFe > table > tbody > tr:first-child td')
        loja    = loja_el.get_text(strip=True) if loja_el else 'Loja NFC-e'

        resultados = []
        # Tabela de itens: cada <tr> com class "Item"
        for row in soup.select('tr.Item'):
            cols = row.find_all('td')
            if len(cols) < 3:
                continue
            nome  = cols[0].get_text(strip=True)
            qtd   = cols[1].get_text(strip=True)
            total = cols[2].get_text(strip=True)
            ean_el = row.get('data-ean') or ''
            preco = self._limpar_preco(total)
            if preco and nome:
                resultados.append(ResultadoPreco(
                    nome_produto=nome,
                    preco=preco,
                    loja=loja,
                    url=url,
                    ean=ean_el or None,
                    fonte='nfce',
                ))
        return resultados


# ── Dados simulados para demonstração ────────────────────────────────────────
# (usados quando scraping real não está disponível)

MOCK_DATA = {
    'arroz': [
        ResultadoPreco('Arroz Camil Parboilizado 5kg',  18.90, 'Carrefour',     'https://mercado.carrefour.com.br/arroz-camil-5kg',  ean='7896006751335'),
        ResultadoPreco('Arroz Camil 5kg',               19.90, 'Pão de Açúcar', 'https://www.paodeacucar.com/produto/arroz-camil',    ean='7896006751335'),
        ResultadoPreco('Arroz Tio João 5kg',            17.50, 'Carrefour',     'https://mercado.carrefour.com.br/arroz-tio-joao',   ean='7891895013718'),
        ResultadoPreco('Arroz Tio João Longo Fino 5kg', 18.20, 'Atacadão',      'https://www.atacadao.com.br/arroz-tio-joao',        ean='7891895013718'),
        ResultadoPreco('Arroz Prato Fino 5kg',          16.80, 'Assaí',         'https://www.assai.com.br/arroz-prato-fino',          ean='7896006750001'),
    ],
    'leite': [
        ResultadoPreco('Leite Integral Italac 1L',      4.29,  'Carrefour',     'https://mercado.carrefour.com.br/leite-italac',     ean='7898215151854'),
        ResultadoPreco('Leite Integral Parmalat 1L',    4.89,  'Pão de Açúcar', 'https://www.paodeacucar.com/produto/leite-parmalat', ean='7891097000885'),
        ResultadoPreco('Leite Integral Ninho 1L',       6.49,  'Atacadão',      'https://www.atacadao.com.br/leite-ninho',           ean='7891000100103'),
        ResultadoPreco('Leite Integral Betânia 1L',     3.99,  'Assaí',         'https://www.assai.com.br/leite-betania',            ean='7896183200014'),
    ],
    'feijao': [
        ResultadoPreco('Feijão Carioca Camil 1kg',      8.90,  'Carrefour',     'https://mercado.carrefour.com.br/feijao-camil',     ean='7896006752226'),
        ResultadoPreco('Feijão Carioca Kicaldo 1kg',    9.20,  'Pão de Açúcar', 'https://www.paodeacucar.com/produto/feijao-kicaldo', ean='7896004003820'),
        ResultadoPreco('Feijão Preto Camil 1kg',        9.50,  'Atacadão',      'https://www.atacadao.com.br/feijao-preto',          ean='7896006752004'),
        ResultadoPreco('Feijão Carioca TF 1kg',         7.80,  'Assaí',         'https://www.assai.com.br/feijao-tf',               ean='7896084100010'),
    ],
    'oleo': [
        ResultadoPreco('Óleo de Soja Liza 900ml',       7.90,  'Carrefour',     'https://mercado.carrefour.com.br/oleo-liza',        ean='7896036090398'),
        ResultadoPreco('Óleo de Soja Soya 900ml',       8.20,  'Pão de Açúcar', 'https://www.paodeacucar.com/produto/oleo-soya',    ean='7891107101621'),
        ResultadoPreco('Óleo de Soja Liza 900ml',       7.50,  'Atacadão',      'https://www.atacadao.com.br/oleo-liza',            ean='7896036090398'),
    ],
    'cafe': [
        ResultadoPreco('Café Pilão Tradicional 500g',  14.90,  'Carrefour',     'https://mercado.carrefour.com.br/cafe-pilao',       ean='7896089010011'),
        ResultadoPreco('Café 3 Corações 500g',         13.50,  'Pão de Açúcar', 'https://www.paodeacucar.com/produto/cafe-3coracoes', ean='7896045100065'),
        ResultadoPreco('Café Melitta 500g',            12.90,  'Atacadão',      'https://www.atacadao.com.br/cafe-melitta',          ean='7891021009011'),
        ResultadoPreco('Café Pilão 500g',              15.20,  'Assaí',         'https://www.assai.com.br/cafe-pilao',              ean='7896089010011'),
    ],
}

def buscar_mock(termo: str) -> list[ResultadoPreco]:
    """Retorna dados simulados para demonstração."""
    termo_lower = termo.lower()
    for chave, resultados in MOCK_DATA.items():
        if chave in termo_lower or any(
            chave in r.nome_produto.lower() for r in resultados[:1]
        ):
            return resultados
    # busca parcial
    todos = []
    for resultados in MOCK_DATA.values():
        for r in resultados:
            if termo_lower in r.nome_produto.lower():
                todos.append(r)
    return todos or MOCK_DATA.get('arroz', [])


# ── Manager ──────────────────────────────────────────────────────────────────

class ScraperManager:
    """
    Orquestra todos os conectores em paralelo.
    Se o scraping real falhar (ou estiver desabilitado),
    cai automaticamente nos dados mock.
    """

    def __init__(self, usar_mock: bool = False):
        self.usar_mock = usar_mock
        self.conectores: list[ConectorBase] = [
            ConectorCarrefour(),
            ConectorPdA(),
        ]

    async def buscar_todos(self, produto: str) -> list[ResultadoPreco]:
        if self.usar_mock:
            return buscar_mock(produto)

        tarefas = [c.buscar(produto) for c in self.conectores]
        resultados_por_conector = await asyncio.gather(*tarefas, return_exceptions=True)

        todos = []
        for res in resultados_por_conector:
            if isinstance(res, list):
                todos.extend(res)

        # fallback para mock se todos falharam
        if not todos:
            print("[Manager] scraping falhou, usando dados mock")
            return buscar_mock(produto)

        return todos

    def buscar_sync(self, produto: str) -> list[ResultadoPreco]:
        """Wrapper síncrono para uso no Flask."""
        return asyncio.run(self.buscar_todos(produto))
