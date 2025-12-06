"""
NEXUS Marketplace API Server v3.0
Multi-Seller Platform with Cart & Checkout

Features:
- Multi-seller support with API key authentication
- Real-time listing sync from NEXUS V2 desktop
- Shopping cart (session-based)
- Order management
- Scryfall enrichment

Endpoints:
  PUBLIC:
    GET  /                      - Marketplace frontend
    GET  /api/listings          - Browse all active listings
    GET  /api/listings/<id>     - Single listing details
    GET  /api/sellers           - List sellers
    GET  /api/cart              - View cart (cookie session)
    POST /api/cart/add          - Add to cart
    POST /api/cart/remove       - Remove from cart
    POST /api/cart/clear        - Clear cart
    POST /api/checkout          - Create order
    
  SELLER (API Key Required):
    POST /api/seller/register   - Register new seller
    POST /api/seller/sync       - Sync listings from V2
    GET  /api/seller/listings   - View own listings
    GET  /api/seller/orders     - View incoming orders
    POST /api/seller/order/<id>/update - Update order status
"""

from flask import Flask, jsonify, request, send_file, session, make_response
from flask_cors import CORS
import json
import os
import uuid
import hashlib
import secrets
from datetime import datetime, timedelta
from pathlib import Path
import requests
import time
from functools import wraps

app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', secrets.token_hex(32))
CORS(app, supports_credentials=True)

# ============================================
# DATA STORAGE
# ============================================

DATA_DIR = Path(__file__).parent / 'data'
DATA_DIR.mkdir(exist_ok=True)

SELLERS_FILE = DATA_DIR / 'sellers.json'
LISTINGS_FILE = DATA_DIR / 'listings.json'
ORDERS_FILE = DATA_DIR / 'orders.json'
CARTS_FILE = DATA_DIR / 'carts.json'
SCRYFALL_CACHE = DATA_DIR / 'scryfall_cache.json'

def load_json(filepath, default=None):
    """Load JSON file with default fallback"""
    if default is None:
        default = {}
    if filepath.exists():
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            pass
    return default

def save_json(filepath, data):
    """Save data to JSON file"""
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, default=str)

# Load initial data
sellers = load_json(SELLERS_FILE, {})
listings = load_json(LISTINGS_FILE, [])
orders = load_json(ORDERS_FILE, [])
carts = load_json(CARTS_FILE, {})
scryfall_cache = load_json(SCRYFALL_CACHE, {})

# ============================================
# AUTHENTICATION
# ============================================

def require_api_key(f):
    """Decorator to require valid seller API key"""
    @wraps(f)
    def decorated(*args, **kwargs):
        api_key = request.headers.get('X-API-Key') or request.args.get('api_key')
        if not api_key:
            return jsonify({'error': 'API key required'}), 401
        
        # Find seller by API key
        seller = None
        for seller_id, s in sellers.items():
            if s.get('api_key') == api_key:
                seller = s
                seller['id'] = seller_id
                break
        
        if not seller:
            return jsonify({'error': 'Invalid API key'}), 401
        
        # Inject seller into request context
        request.seller = seller
        return f(*args, **kwargs)
    return decorated

def get_or_create_cart_id():
    """Get cart ID from cookie or create new one"""
    cart_id = request.cookies.get('cart_id')
    if not cart_id or cart_id not in carts:
        cart_id = str(uuid.uuid4())
        carts[cart_id] = {'items': [], 'created': datetime.now().isoformat()}
        save_json(CARTS_FILE, carts)
    return cart_id

# ============================================
# SCRYFALL INTEGRATION
# ============================================

def fetch_from_scryfall(card_name, set_code=None):
    """Fetch card data from Scryfall with caching"""
    cache_key = f"{card_name}|{set_code or 'any'}".lower()
    
    if cache_key in scryfall_cache:
        cached = scryfall_cache[cache_key]
        if cached.get('timestamp', 0) > time.time() - (7 * 24 * 3600):
            return cached.get('data')
    
    try:
        url = 'https://api.scryfall.com/cards/named'
        params = {'fuzzy': card_name}
        if set_code:
            params['set'] = set_code
        
        time.sleep(0.1)
        response = requests.get(url, params=params, timeout=5)
        
        if response.status_code == 200:
            data = response.json()
            result = {
                'image_url': data.get('image_uris', {}).get('normal', ''),
                'image_small': data.get('image_uris', {}).get('small', ''),
                'scryfall_price': float(data.get('prices', {}).get('usd', 0) or 0),
                'type_line': data.get('type_line', ''),
                'mana_cost': data.get('mana_cost', ''),
                'oracle_text': data.get('oracle_text', ''),
                'rarity': data.get('rarity', 'common'),
                'set_name': data.get('set_name', ''),
                'colors': data.get('colors', []),
            }
            
            scryfall_cache[cache_key] = {'data': result, 'timestamp': time.time()}
            if len(scryfall_cache) % 50 == 0:
                save_json(SCRYFALL_CACHE, scryfall_cache)
            
            return result
    except Exception as e:
        print(f"Scryfall error for {card_name}: {e}")
    
    return None

