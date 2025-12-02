"""
NEXUS Marketplace API Server
Multi-AI Chat Integration: Jacques, Mendel, Clouse
Serves card data and analytics for the marketplace frontend
"""

from flask import Flask, jsonify, request, send_from_directory, send_file
from flask_cors import CORS
import json
import os
from datetime import datetime
from pathlib import Path
import requests
import time

app = Flask(__name__)
CORS(app)

DATA_DIR = Path(__file__).parent / 'data'
DATA_DIR.mkdir(exist_ok=True)
SCRYFALL_CACHE = DATA_DIR / 'scryfall_cache.json'

# Load Scryfall cache
scryfall_cache = {}
if SCRYFALL_CACHE.exists():
    with open(SCRYFALL_CACHE, 'r', encoding='utf-8') as f:
        scryfall_cache = json.load(f)

def save_scryfall_cache():
    with open(SCRYFALL_CACHE, 'w', encoding='utf-8') as f:
        json.dump(scryfall_cache, f, indent=2)
    print(f"💾 Scryfall cache saved: {len(scryfall_cache)} cards")

# ============================================
# AI PERSONALITIES
# ============================================

AI_CONFIGS = {
    'jacques': {
        'trigger': 'jacques',
        'name': 'jacques',
        'system_prompt': """You are Jacques, a skilled Python developer helping Kevin with his MTG card marketplace project. 
You're casual, helpful, and concise. Part of Kevin's dev squad."""
    },
    'mendel': {
        'trigger': 'mendel',
        'name': 'mendel', 
        'system_prompt': """You are Mendel, the VS Code AI in Kevin's dev squad. 
You're technical, efficient, and use tree emojis 🌲. You live in the IDE, write code, debug, deploy."""
    },
    'clouse': {
        'trigger': 'clouse',
        'name': 'clouse',
        'system_prompt': """You are Clouse, the browser agent AI in Kevin's dev squad. 
You navigate the web, scrape data, interact with websites. Keep responses short and action-oriented."""
    }
}

# ============================================
# SCRYFALL INTEGRATION
# ============================================

def fetch_from_scryfall(card_name, set_code=None):
    """Fetch card data from Scryfall with caching"""
    cache_key = f"{card_name}|{set_code or 'any'}".lower()
    
    # Check cache first
    if cache_key in scryfall_cache:
        cached = scryfall_cache[cache_key]
        if cached.get('timestamp', 0) > time.time() - (7 * 24 * 3600):  # 7 day cache
            return cached.get('data')
    
    try:
        # Scryfall API - named endpoint
        url = 'https://api.scryfall.com/cards/named'
        params = {'fuzzy': card_name}
        if set_code:
            params['set'] = set_code
        
        time.sleep(0.1)  # Rate limit: 10 req/sec max
        response = requests.get(url, params=params, timeout=5)
        
        if response.status_code == 200:
            data = response.json()
            result = {
                'image_url': data.get('image_uris', {}).get('normal', ''),
                'image_small': data.get('image_uris', {}).get('small', ''),
                'price': float(data.get('prices', {}).get('usd', 0) or 0),
                'price_foil': float(data.get('prices', {}).get('usd_foil', 0) or 0),
                'type_line': data.get('type_line', ''),
                'mana_cost': data.get('mana_cost', ''),
                'oracle_text': data.get('oracle_text', ''),
                'power': data.get('power', ''),
                'toughness': data.get('toughness', ''),
                'rarity': data.get('rarity', 'common'),
                'set_name': data.get('set_name', ''),
                'scryfall_id': data.get('id', ''),
                'colors': data.get('colors', []),
                'color_identity': data.get('color_identity', [])
            }
            
            # Cache the result
            scryfall_cache[cache_key] = {
                'data': result,
                'timestamp': time.time()
            }
            
            # Auto-save cache every 50 fetches
            if len(scryfall_cache) % 50 == 0:
                save_scryfall_cache()
            
            return result
    except Exception as e:
        print(f"⚠️  Scryfall fetch error for {card_name}: {e}")
    
    return None

def enrich_card(card):
    """Enrich a card with Scryfall data if missing image/price"""
    needs_enrichment = not card.get('image_url') or card.get('price', 0) == 0
    
    if needs_enrichment:
        scryfall_data = fetch_from_scryfall(card.get('name'), card.get('set'))
        if scryfall_data:
            card.update(scryfall_data)
    
    return card

# ============================================
# CARD DATA FUNCTIONS
# ============================================

