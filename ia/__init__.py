import os
import re
import json
import base64

PROMPTS = {
    'etiqueta': (
        "Você está analisando uma foto de etiqueta de preço de supermercado brasileiro. "
        "Extraia o nome do produto e o preço. "
        "Retorne APENAS JSON válido, sem markdown, sem texto extra: "
        '{"produtos": [{"nome": "Nome exato do produto", "preco": 9.99}]}'
    ),
    'cupom': (
        "Você está analisando um cupom fiscal de supermercado brasileiro. "
        "Extraia todos os produtos e seus preços unitários. "
        "Ignore taxas, descontos e totais — somente itens individuais. "
        "Retorne APENAS JSON válido, sem markdown, sem texto extra: "
        '{"produtos": [{"nome": "Nome do produto", "preco": 9.99}]}'
    ),
    'prateleira': (
        "Você está analisando uma foto de prateleira de supermercado brasileiro. "
        "Extraia TODOS os produtos visíveis que têm etiqueta de preço legível. "
        "Inclua marca, descrição e gramatura quando visíveis. "
        "Se o preço não estiver legível, não inclua o produto. "
        "Retorne APENAS JSON válido, sem markdown, sem texto extra: "
        '{"produtos": [{"nome": "Marca Produto 1kg", "preco": 9.99}]}'
    ),
}

def analisar_foto(image_bytes: bytes, media_type: str, tipo_foto: str) -> list[dict]:
    """
    Envia imagem ao Claude Vision e retorna lista de {nome, preco}.
    Requer ANTHROPIC_API_KEY no ambiente.
    """
    api_key = os.getenv('ANTHROPIC_API_KEY')
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY não configurada")

    import anthropic
    client   = anthropic.Anthropic(api_key=api_key)
    b64      = base64.standard_b64encode(image_bytes).decode('utf-8')
    prompt   = PROMPTS.get(tipo_foto, PROMPTS['etiqueta'])

    response = client.messages.create(
        model='claude-sonnet-4-6',
        max_tokens=1000,
        messages=[{
            'role': 'user',
            'content': [
                {
                    'type': 'image',
                    'source': {'type': 'base64', 'media_type': media_type, 'data': b64}
                },
                {'type': 'text', 'text': prompt}
            ]
        }]
    )

    texto = response.content[0].text.strip()
    # Remove wrappers ```json ``` se o modelo os incluir
    texto = re.sub(r'^```(?:json)?\s*|\s*```$', '', texto, flags=re.MULTILINE).strip()

    data     = json.loads(texto)
    produtos = data.get('produtos', [])

    resultado = []
    for p in produtos:
        nome  = str(p.get('nome', '')).strip()
        preco = p.get('preco', 0)
        if isinstance(preco, str):
            preco = float(
                preco.replace('R$', '').replace('\xa0', '')
                     .replace('.', '').replace(',', '.').strip()
            )
        preco = round(float(preco), 2)
        if nome and preco > 0:
            resultado.append({'nome': nome, 'preco': preco})

    return resultado