def enrich_listing(listing):
    """Enrich listing with Scryfall data if needed"""
    if not listing.get('image_url'):
        scryfall_data = fetch_from_scryfall(listing.get('card_name'), listing.get('set_code'))
        if scryfall_data:
            listing.update({
                'image_url': scryfall_data.get('image_url', ''),
                'image_small': scryfall_data.get('image_small', ''),
                'type_line': scryfall_data.get('type_line', ''),
                'mana_cost': scryfall_data.get('mana_cost', ''),
                'rarity': scryfall_data.get('rarity', 'common'),
                'set_name': scryfall_data.get('set_name', ''),
                'colors': scryfall_data.get('colors', []),
            })
    return listing

# ============================================
# PUBLIC ENDPOINTS
# ============================================

@app.route('/')
def index():
    """Serve marketplace frontend"""
    html_path = Path(__file__).parent / 'marketplace.html'
    if html_path.exists():
        return send_file(html_path)
    return jsonify({'error': 'Frontend not found'}), 404

@app.route('/brand_icon.jpg')
def brand_icon():
    """Serve brand icon"""
    icon_path = Path(__file__).parent / 'brand_icon.jpg'
    if icon_path.exists():
        return send_file(icon_path, mimetype='image/jpeg')
    return '', 404

@app.route('/health')
def health():
    return jsonify({'status': 'healthy', 'version': '3.0.0', 'timestamp': datetime.now().isoformat()})

@app.route('/status')
def status():
    active_listings = [l for l in listings if l.get('status') == 'Active']
    return jsonify({
        'total_listings': len(active_listings),
        'total_sellers': len(sellers),
        'version': '3.0.0'
    })

@app.route('/api/listings')
def get_listings():
    """Get all active listings with optional filters"""
    active = [l for l in listings if l.get('status') == 'Active']
    
    # Filters
    name = request.args.get('name', '').lower()
    set_code = request.args.get('set', '').lower()
    seller_id = request.args.get('seller')
    min_price = request.args.get('min_price', type=float)
    max_price = request.args.get('max_price', type=float)
    rarity = request.args.get('rarity', '').lower()
    limit = request.args.get('limit', 100, type=int)
    offset = request.args.get('offset', 0, type=int)
    
    filtered = active
    
    if name:
        filtered = [l for l in filtered if name in l.get('card_name', '').lower()]
    if set_code:
        filtered = [l for l in filtered if set_code in l.get('set_code', '').lower()]
    if seller_id:
        filtered = [l for l in filtered if l.get('seller_id') == seller_id]
    if min_price is not None:
        filtered = [l for l in filtered if l.get('price', 0) >= min_price]
    if max_price is not None:
        filtered = [l for l in filtered if l.get('price', 0) <= max_price]
    if rarity:
        filtered = [l for l in filtered if rarity in l.get('rarity', '').lower()]
    
    # Add seller info to each listing and enrich with Scryfall data
    for listing in filtered:
        seller = sellers.get(listing.get('seller_id', ''), {})
        listing['seller_name'] = seller.get('shop_name', 'Unknown Seller')
        # Enrich with image if missing
        if not listing.get('image_url'):
            enrich_listing(listing)
    
    total = len(filtered)
    paginated = filtered[offset:offset + limit]
    
    return jsonify({
        'listings': paginated,
        'total': total,
        'offset': offset,
        'limit': limit
    })

@app.route('/api/listings/<listing_id>')
def get_listing(listing_id):
    """Get single listing details"""
    listing = next((l for l in listings if l.get('id') == listing_id), None)
    if not listing:
        return jsonify({'error': 'Listing not found'}), 404
    
    # Enrich with Scryfall data
    listing = enrich_listing(listing)
    
    # Add seller info
    seller = sellers.get(listing.get('seller_id', ''), {})
    listing['seller_name'] = seller.get('shop_name', 'Unknown Seller')
    listing['seller_location'] = seller.get('location', '')
    
    return jsonify(listing)