def load_cards():
    """Load cards from nexus_library.json"""
    library_file = DATA_DIR / 'nexus_library.json'
    if library_file.exists():
        with open(library_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data
    return {}

def load_collection():
    """Load collection data - supports both library and box_inventory formats"""
    data = load_cards()
    cards = []
    
    # Format 1: library (from NEXUS export)
    library = data.get('library', {})
    if library:
        for call_number, card in library.items():
            if isinstance(card, dict):
                cards.append({
                    'name': card.get('name', 'Unknown'),
                    'set': card.get('set', 'UNK'),
                    'set_name': card.get('set_name', ''),
                    'rarity': card.get('rarity', 'common'),
                    'colors': card.get('colors', []),
                    'color_identity': card.get('color_identity', []),
                    'price': card.get('price', 0),
                    'box': card.get('box_id', ''),
                    'call_number': call_number,
                    'image_url': card.get('image_url', ''),
                    'type_line': card.get('type_line', ''),
                    'mana_cost': card.get('mana_cost', ''),
                    'oracle_text': card.get('oracle_text', ''),
                    'power': card.get('power', ''),
                    'toughness': card.get('toughness', ''),
                    'quantity': 1
                })
        return cards
    
    # Format 2: box_inventory (legacy format)
    box_inventory = data.get('box_inventory', {})
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

# ============================================
# AI FUNCTIONS
# ============================================

def get_ai_response(ai_name, user_message, conversation_context=""):
    """Call Anthropic API to get AI response"""
    try:
        import anthropic
        
        api_key = os.environ.get('ANTHROPIC_API_KEY')
        if not api_key:
            print("ERROR: No ANTHROPIC_API_KEY found")
            return None
            
        config = AI_CONFIGS.get(ai_name)
        if not config:
            print(f"ERROR: No config for AI '{ai_name}'")
            return None
        
        client = anthropic.Anthropic(api_key=api_key)
        
        # Build the prompt with context
        full_prompt = user_message
        if conversation_context:
            full_prompt = f"Recent chat:\n{conversation_context}\n\nLatest: {user_message}"
        
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=500,
            system=config['system_prompt'],
            messages=[{"role": "user", "content": full_prompt}]
        )
        
        return response.content[0].text
        
    except Exception as e:
        print(f"ERROR calling Anthropic API for {ai_name}: {e}")
        return None

def check_for_ai_triggers(message_text, author):
    """Check if message triggers any AI responses"""
    triggered_ais = []
    text_lower = message_text.lower()
    
    # @everyone triggers ALL AIs
    if '@everyone' in text_lower or 'everyone' in text_lower:
        for ai_name in AI_CONFIGS.keys():
            if author.lower() != ai_name:  # Don't let AI trigger itself
                triggered_ais.append(ai_name)
        return triggered_ais
    
    # Individual triggers
    for ai_name, config in AI_CONFIGS.items():
        # Don't let AI trigger itself
        if author.lower() == ai_name:
            continue
        # Check if trigger word is in message
        if config['trigger'] in text_lower:
            triggered_ais.append(ai_name)
    
    return triggered_ais

def get_recent_context(messages, limit=5):
    """Get recent messages for context"""
    recent = messages[-limit:] if len(messages) > limit else messages
    context_lines = []
    for msg in recent:
        author = msg.get('author', 'unknown')
        text = msg.get('text', '')
        context_lines.append(f"{author}: {text}")
    return "\n".join(context_lines)

# ============================================
# CARD ENDPOINTS
# ============================================

@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'healthy', 'timestamp': datetime.now().isoformat()})

@app.route('/status', methods=['GET'])
def status():
    """Server status"""
    cards = load_collection()
    return jsonify({
        'cards_in_db': len(cards),
        'uptime': 'running',
        'version': '2.0.0'
    })

