"""
NEXUS Marketplace API Server
Serves card data and analytics for the marketplace frontend
"""

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
import json
import os
from datetime import datetime
from pathlib import Path

app = Flask(__name__)
CORS(app)  # Allow cross-origin requests

# Data directory
DATA_DIR = Path(__file__).parent / 'data'
DATA_DIR.mkdir(exist_ok=True)

def load_cards():
    """Load cards from nexus_library.json"""
    library_file = DATA_DIR / 'nexus_library.json'
    if library_file.exists():
        with open(library_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data
    return {}

def load_collection():
    """Load collection data"""
    data = load_cards()
    box_inventory = data.get('box_inventory', {})

    cards = []
    for box_name, box_cards in box_inventory.items():
        for card in box_cards:
            if isinstance(card, dict):
                cards.append({
                    'name': card.get('name', 'Unknown'),
                    'set': card.get('set_code', 'UNK'),
                    'rarity': card.get('rarity', 'common'),
                    'colors': card.get('colors', []),
                    'price': card.get('price', 0),
                    'box': box_name,
                    'quantity': 1
                })

    return cards

@app.route('/health', methods=['GET'])
def health():
    """Health check"""
    return jsonify({'status': 'healthy', 'timestamp': datetime.now().isoformat()})

@app.route('/status', methods=['GET'])
def status():
    """Server status"""
    cards = load_collection()
    return jsonify({
        'cards_in_db': len(cards),
        'uptime': 'running',
        'version': '1.0.0'
    })

@app.route('/cards/search', methods=['GET'])
def search_cards():
    """Search cards with filters"""
    cards = load_collection()

    # Apply filters from query params
    name_filter = request.args.get('name', '').lower()
    set_filter = request.args.get('set', '').lower()
    rarity_filter = request.args.get('rarity', '').lower()
    color_filter = request.args.get('color', '').lower()
    limit = int(request.args.get('limit', 1000))

    filtered = cards

    if name_filter:
        filtered = [c for c in filtered if name_filter in c['name'].lower()]
    if set_filter:
        filtered = [c for c in filtered if set_filter in c['set'].lower()]
    if rarity_filter:
        filtered = [c for c in filtered if rarity_filter in c['rarity'].lower()]
    if color_filter:
        filtered = [c for c in filtered if any(color_filter in str(col).lower() for col in c['colors'])]

    return jsonify({
        'cards': filtered[:limit],
        'total': len(filtered),
        'limit': limit
    })

@app.route('/analytics/summary', methods=['GET'])
def analytics_summary():
    """Get collection analytics"""
    cards = load_collection()

    total_value = sum(c['price'] for c in cards)
    unique_cards = len(set(c['name'] for c in cards))

    # Get rarity breakdown
    rarities = {}
    for card in cards:
        rarity = card['rarity']
        rarities[rarity] = rarities.get(rarity, 0) + 1

    return jsonify({
        'total_value': round(total_value, 2),
        'total_cards': len(cards),
        'unique_cards': unique_cards,
        'rarities': rarities,
        'average_value': round(total_value / len(cards), 2) if cards else 0
    })

@app.route('/dev/messages', methods=['GET', 'POST'])
def dev_messages():
    """Developer chat/messaging endpoint"""
    messages_file = DATA_DIR / 'messages.json'

    if request.method == 'POST':
        # Get data - support both JSON and form data
        if request.is_json:
            data = request.get_json()
        else:
            data = request.form.to_dict()
        
        # Debug logging
        print(f"Received POST data: {data}")
        print(f"Content-Type: {request.content_type}")
        
        messages = []
        if messages_file.exists():
            with open(messages_file, 'r') as f:
                try:
                    messages = json.load(f)
                except:
                    messages = []

        # Extract message data with fallbacks
        author = data.get('author') or data.get('sender') or 'Anonymous'
        text = data.get('text') or data.get('message') or ''
        
        new_msg = {
            'author': author,
            'text': text,
            'time': datetime.now().strftime('%I:%M %p'),
            'datetime': datetime.now().isoformat()
        }
        
        print(f"Saving message: {new_msg}")
        messages.append(new_msg)

        with open(messages_file, 'w') as f:
            json.dump(messages[-100:], f, indent=2)  # Keep last 100

        # Check if Jacques should respond (always, unless he sent it)
        if new_msg['author'] != 'jacques':
            try:
                import anthropic
                client = anthropic.Anthropic(api_key=os.environ.get('ANTHROPIC_API_KEY'))

                # Get Jacques (Claude) response
                response = client.messages.create(
                    model="claude-sonnet-4-20250514",
                    max_tokens=500,
                    messages=[{
                        "role": "user",
                        "content": f"You are Jacques, a skilled Python developer helping Kevin with his MTG card marketplace project. Kevin just said: '{new_msg['text']}'\n\nRespond as Jacques (casual, helpful, concise):"
                    }]
                )

                jacques_reply = response.content[0].text

                # Add Jacques' response
                jacques_msg = {
                    'author': 'jacques',
                    'text': jacques_reply,
                    'time': datetime.now().strftime('%I:%M %p'),
                    'datetime': datetime.now().isoformat()
                }
                messages.append(jacques_msg)

                with open(messages_file, 'w') as f:
                    json.dump(messages[-100:], f, indent=2)

                return jsonify({'status': 'ok', 'message': 'Message saved, Jacques notified'})

            except Exception as e:
                print(f"Failed to get Jacques AI response: {e}")

        # Check if Mendel should respond (always, unless he sent it)
        if new_msg['author'] != 'mendel':
            try:
                import anthropic
                client = anthropic.Anthropic(api_key=os.environ.get('ANTHROPIC_API_KEY'))

                # Get Mendel (Claude) response
                response = client.messages.create(
                    model="claude-sonnet-4-20250514",
                    max_tokens=500,
                    messages=[{
                        "role": "user",
                        "content": f"You are Mendel, an AI assistant helping Kevin and Jacques with their MTG marketplace project. You're technical, efficient, and use tree emojis 🌲. Someone just said: '{new_msg['text']}'\n\nRespond as Mendel (brief, helpful, technical):"
                    }]
                )

                mendel_reply = response.content[0].text

                # Add Mendel's response
                mendel_msg = {
                    'author': 'mendel',
                    'text': mendel_reply,
                    'time': datetime.now().strftime('%I:%M %p'),
                    'datetime': datetime.now().isoformat()
                }
                messages.append(mendel_msg)

                with open(messages_file, 'w') as f:
                    json.dump(messages[-100:], f, indent=2)

                return jsonify({'status': 'ok', 'message': 'Message saved, Mendel notified'})

            except Exception as e:
                print(f"Failed to get Mendel AI response: {e}")

        return jsonify({'status': 'ok', 'message': 'Message saved'})

    else:
        # GET messages
        if messages_file.exists():
            with open(messages_file, 'r') as f:
                try:
                    messages = json.load(f)
                    return jsonify(messages)
                except:
                    return jsonify([])
        return jsonify([])

@app.route('/')
def index():
    """Serve marketplace HTML"""
    return send_from_directory('E:\\Downloads', 'marketplace.html')

if __name__ == '__main__':
    print('=' * 60)
    print('NEXUS MARKETPLACE API SERVER')
    print('=' * 60)
    print(f'API: http://localhost:8000')
    print(f'Data directory: {DATA_DIR}')
    print('=' * 60)
    print()

    port = int(os.environ.get('PORT', 5001))
    app.run(host='0.0.0.0', port=port, debug=True)
