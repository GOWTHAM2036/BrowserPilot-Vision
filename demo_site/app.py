"""Deterministic Demo Laptop Shopping Website built with Flask and In-Memory Cart."""

from __future__ import annotations

import os
from typing import Any, Dict, List
from flask import Flask, jsonify, redirect, render_template_string, request, url_for


app = Flask(__name__)

# Deterministic laptop product catalog
PRODUCTS: List[Dict[str, Any]] = [
    {
        "id": 1,
        "name": "StudentLite Chromebook 11",
        "category": "Chromebook",
        "price": 199.00,
        "cpu": "MediaTek MT8183",
        "ram": "4GB",
        "storage": "64GB eMMC",
        "display": "11.6-inch HD",
        "in_stock": True,
        "description": "Affordable and lightweight Chromebook designed for students and basic web browsing.",
    },
    {
        "id": 2,
        "name": "BudgetBook Essential 14",
        "category": "Budget",
        "price": 349.00,
        "cpu": "Intel Celeron N4500",
        "ram": "8GB",
        "storage": "128GB SSD",
        "display": "14-inch FHD",
        "in_stock": True,
        "description": "Dependable everyday laptop for productivity, document editing, and online learning.",
    },
    {
        "id": 3,
        "name": "UltraBook Swift 13",
        "category": "Ultrabook",
        "price": 499.00,
        "cpu": "Intel Core i3-1215U",
        "ram": "8GB",
        "storage": "256GB NVMe SSD",
        "display": "13.3-inch FHD IPS",
        "in_stock": True,
        "description": "Ultra-slim, portable laptop with vivid display and fast all-day performance.",
    },
    {
        "id": 4,
        "name": "EcoBook Air 13",
        "category": "Ultrabook",
        "price": 649.00,
        "cpu": "AMD Ryzen 5 5500U",
        "ram": "16GB",
        "storage": "512GB NVMe SSD",
        "display": "13.5-inch 2K IPS",
        "in_stock": True,
        "description": "Energy-efficient aluminum laptop with sustainable materials and all-day battery life.",
    },
    {
        "id": 5,
        "name": "ProBook Performance 15",
        "category": "Professional",
        "price": 899.00,
        "cpu": "Intel Core i7-1260P",
        "ram": "16GB",
        "storage": "1TB NVMe SSD",
        "display": "15.6-inch FHD 100% sRGB",
        "in_stock": True,
        "description": "Heavy-duty workstation laptop built for developers, designers, and business tasks.",
    },
    {
        "id": 6,
        "name": "Gaming Titan RTX 16",
        "category": "Gaming",
        "price": 1299.00,
        "cpu": "Intel Core i9-12900H",
        "ram": "32GB",
        "storage": "1TB Gen4 NVMe SSD",
        "display": "16-inch QHD 165Hz",
        "in_stock": True,
        "description": "High-octane gaming beast equipped with dedicated NVIDIA GeForce RTX graphics.",
    },
]