@app.route('/cards/search', methods=['GET'])
def search_cards():
    """Search cards with filters and Scryfall enrichment"""
    cards = load_collection()

    # Apply filters from query params
    name_filter = request.args.get('name', '').lower()
    set_filter = request.args.get('set', '').lower()
    rarity_filter = request.args.get('rarity', '').lower()
    color_filter = request.args.get('color', '').lower()
    limit = int(request.args.get('limit', 1000))
    enrich = request.args.get('enrich', 'true').lower() == 'true'

    filtered = cards

    if name_filter:
        filtered = [c for c in filtered if name_filter in c['name'].lower()]
    if set_filter:
        filtered = [c for c in filtered if set_filter in c['set'].lower()]
    if rarity_filter:
        filtered = [c for c in filtered if rarity_filter in c['rarity'].lower()]
    if color_filter:
        filtered = [c for c in filtered if any(color_filter in str(col).lower() for col in c['colors'])]

    result_cards = filtered[:limit]
    
    # Enrich with Scryfall data (limit to 100 cards per request to avoid rate limits)
    if enrich and len(result_cards) <= 100:
        enriched = []
        for i, card in enumerate(result_cards):
            enriched_card = enrich_card(card)
            enriched.append(enriched_card)
            if (i + 1) % 10 == 0:
                print(f"📦 Enriched {i+1}/{len(result_cards)} cards...")
        result_cards = enriched
        save_scryfall_cache()

    return jsonify({
        'cards': result_cards,
        'total': len(filtered),
        'limit': limit,
        'enriched': enrich
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

# ============================================
# CHAT ENDPOINT
# ============================================

@app.route('/dev/messages', methods=['GET', 'POST'])
def dev_messages():
    """Developer chat endpoint with multi-AI support"""
    messages_file = DATA_DIR / 'messages.json'
    
    # Load existing messages
    messages = []
    if messages_file.exists():
        try:
            with open(messages_file, 'r') as f:
                messages = json.load(f)
        except:
            messages = []
    
    if request.method == 'GET':
        return jsonify(messages)
    
    # POST - new message
    if request.method == 'POST':
        try:
            if request.is_json:
                data = request.get_json()
            else:
                data = request.form.to_dict()
        except:
            data = {}
        
        # Handle different field names
        author = data.get('author') or data.get('sender') or 'Anonymous'
        text = data.get('text') or data.get('message') or ''
        
        print(f"📨 Received: author={author}, text='{text[:50]}...'")
        
        if not text:
            return jsonify({'status': 'error', 'message': 'Empty text'}), 400
        
        # Save the user message
        new_msg = {
            'author': author,
            'text': text,
            'time': datetime.now().strftime('%I:%M %p'),
            'datetime': datetime.now().isoformat()
        }
        messages.append(new_msg)
        
        # Check for AI triggers
        triggered_ais = check_for_ai_triggers(text, author)
        
        # Get AI responses
        for ai_name in triggered_ais:
            print(f"🤖 Triggering {ai_name}...")
            context = get_recent_context(messages)
            ai_response = get_ai_response(ai_name, text, context)
            
            if ai_response:
                ai_msg = {
                    'author': ai_name,
                    'text': ai_response,
                    'time': datetime.now().strftime('%I:%M %p'),
                    'datetime': datetime.now().isoformat()
                }
                messages.append(ai_msg)
                print(f"✅ {ai_name}: {ai_response[:50]}...")
        
        # Save all messages (keep last 100)
        with open(messages_file, 'w') as f:
            json.dump(messages[-100:], f, indent=2)
        
        return jsonify({'status': 'ok', 'ai_triggered': triggered_ais})

@app.route('/')
def index():
    """Serve marketplace HTML"""
    html_path = Path(__file__).parent / 'marketplace.html'
    if html_path.exists():
        return send_file(html_path)
    return jsonify({'error': 'marketplace.html not found'}), 404

# ============================================
# MCP ENDPOINT
# ============================================

@app.route('/mcp', methods=['POST'])
def mcp_handler():
    """Model Context Protocol handler"""
    data = request.get_json()
    method = data.get('method', '')
    
    if method == 'tools/list':
        return jsonify({
            'tools': [
                {'name': 'search_cards', 'description': 'Search MTG cards in collection'},
                {'name': 'get_analytics', 'description': 'Get collection analytics'},
                {'name': 'send_chat', 'description': 'Send message to dev chat'}
            ]
        })
    
    if method == 'tools/call':
        tool = data.get('params', {}).get('name')
        args = data.get('params', {}).get('arguments', {})
        
        if tool == 'search_cards':
            cards = load_collection()
            query = args.get('query', '').lower()
            results = [c for c in cards if query in c['name'].lower()][:20]
            return jsonify({'result': results})
        
        if tool == 'get_analytics':
            cards = load_collection()
            return jsonify({'result': {
                'total': len(cards),
                'value': sum(c['price'] for c in cards)
            }})
        
        if tool == 'send_chat':
            # Trigger chat endpoint
            return jsonify({'result': 'Message sent'})
    
    return jsonify({'error': 'Unknown method'}), 400

# ============================================
# RUN
# ============================================

if __name__ == '__main__':
    print('=' * 60)
    print('NEXUS MARKETPLACE API SERVER v2.0')
    print('Multi-AI: Jacques, Mendel, Clouse')
    print('=' * 60)
    print(f'Data directory: {DATA_DIR}')
    print('=' * 60)
    print()

    port = int(os.environ.get('PORT', 5001))
    app.run(host='0.0.0.0', port=port, debug=True)
