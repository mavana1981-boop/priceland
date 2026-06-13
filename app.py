import os
import json
import subprocess
import pathlib
from datetime import datetime, timedelta
from flask import Flask, render_template, request, jsonify
from models import db, Produto, Loja, Preco
from scrapers import ScraperManager, buscar_mock, ConectorGoogleShopping

# ── Auto-instala Chromium se não estiver presente ─────────────────────────────
def _ensure_playwright():
    cache = pathlib.Path.home() / '.cache' / 'ms-playwright'
    chrome_found = cache.exists() and any(
        f.name == 'chrome' for f in cache.rglob('chrome') if f.is_file()
    )
    if not chrome_found:
        print("[startup] Chromium não encontrado — instalando...")
        subprocess.run(
            ['playwright', 'install', 'chromium', '--with-deps'],
            check=False
        )
        print("[startup] Chromium pronto.")

_ensure_playwright()

# ─────────────────────────────────────────────────────────────────────────────

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv(
    'DATABASE_URL', 'sqlite:///comparapreco.db'
).replace('postgres://', 'postgresql://')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db.init_app(app)

USE_MOCK = os.getenv('USE_MOCK', 'false').lower() == 'true'
manager  = ScraperManager(usar_mock=USE_MOCK)


# ── Helpers ───────────────────────────────────────────────────────────────────

def agrupar_por_produto(resultados):
    grupos = {}
    for r in resultados:
        chave = r.ean or r.nome_produto.lower()[:35]
        if chave not in grupos:
            grupos[chave] = {'nome': r.nome_produto, 'ean': r.ean, 'precos': []}
        grupos[chave]['precos'].append({
            'loja': r.loja, 'preco': r.preco,
            'url': r.url, 'fonte': r.fonte,
            'imagem': getattr(r, 'imagem', None),
        })
    for g in grupos.values():
        g['precos'].sort(key=lambda x: x['preco'])
        g['menor']    = g['precos'][0]
        g['maior']    = g['precos'][-1]
        g['economia'] = round(g['maior']['preco'] - g['menor']['preco'], 2)
    return sorted(grupos.values(), key=lambda x: x['menor']['preco'])


# ── Rotas ─────────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/buscar')
def buscar():
    termo = request.args.get('q', '').strip()
    if not termo:
        return render_template('index.html', erro='Digite um produto.')
    resultados = manager.buscar_sync(termo)
    grupos = agrupar_por_produto(resultados)
    return render_template('resultado.html',
                           termo=termo, grupos=grupos,
                           total=len(resultados),
                           fonte='Google Shopping · Brasília, DF',
                           agora=datetime.now().strftime('%d/%m/%Y %H:%M'))


@app.route('/api/buscar')
def api_buscar():
    termo = request.args.get('q', '').strip()
    if not termo:
        return jsonify({'erro': 'Parâmetro q obrigatório'}), 400
    resultados = manager.buscar_sync(termo)
    return jsonify([{
        'nome': r.nome_produto, 'preco': r.preco, 'loja': r.loja,
        'url': r.url, 'ean': r.ean, 'fonte': r.fonte,
        'coletado_em': r.coletado_em.isoformat(),
    } for r in resultados])


@app.route('/nfce', methods=['GET', 'POST'])
def nfce():
    if request.method == 'GET':
        return render_template('nfce.html')
    url_qr = request.form.get('url_qr', '').strip()
    if not url_qr:
        return render_template('nfce.html', erro='Cole a URL do QR Code do cupom.')
    itens_mock = [
        {'nome': 'ARROZ CAMIL PARB 5KG',  'preco': 18.90, 'ean': '7896006751335'},
        {'nome': 'LEITE ITALAC INT 1L',   'preco':  4.29, 'ean': '7898215151854'},
        {'nome': 'FEIJAO CAMIL CAR 1KG',  'preco':  8.90, 'ean': '7896006752226'},
        {'nome': 'OLEO SOJA LIZA 900ML',  'preco':  7.90, 'ean': '7896036090398'},
        {'nome': 'CAFE PILAO TRAD 500G',  'preco': 14.90, 'ean': '7896089010011'},
    ]
    total     = sum(i['preco'] for i in itens_mock)
    loja_info = {'nome': 'Carrefour Asa Norte', 'cnpj': '45.543.915/0116-00', 'data': '13/06/2026 00:22'}
    return render_template('nfce.html', itens=itens_mock, total=total,
                           loja=loja_info, url_qr=url_qr)


@app.route('/status')
def status():
    return jsonify({
        'modo': 'mock' if USE_MOCK else 'google_shopping_real',
        'conector': 'buscar_mock()' if USE_MOCK else 'ConectorGoogleShopping → Crawl4AI → Playwright',
        'url_exemplo': ConectorGoogleShopping()._url('arroz camil 5kg'),
    })


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True, port=5050)
