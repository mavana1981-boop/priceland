# ComparaPreço DF

Comparador de preços de supermercados do Distrito Federal.

## Stack
- **Backend:** Flask + SQLAlchemy + PostgreSQL (Railway)
- **Scraping:** Crawl4AI (Playwright headless) + fallback mock
- **NFC-e:** QR Code SEFAZ-DF → parsing HTML/XML
- **Deploy:** Railway (Nixpacks / Procfile)

## Estrutura
```
comparapreco/
├── app.py              # Flask app + rotas
├── models/__init__.py  # SQLAlchemy: Produto, Loja, Preco
├── scrapers/__init__.py # ConectorCarrefour, ConectorPdA, ConectorNFCe, ScraperManager
├── templates/
│   ├── index.html      # Página inicial com busca
│   ├── resultado.html  # Comparação por produto/EAN
│   └── nfce.html       # Leitor de cupom fiscal
├── requirements.txt
└── Procfile
```

## Variáveis de ambiente (.env)
```
DATABASE_URL=postgresql://user:pass@host:5432/comparapreco
USE_MOCK=false          # true = dados simulados (dev), false = scraping real
```

## Rodar local
```bash
pip install -r requirements.txt
python -m playwright install chromium
python app.py
```

## Fluxo de dados

### Scraping (Crawl4AI)
1. Usuário busca "arroz camil 5kg"
2. `ScraperManager.buscar_todos()` dispara todos conectores em paralelo (`asyncio.gather`)
3. Cada `ConectorXxx.buscar()` usa `JsonCssExtractionStrategy` do Crawl4AI
4. Resultados normalizados por EAN → salvo em `precos`
5. Próxima busca igual nas próximas 60 min → retorna do banco (sem rescrape)

### NFC-e SEFAZ-DF
1. Usuário cola URL do QR Code do cupom
2. `ConectorNFCe.processar_qrcode()` faz GET via Crawl4AI
3. Parser extrai itens com nome, EAN, preço, loja (CNPJ)
4. Cada item vira um `Preco` com `fonte='nfce'` (mais confiável que scraping)
5. Usuário pode clicar "comparar" → busca o mesmo produto nas outras redes

## Adicionando novos supermercados
Criar nova classe em `scrapers/__init__.py` herdando `ConectorBase`:
```python
class ConectorAtacadao(ConectorBase):
    nome_loja = 'Atacadão'
    async def buscar(self, produto: str) -> list[ResultadoPreco]:
        # usar JsonCssExtractionStrategy com seletores do atacadao.com.br
        ...
```
Registrar no `ScraperManager.__init__()`:
```python
self.conectores = [ConectorCarrefour(), ConectorPdA(), ConectorAtacadao()]
```