# In-memory shopping cart
CART_ITEMS: List[Dict[str, Any]] = []


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Demo Laptop Store - BrowserPilot Vision</title>
    <style>
        :root {
            --primary: #2563eb;
            --primary-dark: #1d4ed8;
            --bg: #f8fafc;
            --card-bg: #ffffff;
            --text: #0f172a;
            --text-muted: #64748b;
            --border: #e2e8f0;
            --badge-bg: #dcfce7;
            --badge-text: #166534;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            background-color: var(--bg);
            color: var(--text);
            line-height: 1.5;
            padding: 24px;
        }
        .container { max-width: 1000px; margin: 0 auto; }
        header {
            margin-bottom: 24px;
            padding-bottom: 16px;
            border-bottom: 2px solid var(--border);
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        h1 { font-size: 1.8rem; font-weight: 700; color: var(--text); }
        p.subtitle { color: var(--text-muted); font-size: 0.95rem; }
        .cart-link {
            padding: 8px 16px;
            background: #2563eb;
            color: white;
            text-decoration: none;
            border-radius: 6px;
            font-weight: 600;
        }
        .cart-link:hover { background: #1d4ed8; }
        .banner {
            background: #dcfce7;
            color: #166534;
            padding: 12px 16px;
            border-radius: 6px;
            margin-bottom: 16px;
            border: 1px solid #86efac;
            font-weight: 500;
        }
        .controls {
            display: flex;
            flex-wrap: wrap;
            gap: 12px;
            margin-bottom: 20px;
            background: var(--card-bg);
            padding: 16px;
            border-radius: 8px;
            border: 1px solid var(--border);
            align-items: center;
        }
        .search-form { display: flex; gap: 8px; flex: 1; min-width: 280px; }
        input[type="text"] {
            flex: 1;
            padding: 10px 14px;
            border: 1px solid var(--border);
            border-radius: 6px;
            font-size: 0.95rem;
        }
        button {
            padding: 10px 18px;
            background-color: var(--primary);
            color: white;
            border: none;
            border-radius: 6px;
            font-weight: 600;
            cursor: pointer;
            transition: background 0.15s ease;
        }
        button:hover { background-color: var(--primary-dark); }
        .sort-links { display: flex; gap: 8px; align-items: center; }
        .sort-links a {
            padding: 8px 12px;
            background: #f1f5f9;
            color: var(--text);
            text-decoration: none;
            border-radius: 6px;
            font-size: 0.85rem;
            font-weight: 500;
        }
        .sort-links a.active {
            background: var(--primary);
            color: white;
        }
        .summary-bar {
            margin-bottom: 16px;
            padding: 12px 16px;
            background: #eff6ff;
            border: 1px solid #bfdbfe;
            border-radius: 6px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .cheapest-badge {
            background: var(--badge-bg);
            color: var(--badge-text);
            padding: 4px 10px;
            border-radius: 20px;
            font-size: 0.85rem;
            font-weight: 600;
        }
        .product-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(290px, 1fr));
            gap: 16px;
        }
        .product-card {
            background: var(--card-bg);
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 18px;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
        }
        .product-card.cheapest-highlight {
            border: 2px solid #22c55e;
            box-shadow: 0 4px 6px -1px rgba(34, 197, 94, 0.15);
        }
        .product-title { font-size: 1.15rem; font-weight: 600; margin-bottom: 6px; }
        .product-category {
            font-size: 0.75rem;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            color: var(--primary);
            font-weight: 700;
            margin-bottom: 8px;
        }
        .product-specs { font-size: 0.85rem; color: var(--text-muted); margin-bottom: 12px; }
        .product-price { font-size: 1.35rem; font-weight: 700; color: #16a34a; }
        .card-footer {
            margin-top: 14px;
            display: flex;
            gap: 8px;
            justify-content: space-between;
            align-items: center;
        }
        .details-btn {
            padding: 6px 12px;
            background: #f8fafc;
            border: 1px solid var(--border);
            border-radius: 4px;
            font-size: 0.85rem;
            cursor: pointer;
            text-decoration: none;
            color: var(--text);
        }
        .add-cart-btn {
            background: #16a34a;
            color: white;
            border-color: #15803d;
        }
        .add-cart-btn:hover { background: #15803d; }
        .no-results {
            background: white;
            padding: 32px;
            text-align: center;
            border-radius: 8px;
            border: 1px solid var(--border);
            color: var(--text-muted);
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <div>
                <h1>Demo Laptop Store</h1>
                <p class="subtitle">Deterministic test website for BrowserPilot Vision automation</p>
            </div>
            <div>
                <a href="/cart" id="view-cart-link" class="cart-link" aria-label="Shopping Cart">
                    🛒 Cart (<span id="cart-count">{{ cart|length }}</span>)
                </a>
            </div>
        </header>

        {% if banner_msg %}
            <div class="banner" id="banner-message" role="status">{{ banner_msg }}</div>
        {% endif %}

        <section class="controls" aria-label="Search and Filter Controls">
            <form class="search-form" action="/" method="GET" role="search">
                <input
                    type="text"
                    id="search-input"
                    name="q"
                    value="{{ query }}"
                    placeholder="Search laptops by name, CPU, or category..."
                    aria-label="Search laptops"
                />
                <button type="submit" id="search-btn" aria-label="Search">Search</button>
                {% if query %}
                    <a href="/" class="details-btn" id="clear-btn">Clear</a>
                {% endif %}
            </form>

            <div class="sort-links" aria-label="Sorting Options">
                <span>Sort:</span>
                <a href="/?q={{ query }}&sort=price_asc" id="sort-price-asc" class="{% if sort_by == 'price_asc' %}active{% endif %}">Price: Low to High</a>
                <a href="/?q={{ query }}&sort=price_desc" id="sort-price-desc" class="{% if sort_by == 'price_desc' %}active{% endif %}">Price: High to Low</a>
            </div>
        </section>

        {% if products %}
            <div class="summary-bar" id="search-summary" aria-label="Catalog Summary">
                <span>Showing <strong>{{ products|length }}</strong> product(s)</span>
                {% if cheapest %}
                    <span class="cheapest-badge" id="cheapest-badge" aria-label="Cheapest Product Match">
                        Cheapest Match: <strong>{{ cheapest.name }}</strong> at <strong>${{ "%.2f"|format(cheapest.price) }}</strong>
                    </span>
                {% endif %}
            </div>

            <main class="product-grid" aria-label="Product Catalog">
                {% for p in products %}
                    <article class="product-card {% if cheapest and p.id == cheapest.id %}cheapest-highlight{% endif %}" id="product-{{ p.id }}" data-id="{{ p.id }}">
                        <div class="product-category">{{ p.category }}</div>
                        <h2 class="product-title">{{ p.name }}</h2>
                        <p class="product-specs">{{ p.cpu }} &bull; {{ p.ram }} &bull; {{ p.storage }} &bull; {{ p.display }}</p>
                        <div class="card-footer">
                            <span class="product-price" id="price-{{ p.id }}">${{ "%.2f"|format(p.price) }}</span>
                            <div style="display:flex; gap:6px;">
                                <a href="/product/{{ p.id }}" class="details-btn" id="details-btn-{{ p.id }}" aria-label="View Details for {{ p.name }}">View Details</a>
                                <a href="/cart/add/{{ p.id }}" class="details-btn add-cart-btn" id="add-to-cart-{{ p.id }}" aria-label="Add {{ p.name }} to Cart">Add to Cart</a>
                            </div>
                        </div>
                    </article>
                {% endfor %}
            </main>
        {% else %}
            <div class="no-results" id="no-results">
                <h2>No products found</h2>
                <p>No laptops matched your search query "{{ query }}".</p>
                <p style="margin-top: 12px;"><a href="/" class="details-btn">View All Laptops</a></p>
            </div>
        {% endif %}
    </div>
</body>
</html>
"""

DETAIL_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>{{ product.name }} - Demo Laptop Store</title>
    <style>
        body { font-family: sans-serif; background: #f8fafc; color: #0f172a; padding: 24px; }
        .container { max-width: 800px; margin: 0 auto; background: white; padding: 24px; border-radius: 8px; border: 1px solid #e2e8f0; }
        h1 { margin-bottom: 8px; }
        .price { font-size: 1.5rem; color: #16a34a; font-weight: bold; margin-bottom: 16px; }
        .specs { margin-bottom: 16px; line-height: 1.8; }
        .actions { margin-top: 20px; display: flex; gap: 12px; }
        .back-link { padding: 8px 16px; background: #2563eb; color: white; text-decoration: none; border-radius: 6px; }
        .add-cart-link { padding: 8px 16px; background: #16a34a; color: white; text-decoration: none; border-radius: 6px; font-weight: 600; }
    </style>
</head>
<body>
    <div class="container">
        <a href="/" id="back-home">&larr; Back to Laptop Catalog</a>
        <h1 style="margin-top: 16px;">{{ product.name }}</h1>
        <div class="price" id="detail-price">${{ "%.2f"|format(product.price) }}</div>
        <p>{{ product.description }}</p>
        <div class="specs" style="margin-top: 16px;">
            <p><strong>CPU:</strong> {{ product.cpu }}</p>
            <p><strong>RAM:</strong> {{ product.ram }}</p>
            <p><strong>Storage:</strong> {{ product.storage }}</p>
            <p><strong>Display:</strong> {{ product.display }}</p>
            <p><strong>Status:</strong> {% if product.in_stock %}In Stock{% else %}Out of Stock{% endif %}</p>
        </div>
        <div class="actions">
            <a href="/cart/add/{{ product.id }}" class="add-cart-link" id="add-to-cart-detail">Add to Cart</a>
            <a href="/cart" class="back-link" style="background:#64748b;" id="view-cart-from-detail">View Cart</a>
        </div>
    </div>
</body>
</html>
"""

CART_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Shopping Cart - Demo Laptop Store</title>
    <style>
        body { font-family: sans-serif; background: #f8fafc; color: #0f172a; padding: 24px; }
        .container { max-width: 800px; margin: 0 auto; background: white; padding: 24px; border-radius: 8px; border: 1px solid #e2e8f0; }
        h1 { margin-bottom: 16px; border-bottom: 2px solid #e2e8f0; padding-bottom: 12px; }
        .cart-table { width: 100%; border-collapse: collapse; margin-bottom: 24px; }
        .cart-table th, .cart-table td { padding: 12px; text-align: left; border-bottom: 1px solid #e2e8f0; }
        .total-row { font-size: 1.2rem; font-weight: bold; color: #16a34a; }
        .btn { display: inline-block; padding: 8px 16px; border-radius: 6px; text-decoration: none; font-weight: 600; }
        .btn-primary { background: #2563eb; color: white; }
        .btn-secondary { background: #e2e8f0; color: #334155; }
        .banner { background: #dcfce7; color: #166534; padding: 12px 16px; border-radius: 6px; margin-bottom: 16px; border: 1px solid #86efac; font-weight: 500; }
    </style>
</head>
<body>
    <div class="container">
        <h1>Your Shopping Cart</h1>
        {% if added_name %}
            <div class="banner" id="cart-banner">Successfully added <strong>{{ added_name }}</strong> to your cart!</div>
        {% endif %}

        {% if cart %}
            <table class="cart-table" id="cart-table">
                <thead>
                    <tr>
                        <th>Product</th>
                        <th>Price</th>
                        <th>Category</th>
                    </tr>
                </thead>
                <tbody>
                    {% for item in cart %}
                        <tr class="cart-item" id="cart-item-{{ item.id }}">
                            <td class="cart-item-name"><strong>{{ item.name }}</strong></td>
                            <td class="cart-item-price">${{ "%.2f"|format(item.price) }}</td>
                            <td>{{ item.category }}</td>
                        </tr>
                    {% endfor %}
                    <tr class="total-row">
                        <td>Total</td>
                        <td id="cart-total">${{ "%.2f"|format(total) }}</td>
                        <td></td>
                    </tr>
                </tbody>
            </table>
            <div style="display:flex; justify-content:space-between; align-items:center;">
                <a href="/" class="btn btn-secondary" id="continue-shopping">&larr; Continue Shopping</a>
                <a href="/cart/clear" class="btn btn-secondary" style="color:#dc2626;" id="clear-cart-btn">Clear Cart</a>
            </div>
        {% else %}
            <p id="empty-cart-msg">Your shopping cart is currently empty.</p>
            <p style="margin-top: 16px;"><a href="/" class="btn btn-primary" id="start-shopping">Browse Laptops</a></p>
        {% endif %}
    </div>
</body>
</html>
"""


@app.route("/")
def index():
    query = request.args.get("q", "").strip().lower()
    sort_by = request.args.get("sort", "").strip().lower()
    banner = request.args.get("banner", "")

    filtered = PRODUCTS
    if query:
        filtered = [
            p for p in PRODUCTS
            if query in p["name"].lower()
            or query in p["category"].lower()
            or query in p["cpu"].lower()
            or query in p["description"].lower()
        ]

    if sort_by == "price_asc":
        filtered = sorted(filtered, key=lambda x: x["price"])
    elif sort_by == "price_desc":
        filtered = sorted(filtered, key=lambda x: x["price"], reverse=True)

    cheapest = min(filtered, key=lambda x: x["price"]) if filtered else None

    return render_template_string(
        HTML_TEMPLATE,
        products=filtered,
        query=request.args.get("q", ""),
        sort_by=sort_by,
        cheapest=cheapest,
        cart=CART_ITEMS,
        banner_msg=banner,
    )


@app.route("/product/<int:product_id>")
def product_detail(product_id: int):
    product = next((p for p in PRODUCTS if p["id"] == product_id), None)
    if not product:
        return "Product Not Found", 404
    return render_template_string(DETAIL_TEMPLATE, product=product, cart=CART_ITEMS)


@app.route("/cart")
def view_cart():
    added_name = request.args.get("added", "")
    total = sum(item["price"] for item in CART_ITEMS)
    return render_template_string(
        CART_TEMPLATE,
        cart=CART_ITEMS,
        total=total,
        added_name=added_name,
    )


@app.route("/cart/add/<int:product_id>")
def add_to_cart(product_id: int):
    product = next((p for p in PRODUCTS if p["id"] == product_id), None)
    if product:
        CART_ITEMS.append(product)
        return redirect(url_for("view_cart", added=product["name"]))
    return "Product Not Found", 404


@app.route("/cart/clear")
def clear_cart():
    CART_ITEMS.clear()
    return redirect(url_for("view_cart"))


@app.route("/api/products")
def api_products():
    return jsonify({"products": PRODUCTS, "count": len(PRODUCTS)})


@app.route("/api/cart")
def api_cart():
    return jsonify({"cart": CART_ITEMS, "count": len(CART_ITEMS)})


@app.route("/health")
def health():
    return jsonify({"status": "ok", "service": "demo_site", "cart_count": len(CART_ITEMS)})


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
