from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()

class Estabelecimento(db.Model):
    __tablename__ = 'estabelecimentos'
    id       = db.Column(db.Integer, primary_key=True)
    nome     = db.Column(db.String(100), nullable=False, unique=True)
    registros = db.relationship('RegistroPreco', back_populates='estabelecimento', cascade='all, delete-orphan')

class RegistroPreco(db.Model):
    __tablename__ = 'registros_preco'
    id                 = db.Column(db.Integer, primary_key=True)
    produto_nome       = db.Column(db.String(200), nullable=False, index=True)
    preco              = db.Column(db.Numeric(10, 2), nullable=False)
    estabelecimento_id = db.Column(db.Integer, db.ForeignKey('estabelecimentos.id'), nullable=False)
    data               = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    fonte              = db.Column(db.String(20), default='etiqueta')  # etiqueta | cupom | prateleira
    estabelecimento    = db.relationship('Estabelecimento', back_populates='registros')

class Cesta(db.Model):
    __tablename__ = 'cestas'
    id        = db.Column(db.Integer, primary_key=True)
    nome      = db.Column(db.String(100), nullable=False)
    criado_em = db.Column(db.DateTime, default=datetime.utcnow)
    itens     = db.relationship('ItemCesta', back_populates='cesta', cascade='all, delete-orphan')

class ItemCesta(db.Model):
    __tablename__ = 'itens_cesta'
    id           = db.Column(db.Integer, primary_key=True)
    cesta_id     = db.Column(db.Integer, db.ForeignKey('cestas.id'), nullable=False)
    nome_produto = db.Column(db.String(200), nullable=False)
    quantidade   = db.Column(db.Float, default=1)
    preco_meta   = db.Column(db.Numeric(10, 2))
    cesta        = db.relationship('Cesta', back_populates='itens')