@app.route('/api/sellers')
def get_sellers():
    """List all active sellers"""
    seller_list = []
    for seller_id, s in sellers.items():
        seller_listings = [l for l in listings if l.get('seller_id') == seller_id and l.get('status') == 'Active']
        seller_list.append({
            'id': seller_id,
            'shop_name': s.get('shop_name'),
            'location': s.get('location', ''),
            'listing_count': len(seller_listings),
            'joined': s.get('created', '')[:10]
        })
    return jsonify({'sellers': seller_list})

# ============================================
# CART ENDPOINTS
# ============================================

@app.route('/api/cart')
def get_cart():
    """Get current cart contents"""
    cart_id = get_or_create_cart_id()
    cart = carts.get(cart_id, {'items': []})
    
    # Enrich cart items with current listing data
    enriched_items = []
    total = 0
    
    for item in cart.get('items', []):
        listing = next((l for l in listings if l.get('id') == item.get('listing_id')), None)
        if listing and listing.get('status') == 'Active':
            qty = item.get('quantity', 1)
            price = listing.get('price', 0)
            enriched_items.append({
                'listing_id': listing['id'],
                'card_name': listing.get('card_name'),
                'set_code': listing.get('set_code'),
                'condition': listing.get('condition'),
                'price': price,
                'quantity': qty,
                'subtotal': price * qty,
                'image_url': listing.get('image_url', ''),
                'seller_name': sellers.get(listing.get('seller_id', ''), {}).get('shop_name', 'Unknown')
            })
            total += price * qty
    
    response = make_response(jsonify({
        'items': enriched_items,
        'item_count': len(enriched_items),
        'total': round(total, 2)
    }))
    response.set_cookie('cart_id', cart_id, max_age=7*24*3600, samesite='Lax')
    return response

@app.route('/api/cart/add', methods=['POST'])
def add_to_cart():
    """Add item to cart"""
    cart_id = get_or_create_cart_id()
    data = request.get_json() or {}
    
    listing_id = data.get('listing_id')
    quantity = data.get('quantity', 1)
    
    if not listing_id:
        return jsonify({'error': 'listing_id required'}), 400
    
    # Verify listing exists and is active
    listing = next((l for l in listings if l.get('id') == listing_id and l.get('status') == 'Active'), None)
    if not listing:
        return jsonify({'error': 'Listing not available'}), 404
    
    # Check quantity available
    available = listing.get('quantity', 1)
    
    # Get or create cart
    cart = carts.get(cart_id, {'items': []})
    
    # Check if already in cart
    existing = next((i for i in cart['items'] if i.get('listing_id') == listing_id), None)
    if existing:
        new_qty = existing['quantity'] + quantity
        if new_qty > available:
            return jsonify({'error': f'Only {available} available'}), 400
        existing['quantity'] = new_qty
    else:
        if quantity > available:
            return jsonify({'error': f'Only {available} available'}), 400
        cart['items'].append({'listing_id': listing_id, 'quantity': quantity})
    
    carts[cart_id] = cart
    save_json(CARTS_FILE, carts)
    
    response = make_response(jsonify({'success': True, 'message': 'Added to cart'}))
    response.set_cookie('cart_id', cart_id, max_age=7*24*3600, samesite='Lax')
    return response

@app.route('/api/cart/remove', methods=['POST'])
def remove_from_cart():
    """Remove item from cart"""
    cart_id = get_or_create_cart_id()
    data = request.get_json() or {}
    listing_id = data.get('listing_id')
    
    if cart_id in carts:
        carts[cart_id]['items'] = [i for i in carts[cart_id].get('items', []) if i.get('listing_id') != listing_id]
        save_json(CARTS_FILE, carts)
    
    return jsonify({'success': True})

@app.route('/api/cart/clear', methods=['POST'])
def clear_cart():
    """Clear entire cart"""
    cart_id = get_or_create_cart_id()
    if cart_id in carts:
        carts[cart_id]['items'] = []
        save_json(CARTS_FILE, carts)
    return jsonify({'success': True})

