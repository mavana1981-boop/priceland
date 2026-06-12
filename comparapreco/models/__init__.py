from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()

class Loja(db.Model):
    __tablename__ = 'lojas'
    id       = db.Column(db.Integer, primary_key=True)
    nome     = db.Column(db.String(100), nullable=False)
    cnpj     = db.Column(db.String(20))
    bairro   = db.Column(db.String(100))
    url_base = db.Column(db.String(200))
    ativo    = db.Column(db.Boolean, default=True)
    precos   = db.relationship('Preco', back_populates='loja')

class Produto(db.Model):
    __tablename__ = 'produtos'
    id               = db.Column(db.Integer, primary_key=True)
    nome_normalizado = db.Column(db.String(200), nullable=False)
    ean              = db.Column(db.String(20), index=True)
    categoria        = db.Column(db.String(80))
    marca            = db.Column(db.String(80))
    precos           = db.relationship('Preco', back_populates='produto')

class Preco(db.Model):
    __tablename__ = 'precos'
    id          = db.Column(db.Integer, primary_key=True)
    produto_id  = db.Column(db.Integer, db.ForeignKey('produtos.id'), nullable=False)
    loja_id     = db.Column(db.Integer, db.ForeignKey('lojas.id'), nullable=False)
    preco       = db.Column(db.Numeric(10, 2), nullable=False)
    url         = db.Column(db.String(500))
    fonte       = db.Column(db.String(20), default='scraping')  # scraping | nfce
    coletado_em = db.Column(db.DateTime, default=datetime.utcnow)
    produto     = db.relationship('Produto', back_populates='precos')
    loja        = db.relationship('Loja', back_populates='precos')
