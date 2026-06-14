import os
from datetime import datetime
from flask import Flask, render_template, request, jsonify, redirect, url_for
from models import db, Cesta, ItemCesta, Estabelecimento, RegistroPreco
from ia import analisar_foto

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv(
    'DATABASE_URL', 'sqlite:///cesta.db'
).replace('postgres://', 'postgresql://')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16 MB max upload
db.init_app(app)


# ── Helpers ───────────────────────────────────────────────────────────────────

def calcular_ideal(cesta):
    """Para cada item, busca o menor preço já registrado em qualquer loja."""
    itens_resultado = []
    total_ideal = 0.0
    total_meta  = 0.0

    for item in cesta.itens:
        melhor = (RegistroPreco.query
            .join(Estabelecimento)
            .filter(RegistroPreco.produto_nome.ilike(f'%{item.nome_produto}%'))
            .order_by(RegistroPreco.preco.asc())
            .first())

        preco_unit  = float(melhor.preco) if melhor else None
        preco_total = preco_unit * item.quantidade if preco_unit else None
        meta_total  = float(item.preco_meta) * item.quantidade if item.preco_meta else None

        if preco_total:
            total_ideal += preco_total
        if meta_total:
            total_meta += meta_total

        if melhor and item.preco_meta:
            status = 'ok' if preco_unit <= float(item.preco_meta) else 'acima'
        elif melhor:
            status = 'sem_meta'
        else:
            status = 'sem_preco'

        itens_resultado.append({
            'item':        item,
            'melhor':      melhor,
            'preco_total': preco_total,
            'status':      status,
        })

    return {
        'itens':       itens_resultado,
        'total_ideal': round(total_ideal, 2),
        'total_meta':  round(total_meta, 2),
    }


def calcular_por_loja(cesta):
    """Para cada loja, calcula quanto custaria comprar todos os itens da cesta lá."""
    lojas    = Estabelecimento.query.order_by(Estabelecimento.nome).all()
    resultado = []

    for loja in lojas:
        total     = 0.0
        cobertos  = []
        faltando  = []

        for item in cesta.itens:
            melhor_loja = (RegistroPreco.query
                .filter_by(estabelecimento_id=loja.id)
                .filter(RegistroPreco.produto_nome.ilike(f'%{item.nome_produto}%'))
                .order_by(RegistroPreco.preco.asc())
                .first())

            if melhor_loja:
                subtotal = float(melhor_loja.preco) * item.quantidade
                total   += subtotal
                cobertos.append({'item': item, 'preco': float(melhor_loja.preco), 'subtotal': subtotal})
            else:
                faltando.append(item)

        if cobertos:
            pct = round(len(cobertos) / len(cesta.itens) * 100) if cesta.itens else 0
            resultado.append({
                'loja':         loja,
                'total':        round(total, 2),
                'cobertos':     cobertos,
                'faltando':     faltando,
                'cobertura_pct': pct,
            })

    resultado.sort(key=lambda x: (-x['cobertura_pct'], x['total']))
    return resultado


# ── Rotas — Cestas ────────────────────────────────────────────────────────────

@app.route('/')
def index():
    cestas = Cesta.query.order_by(Cesta.criado_em.desc()).all()
    return render_template('index.html', cestas=cestas)


@app.route('/cesta/nova', methods=['POST'])
def nova_cesta():
    nome = request.form.get('nome', '').strip()
    if not nome:
        return redirect('/')
    cesta = Cesta(nome=nome)
    db.session.add(cesta)
    db.session.commit()
    return redirect(url_for('ver_cesta', id=cesta.id))


@app.route('/cesta/<int:id>')
def ver_cesta(id):
    cesta    = Cesta.query.get_or_404(id)
    ideal    = calcular_ideal(cesta)
    por_loja = calcular_por_loja(cesta)
    return render_template('cesta.html', cesta=cesta, ideal=ideal, por_loja=por_loja)