@app.route('/api/checkout', methods=['POST'])
def checkout():
    """Create order from cart"""
    cart_id = get_or_create_cart_id()
    cart = carts.get(cart_id, {'items': []})
    
    if not cart.get('items'):
        return jsonify({'error': 'Cart is empty'}), 400
    
    data = request.get_json() or {}
    buyer_email = data.get('email')
    buyer_name = data.get('name')
    shipping_address = data.get('shipping_address')
    
    if not buyer_email or not buyer_name:
        return jsonify({'error': 'Name and email required'}), 400
    
    # Group items by seller
    seller_orders = {}
    for item in cart['items']:
        listing = next((l for l in listings if l.get('id') == item['listing_id']), None)
        if listing:
            seller_id = listing.get('seller_id')
            if seller_id not in seller_orders:
                seller_orders[seller_id] = []
            seller_orders[seller_id].append({
                'listing_id': listing['id'],
                'card_name': listing.get('card_name'),
                'set_code': listing.get('set_code'),
                'condition': listing.get('condition'),
                'price': listing.get('price'),
                'quantity': item.get('quantity', 1)
            })
    
    # Create order for each seller
    created_orders = []
    for seller_id, items in seller_orders.items():
        order_total = sum(i['price'] * i['quantity'] for i in items)
        order = {
            'id': f"ORD-{uuid.uuid4().hex[:8].upper()}",
            'seller_id': seller_id,
            'buyer_name': buyer_name,
            'buyer_email': buyer_email,
            'shipping_address': shipping_address,
            'items': items,
            'total': round(order_total, 2),
            'status': 'pending',
            'created': datetime.now().isoformat(),
            'updated': datetime.now().isoformat()
        }
        orders.append(order)
        created_orders.append(order['id'])
        
        # Mark listings as reserved/sold
        for item in items:
            for listing in listings:
                if listing['id'] == item['listing_id']:
                    listing['quantity'] = listing.get('quantity', 1) - item['quantity']
                    if listing['quantity'] <= 0:
                        listing['status'] = 'Sold'
    
    save_json(ORDERS_FILE, orders)
    save_json(LISTINGS_FILE, listings)
    
    # Clear cart
    carts[cart_id]['items'] = []
    save_json(CARTS_FILE, carts)
    
    return jsonify({
        'success': True,
        'order_ids': created_orders,
        'message': 'Order placed! Seller will contact you with payment details.'
    })

# ============================================
# SELLER ENDPOINTS
# ============================================

@app.route('/api/seller/register', methods=['POST'])
def register_seller():
    """Register a new seller account"""
    data = request.get_json() or {}
    
    shop_name = data.get('shop_name')
    email = data.get('email')
    location = data.get('location', '')
    
    if not shop_name or not email:
        return jsonify({'error': 'shop_name and email required'}), 400
    
    # Check if email already registered
    for s in sellers.values():
        if s.get('email') == email:
            return jsonify({'error': 'Email already registered'}), 400
    
    # Generate seller ID and API key
    seller_id = f"SELLER-{uuid.uuid4().hex[:8].upper()}"
    api_key = f"nxs_{secrets.token_hex(24)}"
    
    sellers[seller_id] = {
        'shop_name': shop_name,
        'email': email,
        'location': location,
        'api_key': api_key,
        'created': datetime.now().isoformat(),
        'status': 'active'
    }
    save_json(SELLERS_FILE, sellers)
    
    return jsonify({
        'success': True,
        'seller_id': seller_id,
        'api_key': api_key,
        'message': 'Store this API key securely - it will not be shown again!'
    })

@app.route('/api/seller/sync', methods=['POST'])
@require_api_key
def sync_listings():
    """Sync listings from V2 desktop app"""
    global listings
    
    data = request.get_json() or {}
    incoming_listings = data.get('listings', [])
    mode = data.get('mode', 'merge')  # 'merge' or 'replace'
    
    seller_id = request.seller['id']
    
    if mode == 'replace':
        # Remove all existing listings from this seller
        listings = [l for l in listings if l.get('seller_id') != seller_id]
    
    # Process incoming listings
    added = 0
    updated = 0
    
    for incoming in incoming_listings:
        # Generate listing ID if not present
        if not incoming.get('id'):
            incoming['id'] = f"LST-{uuid.uuid4().hex[:8].upper()}"
        
        # Set seller ID
        incoming['seller_id'] = seller_id
        incoming['synced_at'] = datetime.now().isoformat()
        
        # Enrich with Scryfall image if not provided
        if not incoming.get('image_url'):
            enrich_listing(incoming)
        
        # Check if listing already exists (by ID or by card+condition+seller)
        existing = next((l for l in listings if l.get('id') == incoming.get('id') or 
                        (l.get('card_name') == incoming.get('card_name') and 
                         l.get('condition') == incoming.get('condition') and
                         l.get('seller_id') == seller_id)), None)
        
        if existing:
            # Update existing
            existing.update(incoming)
            updated += 1
        else:
            # Add new
            listings.append(incoming)
            added += 1
    
    save_json(LISTINGS_FILE, listings)
    
    return jsonify({
        'success': True,
        'added': added,
        'updated': updated,
        'total_listings': len([l for l in listings if l.get('seller_id') == seller_id])
    })

