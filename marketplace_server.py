"""
NEXUS Marketplace API Server
Multi-AI Chat Integration: Jacques, Mendel, Clouse
Serves card data and analytics for the marketplace frontend
"""

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
import json
import os
from datetime import datetime
from pathlib import Path

app = Flask(__name__)
CORS(app)

DATA_DIR = Path(__file__).parent / 'data'
DATA_DIR.mkdir(exist_ok=True)

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
    return send_from_directory('E:\\Downloads', 'marketplace.html')

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
