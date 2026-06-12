import os
import json
from datetime import datetime, timedelta
from flask import Flask, render_template, request, jsonify
from models import db, Produto, Loja, Preco
from scrapers import ScraperManager, buscar_mock

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv(
    'DATABASE_URL', 'sqlite:///comparapreco.db'
).replace('postgres://', 'postgresql://')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)

manager = ScraperManager(usar_mock=True)   # troca para False em produção com Crawl4AI real


# ── Helpers ───────────────────────────────────────────────────────────────────

def salvar_resultados(resultados):
    """Persiste preços coletados no banco."""
    for r in resultados:
        loja = Loja.query.filter_by(nome=r.loja).first()
        if not loja:
            loja = Loja(nome=r.loja, url_base=r.url)
            db.session.add(loja)
            db.session.flush()

        produto = None
        if r.ean:
            produto = Produto.query.filter_by(ean=r.ean).first()
        if not produto:
            produto = Produto.query.filter_by(
                nome_normalizado=r.nome_produto.lower()
            ).first()
        if not produto:
            produto = Produto(
                nome_normalizado=r.nome_produto.lower(),
                ean=r.ean,
            )
            db.session.add(produto)
            db.session.flush()

        preco = Preco(
            produto_id=produto.id,
            loja_id=loja.id,
            preco=r.preco,
            url=r.url,
            fonte=r.fonte,
            coletado_em=r.coletado_em,
        )
        db.session.add(preco)

    db.session.commit()


def dados_frescos(termo: str, max_idade_min: int = 60):
    """Verifica se já há dados frescos no banco para este termo."""
    limite = datetime.utcnow() - timedelta(minutes=max_idade_min)
    return Preco.query.join(Produto).filter(
        Produto.nome_normalizado.ilike(f'%{termo}%'),
        Preco.coletado_em >= limite,
    ).count() > 0


# ── Rotas ─────────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/buscar')
def buscar():
    termo = request.args.get('q', '').strip()
    if not termo:
        return render_template('index.html', erro='Digite um produto.')

    resultados = buscar_mock(termo)

    # Agrupa por EAN para identificar mesmo produto em lojas diferentes
    grupos = {}
    for r in resultados:
        chave = r.ean or r.nome_produto.lower()[:30]
        if chave not in grupos:
            grupos[chave] = {
                'nome': r.nome_produto,
                'ean': r.ean,
                'precos': [],
            }
        grupos[chave]['precos'].append({
            'loja': r.loja,
            'preco': r.preco,
            'url': r.url,
            'fonte': r.fonte,
        })

    # Ordena cada grupo por preço
    for g in grupos.values():
        g['precos'].sort(key=lambda x: x['preco'])
        g['menor'] = g['precos'][0]
        g['maior'] = g['precos'][-1]
        g['economia'] = round(g['maior']['preco'] - g['menor']['preco'], 2)

    grupos_lista = sorted(grupos.values(), key=lambda x: x['menor']['preco'])

    return render_template('resultado.html',
                           termo=termo,
                           grupos=grupos_lista,
                           total=len(resultados),
                           agora=datetime.now().strftime('%d/%m/%Y %H:%M'))


@app.route('/api/buscar')
def api_buscar():
    """Endpoint JSON para uso futuro por app mobile."""
    termo = request.args.get('q', '').strip()
    if not termo:
        return jsonify({'erro': 'Parâmetro q obrigatório'}), 400

    resultados = buscar_mock(termo)
    return jsonify([{
        'nome': r.nome_produto,
        'preco': r.preco,
        'loja': r.loja,
        'url': r.url,
        'ean': r.ean,
        'fonte': r.fonte,
        'coletado_em': r.coletado_em.isoformat(),
    } for r in resultados])


@app.route('/nfce', methods=['GET', 'POST'])
def nfce():
    """Recebe URL de QR Code do cupom fiscal e extrai itens."""
    if request.method == 'GET':
        return render_template('nfce.html')

    url_qr = request.form.get('url_qr', '').strip()
    if not url_qr:
        return render_template('nfce.html', erro='Cole a URL do QR Code do cupom.')

    # Em produção: ConectorNFCe().processar_qrcode(url_qr)
    # Aqui: simulamos uma NFC-e de exemplo
    itens_mock = [
        {'nome': 'ARROZ CAMIL PARB 5KG', 'qtd': '1 UN', 'preco': 18.90, 'ean': '7896006751335'},
        {'nome': 'LEITE ITALAC INT 1L',  'qtd': '2 UN', 'preco':  4.29, 'ean': '7898215151854'},
        {'nome': 'FEIJAO CAMIL CAR 1KG', 'qtd': '1 UN', 'preco':  8.90, 'ean': '7896006752226'},
        {'nome': 'OLEO SOJA LIZA 900ML', 'qtd': '1 UN', 'preco':  7.90, 'ean': '7896036090398'},
        {'nome': 'CAFE PILAO TRAD 500G', 'qtd': '1 UN', 'preco': 14.90, 'ean': '7896089010011'},
    ]
    total = sum(i['preco'] for i in itens_mock)
    loja_info = {'nome': 'Carrefour Asa Norte', 'cnpj': '45.543.915/0116-00', 'data': '12/06/2026 09:32'}

    return render_template('nfce.html',
                           itens=itens_mock,
                           total=total,
                           loja=loja_info,
                           url_qr=url_qr)


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True, port=5050)