@app.route('/api/seller/listings')
@require_api_key
def seller_listings():
    """Get seller's own listings"""
    seller_id = request.seller['id']
    my_listings = [l for l in listings if l.get('seller_id') == seller_id]
    
    return jsonify({
        'listings': my_listings,
        'total': len(my_listings),
        'active': len([l for l in my_listings if l.get('status') == 'Active']),
        'sold': len([l for l in my_listings if l.get('status') == 'Sold'])
    })

@app.route('/api/seller/orders')
@require_api_key
def seller_orders():
    """Get seller's incoming orders"""
    seller_id = request.seller['id']
    my_orders = [o for o in orders if o.get('seller_id') == seller_id]
    
    # Sort by date descending
    my_orders.sort(key=lambda x: x.get('created', ''), reverse=True)
    
    return jsonify({
        'orders': my_orders,
        'total': len(my_orders),
        'pending': len([o for o in my_orders if o.get('status') == 'pending']),
        'completed': len([o for o in my_orders if o.get('status') == 'completed'])
    })

@app.route('/api/seller/order/<order_id>/update', methods=['POST'])
@require_api_key
def update_order(order_id):
    """Update order status"""
    seller_id = request.seller['id']
    data = request.get_json() or {}
    new_status = data.get('status')
    tracking = data.get('tracking')
    
    order = next((o for o in orders if o.get('id') == order_id and o.get('seller_id') == seller_id), None)
    if not order:
        return jsonify({'error': 'Order not found'}), 404
    
    if new_status:
        order['status'] = new_status
    if tracking:
        order['tracking'] = tracking
    order['updated'] = datetime.now().isoformat()
    
    save_json(ORDERS_FILE, orders)
    
    return jsonify({'success': True, 'order': order})

# ============================================
# LEGACY ENDPOINTS (for backward compatibility)
# ============================================

@app.route('/cards/search')
def legacy_search():
    """Legacy endpoint - redirect to new API"""
    return get_listings()

@app.route('/analytics/summary')
def analytics_summary():
    """Collection analytics"""
    active = [l for l in listings if l.get('status') == 'Active']
    total_value = sum(l.get('price', 0) * l.get('quantity', 1) for l in active)
    
    return jsonify({
        'total_value': round(total_value, 2),
        'total_listings': len(active),
        'unique_cards': len(set(l.get('card_name') for l in active)),
        'total_sellers': len(sellers)
    })

# ============================================
# DEV CHAT (kept for compatibility)
# ============================================

@app.route('/dev/messages', methods=['GET', 'POST'])
def dev_messages():
    """Developer chat endpoint"""
    messages_file = DATA_DIR / 'messages.json'
    messages = load_json(messages_file, [])
    
    if request.method == 'GET':
        return jsonify(messages)
    
    data = request.get_json() or request.form.to_dict() or {}
    author = data.get('author') or data.get('sender') or 'Anonymous'
    text = data.get('text') or data.get('message') or ''
    
    if text:
        messages.append({
            'author': author,
            'text': text,
            'time': datetime.now().strftime('%I:%M %p'),
            'datetime': datetime.now().isoformat()
        })
        save_json(messages_file, messages[-100:])
    
    return jsonify({'status': 'ok'})

# ============================================
# HEALTHZ FOR RENDER
# ============================================

@app.route('/healthz')
def healthz():
    return 'OK', 200

# ============================================
# RUN
# ============================================

if __name__ == '__main__':
    print('=' * 60)
    print('NEXUS MARKETPLACE API v3.0')
    print('Multi-Seller Platform with Cart & Checkout')
    print('=' * 60)
    print(f'Sellers: {len(sellers)}')
    print(f'Listings: {len(listings)}')
    print(f'Orders: {len(orders)}')
    print('=' * 60)
    
    port = int(os.environ.get('PORT', 5001))
    app.run(host='0.0.0.0', port=port, debug=True)