@app.route('/cesta/<int:id>/item', methods=['POST'])
def add_item(id):
    Cesta.query.get_or_404(id)
    nome       = request.form.get('nome', '').strip()
    quantidade = request.form.get('quantidade', '1').replace(',', '.')
    preco_meta = request.form.get('preco_meta', '').replace(',', '.')
    if nome:
        item = ItemCesta(
            cesta_id     = id,
            nome_produto = nome,
            quantidade   = float(quantidade) if quantidade else 1,
            preco_meta   = float(preco_meta) if preco_meta else None,
        )
        db.session.add(item)
        db.session.commit()
    return redirect(url_for('ver_cesta', id=id))


@app.route('/cesta/<int:id>/item/<int:iid>/delete', methods=['POST'])
def del_item(id, iid):
    item = ItemCesta.query.get_or_404(iid)
    db.session.delete(item)
    db.session.commit()
    return redirect(url_for('ver_cesta', id=id))


@app.route('/cesta/<int:id>/delete', methods=['POST'])
def del_cesta(id):
    cesta = Cesta.query.get_or_404(id)
    db.session.delete(cesta)
    db.session.commit()
    return redirect('/')


# ── Rotas — Upload e IA ───────────────────────────────────────────────────────

@app.route('/upload')
def upload():
    lojas = Estabelecimento.query.order_by(Estabelecimento.nome).all()
    return render_template('upload.html', lojas=lojas)


@app.route('/upload/analisar', methods=['POST'])
def upload_analisar():
    """Recebe foto, envia para IA e retorna JSON com produtos extraídos."""
    foto                = request.files.get('foto')
    tipo                = request.form.get('tipo_foto', 'etiqueta')
    estabelecimento_nome = request.form.get('estabelecimento', '').strip()

    if not foto or not estabelecimento_nome:
        return jsonify({'erro': 'Foto e nome do estabelecimento são obrigatórios'}), 400

    try:
        image_bytes = foto.read()
        media_type  = foto.content_type or 'image/jpeg'
        produtos    = analisar_foto(image_bytes, media_type, tipo)
        return jsonify({'produtos': produtos, 'estabelecimento': estabelecimento_nome, 'tipo': tipo})
    except Exception as e:
        return jsonify({'erro': str(e)}), 500


@app.route('/upload/salvar', methods=['POST'])
def upload_salvar():
    """Recebe JSON com produtos confirmados e salva no banco."""
    data                 = request.get_json()
    estabelecimento_nome = (data.get('estabelecimento') or '').strip()
    produtos             = data.get('produtos', [])
    tipo                 = data.get('tipo', 'etiqueta')

    if not estabelecimento_nome or not produtos:
        return jsonify({'erro': 'Dados incompletos'}), 400

    loja = Estabelecimento.query.filter_by(nome=estabelecimento_nome).first()
    if not loja:
        loja = Estabelecimento(nome=estabelecimento_nome)
        db.session.add(loja)
        db.session.flush()

    count = 0
    for p in produtos:
        nome  = str(p.get('nome', '')).strip()
        preco = p.get('preco', 0)
        try:
            preco = float(str(preco).replace(',', '.'))
        except Exception:
            continue
        if nome and preco > 0:
            db.session.add(RegistroPreco(
                produto_nome       = nome,
                preco              = preco,
                estabelecimento_id = loja.id,
                fonte              = tipo,
            ))
            count += 1

    db.session.commit()
    return jsonify({'saved': count, 'loja': estabelecimento_nome})


# ── Rotas — Preços registrados ────────────────────────────────────────────────

@app.route('/precos')
def precos():
    loja_id   = request.args.get('loja', type=int)
    query     = RegistroPreco.query.join(Estabelecimento)
    if loja_id:
        query = query.filter(RegistroPreco.estabelecimento_id == loja_id)
    registros = query.order_by(RegistroPreco.data.desc()).limit(300).all()
    lojas     = Estabelecimento.query.order_by(Estabelecimento.nome).all()
    return render_template('precos.html', registros=registros, lojas=lojas, loja_id=loja_id)


@app.route('/precos/<int:id>/delete', methods=['POST'])
def del_preco(id):
    r = RegistroPreco.query.get_or_404(id)
    db.session.delete(r)
    db.session.commit()
    return redirect(request.referrer or '/precos')


# ─────────────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True, port=5050)
