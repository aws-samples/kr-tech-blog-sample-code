"""
OpenSearch Setup Lambda - Custom Resource handler for OpenSearch initialization.

This Lambda function is triggered by CDK Custom Resource Provider to:
1. Map Lambda IAM role to OpenSearch all_access role
2. Create UBI indices (ubi_queries, ubi_events)
3. Create products index with k-NN support (faiss engine)
4. Create llm_judgments index
5. Add comprehensive sample data for LTR training

IMPORTANT: When using CDK cr.Provider, do NOT send CFN responses directly.
The Provider framework handles that. Just return the data dict or raise exceptions.
"""

import json
import logging
import random
import uuid
from datetime import datetime, timezone, timedelta

import boto3
from opensearchpy import OpenSearch, RequestsHttpConnection
from requests_aws4auth import AWS4Auth

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def get_opensearch_client(endpoint: str, region: str) -> OpenSearch:
    """Create OpenSearch client with SigV4 authentication."""
    credentials = boto3.Session().get_credentials()
    awsauth = AWS4Auth(
        credentials.access_key,
        credentials.secret_key,
        region,
        'es',
        session_token=credentials.token
    )

    return OpenSearch(
        hosts=[{'host': endpoint, 'port': 443}],
        http_auth=awsauth,
        use_ssl=True,
        verify_certs=True,
        connection_class=RequestsHttpConnection,
        timeout=30,
    )


def get_basic_auth_client(endpoint: str, username: str, password: str) -> OpenSearch:
    """Create OpenSearch client with basic authentication."""
    return OpenSearch(
        hosts=[{'host': endpoint, 'port': 443}],
        http_auth=(username, password),
        use_ssl=True,
        verify_certs=True,
        connection_class=RequestsHttpConnection,
        timeout=30,
    )


def get_secret(secret_arn: str) -> dict:
    """Retrieve secret from Secrets Manager."""
    client = boto3.client('secretsmanager')
    response = client.get_secret_value(SecretId=secret_arn)
    return json.loads(response['SecretString'])


def map_iam_roles(client: OpenSearch, role_arns: list) -> bool:
    """Map IAM roles to OpenSearch all_access role."""
    logger.info(f"Mapping IAM roles to all_access: {role_arns}")

    try:
        # Get current mapping
        current = client.transport.perform_request(
            'GET', '/_plugins/_security/api/rolesmapping/all_access'
        )

        existing_users = current.get('all_access', {}).get('users', [])
        existing_backend_roles = current.get('all_access', {}).get('backend_roles', [])

        # Add roles if not already present
        updated = False
        for role_arn in role_arns:
            if role_arn and role_arn not in existing_backend_roles:
                existing_backend_roles.append(role_arn)
                updated = True
                logger.info(f"Adding role to mapping: {role_arn}")

        if updated:
            # Update mapping
            client.transport.perform_request(
                'PUT',
                '/_plugins/_security/api/rolesmapping/all_access',
                body={
                    'users': existing_users,
                    'backend_roles': existing_backend_roles
                }
            )
            logger.info("Successfully mapped IAM roles to all_access")
        else:
            logger.info("All IAM roles already mapped to all_access")

        return True
    except Exception as e:
        logger.error(f"Failed to map IAM roles: {e}")
        raise


def create_indices(client: OpenSearch) -> dict:
    """Create all required indices."""
    results = {}

    # UBI Queries index
    ubi_queries_mapping = {
        "mappings": {
            "properties": {
                "query_id": {"type": "keyword"},
                "query_response_id": {"type": "keyword"},
                "user_query": {"type": "text", "fields": {"keyword": {"type": "keyword"}}},
                "application": {"type": "keyword"},
                "timestamp": {"type": "date"},
                "user_id": {"type": "keyword"},
                "session_id": {"type": "keyword"},
                "query_attributes": {"type": "object", "enabled": False}
            }
        },
        "settings": {"number_of_shards": 1, "number_of_replicas": 0}
    }

    # UBI Events index
    ubi_events_mapping = {
        "mappings": {
            "properties": {
                "action_name": {"type": "keyword"},
                "query_id": {"type": "keyword"},
                "timestamp": {"type": "date"},
                "client_id": {"type": "keyword"},
                "user_id": {"type": "keyword"},
                "session_id": {"type": "keyword"},
                "object_id": {"type": "keyword"},
                "object_id_field": {"type": "keyword"},
                "position": {"type": "integer"},
                "message": {"type": "text"},
                "dwell_time": {"type": "integer"},
                "event_attributes": {"type": "object", "enabled": False}
            }
        },
        "settings": {"number_of_shards": 1, "number_of_replicas": 0}
    }

    # Products index with k-NN (faiss engine)
    products_mapping = {
        "settings": {
            "number_of_shards": 1,
            "number_of_replicas": 0,
            "index.knn": True
        },
        "mappings": {
            "properties": {
                "product_id": {"type": "keyword"},
                "name": {"type": "text", "fields": {"keyword": {"type": "keyword"}}},
                "description": {"type": "text"},
                "category": {"type": "keyword"},
                "subcategory": {"type": "keyword"},
                "brand": {"type": "keyword"},
                "price": {"type": "float"},
                "rating": {"type": "float"},
                "review_count": {"type": "integer"},
                "in_stock": {"type": "boolean"},
                "tags": {"type": "keyword"},
                "embedding": {
                    "type": "knn_vector",
                    "dimension": 384,
                    "method": {
                        "name": "hnsw",
                        "space_type": "l2",
                        "engine": "faiss",
                        "parameters": {"ef_construction": 256, "m": 16}
                    }
                }
            }
        }
    }

    # LLM Judgments index
    llm_judgments_mapping = {
        "mappings": {
            "properties": {
                "query": {"type": "text", "fields": {"keyword": {"type": "keyword"}}},
                "doc_id": {"type": "keyword"},
                "product_name": {"type": "text"},
                "rank": {"type": "integer"},
                "rating": {"type": "float"},
                "reason": {"type": "text"},
                "model": {"type": "keyword"},
                "timestamp": {"type": "date"}
            }
        },
        "settings": {"number_of_shards": 1, "number_of_replicas": 0}
    }

    indices = {
        "ubi_queries": ubi_queries_mapping,
        "ubi_events": ubi_events_mapping,
        "products": products_mapping,
        "llm_judgments": llm_judgments_mapping
    }

    for index_name, mapping in indices.items():
        try:
            if not client.indices.exists(index=index_name):
                client.indices.create(index=index_name, body=mapping)
                results[index_name] = "created"
                logger.info(f"Created index: {index_name}")
            else:
                results[index_name] = "exists"
                logger.info(f"Index already exists: {index_name}")
        except Exception as e:
            results[index_name] = f"error: {str(e)}"
            logger.error(f"Failed to create index {index_name}: {e}")

    return results


def generate_products() -> list:
    """Generate comprehensive product catalog for LTR training."""
    products = []

    # Smartphones
    smartphones = [
        {"id": "phone-001", "name": "Samsung Galaxy S24 Ultra", "desc": "Latest flagship smartphone with AI features, 200MP camera, S Pen support", "brand": "Samsung", "price": 1299.99, "rating": 4.8, "reviews": 2453, "tags": ["flagship", "android", "5g", "ai", "camera"]},
        {"id": "phone-002", "name": "iPhone 15 Pro Max", "desc": "Premium Apple smartphone with titanium design, A17 Pro chip, ProMotion display", "brand": "Apple", "price": 1199.99, "rating": 4.9, "reviews": 5621, "tags": ["flagship", "ios", "5g", "titanium", "pro"]},
        {"id": "phone-003", "name": "Google Pixel 8 Pro", "desc": "Google flagship with advanced AI photography, Tensor G3 chip, pure Android experience", "brand": "Google", "price": 999.99, "rating": 4.7, "reviews": 1823, "tags": ["flagship", "android", "5g", "ai", "photography"]},
        {"id": "phone-004", "name": "Samsung Galaxy A54", "desc": "Mid-range Samsung phone with great camera and long battery life", "brand": "Samsung", "price": 449.99, "rating": 4.5, "reviews": 3421, "tags": ["midrange", "android", "5g", "budget-friendly"]},
        {"id": "phone-005", "name": "iPhone 15", "desc": "Standard iPhone with Dynamic Island, A16 chip, improved cameras", "brand": "Apple", "price": 799.99, "rating": 4.7, "reviews": 4123, "tags": ["ios", "5g", "dynamic-island"]},
        {"id": "phone-006", "name": "OnePlus 12", "desc": "Flagship killer with Snapdragon 8 Gen 3, 100W fast charging", "brand": "OnePlus", "price": 799.99, "rating": 4.6, "reviews": 1256, "tags": ["flagship", "android", "5g", "fast-charging"]},
        {"id": "phone-007", "name": "Xiaomi 14 Pro", "desc": "Premium Xiaomi phone with Leica cameras, HyperOS", "brand": "Xiaomi", "price": 899.99, "rating": 4.5, "reviews": 892, "tags": ["flagship", "android", "5g", "leica"]},
        {"id": "phone-008", "name": "Google Pixel 8a", "desc": "Affordable Pixel with AI features and excellent camera", "brand": "Google", "price": 499.99, "rating": 4.6, "reviews": 1567, "tags": ["midrange", "android", "5g", "ai", "value"]},
        {"id": "phone-009", "name": "Samsung Galaxy Z Fold 5", "desc": "Foldable smartphone with large inner display, multitasking powerhouse", "brand": "Samsung", "price": 1799.99, "rating": 4.4, "reviews": 987, "tags": ["foldable", "android", "5g", "premium"]},
        {"id": "phone-010", "name": "iPhone SE 2024", "desc": "Compact iPhone with powerful chip at affordable price", "brand": "Apple", "price": 429.99, "rating": 4.3, "reviews": 2134, "tags": ["budget", "ios", "5g", "compact"]},
    ]

    for p in smartphones:
        products.append({
            "product_id": p["id"], "name": p["name"], "description": p["desc"],
            "category": "smartphones", "subcategory": "mobile-phones",
            "brand": p["brand"], "price": p["price"], "rating": p["rating"],
            "review_count": p["reviews"], "in_stock": True, "tags": p["tags"]
        })

    # Laptops
    laptops = [
        {"id": "laptop-001", "name": "MacBook Pro 16 M3 Max", "desc": "Professional laptop with M3 Max chip, 36GB RAM, exceptional performance for creative work", "brand": "Apple", "price": 3499.99, "rating": 4.9, "reviews": 1234, "tags": ["professional", "creative", "high-performance", "macos"]},
        {"id": "laptop-002", "name": "MacBook Air 15 M3", "desc": "Thin and light laptop with M3 chip, all-day battery, perfect for everyday use", "brand": "Apple", "price": 1299.99, "rating": 4.8, "reviews": 2567, "tags": ["ultrabook", "portable", "macos", "student"]},
        {"id": "laptop-003", "name": "Dell XPS 15", "desc": "Premium Windows laptop with OLED display, Intel Core Ultra, sleek design", "brand": "Dell", "price": 1799.99, "rating": 4.6, "reviews": 1876, "tags": ["premium", "oled", "windows", "ultrabook"]},
        {"id": "laptop-004", "name": "Lenovo ThinkPad X1 Carbon", "desc": "Business ultrabook with legendary keyboard, excellent security features", "brand": "Lenovo", "price": 1649.99, "rating": 4.7, "reviews": 2341, "tags": ["business", "ultrabook", "windows", "security"]},
        {"id": "laptop-005", "name": "ASUS ROG Zephyrus G16", "desc": "Gaming laptop with RTX 4070, 240Hz display, excellent cooling", "brand": "ASUS", "price": 1999.99, "rating": 4.5, "reviews": 876, "tags": ["gaming", "rtx", "high-performance", "windows"]},
        {"id": "laptop-006", "name": "HP Spectre x360 14", "desc": "2-in-1 convertible with OLED display, stylish gem-cut design", "brand": "HP", "price": 1449.99, "rating": 4.5, "reviews": 1234, "tags": ["2-in-1", "convertible", "oled", "windows"]},
        {"id": "laptop-007", "name": "Razer Blade 16", "desc": "Premium gaming laptop with RTX 4090, stunning 4K display", "brand": "Razer", "price": 3999.99, "rating": 4.4, "reviews": 543, "tags": ["gaming", "rtx-4090", "premium", "4k"]},
        {"id": "laptop-008", "name": "Microsoft Surface Laptop 5", "desc": "Elegant Windows laptop with touch screen, great for productivity", "brand": "Microsoft", "price": 999.99, "rating": 4.4, "reviews": 1567, "tags": ["windows", "touch", "productivity", "elegant"]},
        {"id": "laptop-009", "name": "Acer Swift Go 14", "desc": "Affordable ultrabook with Intel Core, great battery life", "brand": "Acer", "price": 749.99, "rating": 4.3, "reviews": 892, "tags": ["budget", "ultrabook", "windows", "value"]},
        {"id": "laptop-010", "name": "MacBook Pro 14 M3 Pro", "desc": "Professional laptop with M3 Pro chip, ProMotion display, compact form factor", "brand": "Apple", "price": 1999.99, "rating": 4.8, "reviews": 1876, "tags": ["professional", "macos", "compact", "creative"]},
    ]

    for p in laptops:
        products.append({
            "product_id": p["id"], "name": p["name"], "description": p["desc"],
            "category": "laptops", "subcategory": "notebooks",
            "brand": p["brand"], "price": p["price"], "rating": p["rating"],
            "review_count": p["reviews"], "in_stock": True, "tags": p["tags"]
        })

    # Headphones & Earbuds
    audio = [
        {"id": "audio-001", "name": "Sony WH-1000XM5", "desc": "Premium noise-cancelling wireless headphones with industry-leading ANC", "brand": "Sony", "price": 399.99, "rating": 4.8, "reviews": 4532, "subcat": "headphones", "tags": ["noise-cancelling", "wireless", "premium", "anc"]},
        {"id": "audio-002", "name": "Apple AirPods Pro 2", "desc": "Premium wireless earbuds with active noise cancellation, spatial audio", "brand": "Apple", "price": 249.99, "rating": 4.7, "reviews": 6723, "subcat": "earbuds", "tags": ["noise-cancelling", "wireless", "ios", "spatial-audio"]},
        {"id": "audio-003", "name": "Bose QuietComfort Ultra", "desc": "Premium headphones with immersive audio and world-class noise cancellation", "brand": "Bose", "price": 429.99, "rating": 4.7, "reviews": 2134, "subcat": "headphones", "tags": ["noise-cancelling", "wireless", "premium", "immersive"]},
        {"id": "audio-004", "name": "Samsung Galaxy Buds 3 Pro", "desc": "Premium earbuds with intelligent ANC and 360 audio", "brand": "Samsung", "price": 229.99, "rating": 4.5, "reviews": 1876, "subcat": "earbuds", "tags": ["noise-cancelling", "wireless", "android", "360-audio"]},
        {"id": "audio-005", "name": "Sennheiser Momentum 4", "desc": "Audiophile-grade wireless headphones with exceptional sound quality", "brand": "Sennheiser", "price": 349.99, "rating": 4.6, "reviews": 1234, "subcat": "headphones", "tags": ["audiophile", "wireless", "premium", "hi-res"]},
        {"id": "audio-006", "name": "Apple AirPods Max", "desc": "Over-ear premium headphones with computational audio, high-fidelity sound", "brand": "Apple", "price": 549.99, "rating": 4.5, "reviews": 2341, "subcat": "headphones", "tags": ["premium", "wireless", "ios", "over-ear"]},
        {"id": "audio-007", "name": "Sony WF-1000XM5", "desc": "Flagship wireless earbuds with best-in-class noise cancelling", "brand": "Sony", "price": 299.99, "rating": 4.7, "reviews": 3421, "subcat": "earbuds", "tags": ["noise-cancelling", "wireless", "premium", "compact"]},
        {"id": "audio-008", "name": "Jabra Elite 85t", "desc": "Wireless earbuds with adjustable ANC and great call quality", "brand": "Jabra", "price": 179.99, "rating": 4.4, "reviews": 2567, "subcat": "earbuds", "tags": ["noise-cancelling", "wireless", "calls", "value"]},
        {"id": "audio-009", "name": "Beats Studio Pro", "desc": "Premium headphones with spatial audio and enhanced Apple integration", "brand": "Beats", "price": 349.99, "rating": 4.4, "reviews": 1567, "subcat": "headphones", "tags": ["wireless", "ios", "bass", "spatial-audio"]},
        {"id": "audio-010", "name": "Google Pixel Buds Pro 2", "desc": "AI-powered earbuds with excellent noise cancelling and Google integration", "brand": "Google", "price": 229.99, "rating": 4.5, "reviews": 987, "subcat": "earbuds", "tags": ["noise-cancelling", "wireless", "android", "ai"]},
    ]

    for p in audio:
        products.append({
            "product_id": p["id"], "name": p["name"], "description": p["desc"],
            "category": "audio", "subcategory": p["subcat"],
            "brand": p["brand"], "price": p["price"], "rating": p["rating"],
            "review_count": p["reviews"], "in_stock": True, "tags": p["tags"]
        })

    # Smartwatches & Wearables
    wearables = [
        {"id": "watch-001", "name": "Apple Watch Ultra 2", "desc": "Rugged smartwatch for extreme sports with titanium case, 36-hour battery", "brand": "Apple", "price": 799.99, "rating": 4.8, "reviews": 2134, "tags": ["rugged", "fitness", "ios", "premium"]},
        {"id": "watch-002", "name": "Apple Watch Series 9", "desc": "Advanced smartwatch with S9 chip, health monitoring, always-on display", "brand": "Apple", "price": 399.99, "rating": 4.7, "reviews": 4567, "tags": ["health", "fitness", "ios", "smartwatch"]},
        {"id": "watch-003", "name": "Samsung Galaxy Watch 6 Classic", "desc": "Premium smartwatch with rotating bezel, advanced health tracking", "brand": "Samsung", "price": 399.99, "rating": 4.5, "reviews": 2341, "tags": ["classic", "health", "android", "premium"]},
        {"id": "watch-004", "name": "Garmin Fenix 8", "desc": "Multisport GPS watch with solar charging, maps, advanced training features", "brand": "Garmin", "price": 999.99, "rating": 4.7, "reviews": 1234, "tags": ["sports", "gps", "outdoor", "solar"]},
        {"id": "watch-005", "name": "Fitbit Sense 2", "desc": "Health-focused smartwatch with stress management, ECG, skin temperature", "brand": "Fitbit", "price": 299.99, "rating": 4.3, "reviews": 3421, "tags": ["health", "fitness", "stress", "value"]},
        {"id": "watch-006", "name": "Google Pixel Watch 2", "desc": "Google smartwatch with Fitbit health tracking, Wear OS, AI features", "brand": "Google", "price": 349.99, "rating": 4.4, "reviews": 1567, "tags": ["health", "fitness", "android", "ai"]},
        {"id": "watch-007", "name": "Garmin Forerunner 965", "desc": "Premium running watch with AMOLED display, training metrics, maps", "brand": "Garmin", "price": 599.99, "rating": 4.6, "reviews": 876, "tags": ["running", "gps", "training", "amoled"]},
        {"id": "watch-008", "name": "Samsung Galaxy Watch 6", "desc": "Sleek smartwatch with BioActive sensor, sleep coaching, workout tracking", "brand": "Samsung", "price": 299.99, "rating": 4.4, "reviews": 2876, "tags": ["health", "fitness", "android", "sleep"]},
    ]

    for p in wearables:
        products.append({
            "product_id": p["id"], "name": p["name"], "description": p["desc"],
            "category": "wearables", "subcategory": "smartwatches",
            "brand": p["brand"], "price": p["price"], "rating": p["rating"],
            "review_count": p["reviews"], "in_stock": True, "tags": p["tags"]
        })

    # Tablets
    tablets = [
        {"id": "tablet-001", "name": "iPad Pro 12.9 M4", "desc": "Ultimate iPad with M4 chip, OLED display, Apple Pencil Pro support", "brand": "Apple", "price": 1099.99, "rating": 4.9, "reviews": 2341, "tags": ["professional", "creative", "oled", "pencil"]},
        {"id": "tablet-002", "name": "iPad Air M2", "desc": "Versatile tablet with M2 chip, 10.9-inch display, great for productivity", "brand": "Apple", "price": 599.99, "rating": 4.7, "reviews": 3456, "tags": ["versatile", "productivity", "m2", "value"]},
        {"id": "tablet-003", "name": "Samsung Galaxy Tab S9 Ultra", "desc": "Massive 14.6-inch AMOLED tablet with S Pen, DeX support", "brand": "Samsung", "price": 1199.99, "rating": 4.6, "reviews": 1234, "tags": ["large", "amoled", "android", "productivity"]},
        {"id": "tablet-004", "name": "iPad 10th Gen", "desc": "Colorful iPad with A14 chip, USB-C, great for everyday use", "brand": "Apple", "price": 449.99, "rating": 4.5, "reviews": 4567, "tags": ["value", "colorful", "usb-c", "everyday"]},
        {"id": "tablet-005", "name": "Samsung Galaxy Tab S9", "desc": "Compact flagship tablet with S Pen, IP68 water resistance", "brand": "Samsung", "price": 849.99, "rating": 4.5, "reviews": 1876, "tags": ["compact", "waterproof", "android", "s-pen"]},
        {"id": "tablet-006", "name": "Microsoft Surface Pro 9", "desc": "2-in-1 tablet with Windows 11, kickstand, detachable keyboard", "brand": "Microsoft", "price": 999.99, "rating": 4.4, "reviews": 2134, "tags": ["2-in-1", "windows", "productivity", "business"]},
    ]

    for p in tablets:
        products.append({
            "product_id": p["id"], "name": p["name"], "description": p["desc"],
            "category": "tablets", "subcategory": "tablet-computers",
            "brand": p["brand"], "price": p["price"], "rating": p["rating"],
            "review_count": p["reviews"], "in_stock": True, "tags": p["tags"]
        })

    # Cameras
    cameras = [
        {"id": "camera-001", "name": "Sony A7 IV", "desc": "Full-frame mirrorless camera with 33MP sensor, 4K video, advanced AF", "brand": "Sony", "price": 2499.99, "rating": 4.8, "reviews": 1234, "subcat": "mirrorless", "tags": ["full-frame", "mirrorless", "4k", "professional"]},
        {"id": "camera-002", "name": "Canon EOS R6 Mark II", "desc": "Fast mirrorless camera with 24MP sensor, excellent autofocus, 6K video", "brand": "Canon", "price": 2499.99, "rating": 4.7, "reviews": 987, "subcat": "mirrorless", "tags": ["full-frame", "mirrorless", "6k", "fast-af"]},
        {"id": "camera-003", "name": "Sony ZV-E10 II", "desc": "Vlogging camera with APS-C sensor, flip screen, excellent video features", "brand": "Sony", "price": 999.99, "rating": 4.6, "reviews": 1567, "subcat": "mirrorless", "tags": ["vlogging", "aps-c", "4k", "content-creator"]},
        {"id": "camera-004", "name": "Fujifilm X-T5", "desc": "Retro-styled mirrorless with 40MP sensor, film simulations", "brand": "Fujifilm", "price": 1699.99, "rating": 4.7, "reviews": 876, "subcat": "mirrorless", "tags": ["retro", "aps-c", "film-simulation", "photography"]},
        {"id": "camera-005", "name": "GoPro Hero 12 Black", "desc": "Action camera with 5.3K video, HyperSmooth stabilization, waterproof", "brand": "GoPro", "price": 399.99, "rating": 4.5, "reviews": 3421, "subcat": "action", "tags": ["action", "waterproof", "5k", "adventure"]},
        {"id": "camera-006", "name": "DJI Osmo Pocket 3", "desc": "Pocket gimbal camera with 1-inch sensor, 4K video, 3-axis stabilization", "brand": "DJI", "price": 519.99, "rating": 4.6, "reviews": 1234, "subcat": "gimbal", "tags": ["gimbal", "pocket", "4k", "stabilization"]},
    ]

    for p in cameras:
        products.append({
            "product_id": p["id"], "name": p["name"], "description": p["desc"],
            "category": "cameras", "subcategory": p["subcat"],
            "brand": p["brand"], "price": p["price"], "rating": p["rating"],
            "review_count": p["reviews"], "in_stock": True, "tags": p["tags"]
        })

    # Gaming
    gaming = [
        {"id": "gaming-001", "name": "PlayStation 5", "desc": "Next-gen gaming console with ultra-fast SSD, 4K gaming, DualSense controller", "brand": "Sony", "price": 499.99, "rating": 4.8, "reviews": 8765, "subcat": "consoles", "tags": ["console", "4k", "gaming", "exclusive"]},
        {"id": "gaming-002", "name": "Xbox Series X", "desc": "Most powerful Xbox with 4K gaming, Game Pass, backward compatibility", "brand": "Microsoft", "price": 499.99, "rating": 4.7, "reviews": 6543, "subcat": "consoles", "tags": ["console", "4k", "game-pass", "powerful"]},
        {"id": "gaming-003", "name": "Nintendo Switch OLED", "desc": "Hybrid gaming console with OLED screen, portable and docked modes", "brand": "Nintendo", "price": 349.99, "rating": 4.7, "reviews": 7654, "subcat": "consoles", "tags": ["hybrid", "portable", "oled", "nintendo"]},
        {"id": "gaming-004", "name": "Steam Deck OLED", "desc": "Handheld PC gaming device with OLED display, full Steam library access", "brand": "Valve", "price": 549.99, "rating": 4.6, "reviews": 2341, "subcat": "handheld", "tags": ["handheld", "pc-gaming", "oled", "steam"]},
        {"id": "gaming-005", "name": "Meta Quest 3", "desc": "Mixed reality VR headset with high-res displays, full-color passthrough", "brand": "Meta", "price": 499.99, "rating": 4.5, "reviews": 3456, "subcat": "vr", "tags": ["vr", "mixed-reality", "standalone", "gaming"]},
        {"id": "gaming-006", "name": "ASUS ROG Ally", "desc": "Windows handheld gaming device with powerful AMD chip, 1080p display", "brand": "ASUS", "price": 599.99, "rating": 4.3, "reviews": 1234, "subcat": "handheld", "tags": ["handheld", "windows", "pc-gaming", "portable"]},
    ]

    for p in gaming:
        products.append({
            "product_id": p["id"], "name": p["name"], "description": p["desc"],
            "category": "gaming", "subcategory": p["subcat"],
            "brand": p["brand"], "price": p["price"], "rating": p["rating"],
            "review_count": p["reviews"], "in_stock": True, "tags": p["tags"]
        })

    return products


def generate_ltr_training_data(products: list) -> tuple:
    """
    Generate comprehensive UBI data for LTR training.

    Returns queries and events that simulate realistic user behavior patterns:
    - Users clicking on lower-ranked items (indicates higher relevance)
    - Users purchasing items (strong positive signal)
    - Users adding to cart (medium positive signal)
    - Various dwell times (longer = more relevant)
    - Multiple sessions per user to show consistent preferences
    """
    queries = []
    events = []

    # Define search scenarios with expected relevant products
    # Format: (query, category_hint, highly_relevant_ids, somewhat_relevant_ids)
    search_scenarios = [
        # Smartphone searches
        ("best smartphone 2024", "smartphones", ["phone-001", "phone-002", "phone-003"], ["phone-005", "phone-006"]),
        ("iphone", "smartphones", ["phone-002", "phone-005", "phone-010"], []),
        ("samsung phone", "smartphones", ["phone-001", "phone-004", "phone-009"], []),
        ("budget smartphone", "smartphones", ["phone-004", "phone-008", "phone-010"], ["phone-005"]),
        ("foldable phone", "smartphones", ["phone-009"], ["phone-001"]),
        ("pixel phone camera", "smartphones", ["phone-003", "phone-008"], []),
        ("android flagship", "smartphones", ["phone-001", "phone-003", "phone-006", "phone-007"], []),

        # Laptop searches
        ("macbook pro", "laptops", ["laptop-001", "laptop-010"], ["laptop-002"]),
        ("gaming laptop", "laptops", ["laptop-005", "laptop-007"], []),
        ("best laptop for students", "laptops", ["laptop-002", "laptop-008", "laptop-009"], []),
        ("business laptop", "laptops", ["laptop-004", "laptop-003"], ["laptop-008"]),
        ("ultrabook", "laptops", ["laptop-002", "laptop-003", "laptop-004", "laptop-009"], []),
        ("laptop with oled", "laptops", ["laptop-003", "laptop-006"], []),

        # Audio searches
        ("noise cancelling headphones", "audio", ["audio-001", "audio-003", "audio-006"], ["audio-005"]),
        ("wireless earbuds", "audio", ["audio-002", "audio-004", "audio-007", "audio-010"], ["audio-008"]),
        ("airpods", "audio", ["audio-002", "audio-006"], []),
        ("sony headphones", "audio", ["audio-001", "audio-007"], []),
        ("best earbuds for calls", "audio", ["audio-008", "audio-002", "audio-007"], []),
        ("premium headphones", "audio", ["audio-001", "audio-003", "audio-005", "audio-006"], []),

        # Smartwatch searches
        ("apple watch", "wearables", ["watch-001", "watch-002"], []),
        ("fitness tracker", "wearables", ["watch-005", "watch-006", "watch-002"], ["watch-008"]),
        ("running watch gps", "wearables", ["watch-004", "watch-007"], ["watch-001"]),
        ("samsung smartwatch", "wearables", ["watch-003", "watch-008"], []),
        ("rugged smartwatch", "wearables", ["watch-001", "watch-004"], []),

        # Tablet searches
        ("ipad pro", "tablets", ["tablet-001"], ["tablet-002"]),
        ("tablet for drawing", "tablets", ["tablet-001", "tablet-003", "tablet-005"], []),
        ("budget tablet", "tablets", ["tablet-004"], ["tablet-002"]),
        ("android tablet", "tablets", ["tablet-003", "tablet-005"], []),
        ("tablet for work", "tablets", ["tablet-006", "tablet-003", "tablet-001"], []),

        # Camera searches
        ("mirrorless camera", "cameras", ["camera-001", "camera-002", "camera-004"], []),
        ("vlogging camera", "cameras", ["camera-003", "camera-006"], []),
        ("action camera gopro", "cameras", ["camera-005"], []),
        ("sony camera", "cameras", ["camera-001", "camera-003"], []),

        # Gaming searches
        ("playstation 5", "gaming", ["gaming-001"], []),
        ("nintendo switch", "gaming", ["gaming-003"], []),
        ("vr headset", "gaming", ["gaming-005"], []),
        ("handheld gaming", "gaming", ["gaming-003", "gaming-004", "gaming-006"], []),
        ("best gaming console", "gaming", ["gaming-001", "gaming-002", "gaming-003"], []),
    ]

    # Create product lookup by ID
    product_by_id = {p["product_id"]: p for p in products}

    # Generate users with different behavior profiles
    users = [
        {"id": "user-001", "type": "researcher", "sessions": 5},  # Researches a lot before buying
        {"id": "user-002", "type": "impulse", "sessions": 3},     # Quick decisions
        {"id": "user-003", "type": "comparison", "sessions": 4},  # Compares many options
        {"id": "user-004", "type": "brand_loyal", "sessions": 3}, # Sticks to certain brands
        {"id": "user-005", "type": "budget", "sessions": 4},      # Price sensitive
        {"id": "user-006", "type": "premium", "sessions": 3},     # Goes for premium
        {"id": "user-007", "type": "researcher", "sessions": 5},
        {"id": "user-008", "type": "impulse", "sessions": 2},
        {"id": "user-009", "type": "comparison", "sessions": 4},
        {"id": "user-010", "type": "premium", "sessions": 3},
    ]

    base_time = datetime.now(timezone.utc) - timedelta(days=30)

    for user in users:
        # Each user performs searches across multiple sessions
        for session_num in range(user["sessions"]):
            session_id = f"session-{user['id']}-{session_num}"
            session_time = base_time + timedelta(days=random.randint(0, 29), hours=random.randint(0, 23))

            # Pick 2-4 random search scenarios for this session
            session_searches = random.sample(search_scenarios, min(random.randint(2, 4), len(search_scenarios)))

            for search in session_searches:
                query_text, category_hint, high_rel, some_rel = search
                query_id = str(uuid.uuid4())
                query_time = session_time + timedelta(minutes=random.randint(0, 60))

                # Create query
                queries.append({
                    "query_id": query_id,
                    "user_query": query_text,
                    "timestamp": query_time.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z',
                    "user_id": user["id"],
                    "session_id": session_id,
                    "application": "search-app",
                    "query_attributes": {"category_hint": category_hint}
                })

                # Simulate search results (mix of relevant and less relevant products)
                all_category_products = [p["product_id"] for p in products if p["category"] == category_hint]
                other_products = [pid for pid in all_category_products if pid not in high_rel and pid not in some_rel]

                # Build simulated result list (position 1-10)
                result_list = []
                # Position 1-3: Mix of relevant and less relevant (simulating imperfect ranking)
                if other_products:
                    result_list.append(random.choice(other_products))  # Less relevant at top
                if high_rel:
                    result_list.append(random.choice(high_rel))  # Highly relevant
                if some_rel:
                    result_list.append(random.choice(some_rel))
                elif high_rel:
                    result_list.append(random.choice(high_rel))

                # Fill remaining positions
                remaining = [p for p in all_category_products if p not in result_list]
                random.shuffle(remaining)
                result_list.extend(remaining[:7])

                # Generate events based on user behavior type
                event_time = query_time + timedelta(seconds=random.randint(2, 10))

                if user["type"] == "researcher":
                    # Researchers click multiple items, spend time reading
                    click_count = random.randint(3, 5)
                    for i, pid in enumerate(result_list[:click_count]):
                        position = i + 1
                        dwell = random.randint(30, 180) if pid in high_rel else random.randint(5, 30)
                        events.append({
                            "action_name": "click",
                            "query_id": query_id,
                            "timestamp": event_time.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z',
                            "user_id": user["id"],
                            "session_id": session_id,
                            "object_id": pid,
                            "object_id_field": "product_id",
                            "position": position,
                            "dwell_time": dwell,
                            "event_attributes": {"source": "search_results"}
                        })
                        event_time += timedelta(seconds=dwell + random.randint(2, 10))

                    # Sometimes add to cart (40% chance for highly relevant)
                    for pid in high_rel[:2]:
                        if pid in result_list and random.random() < 0.4:
                            events.append({
                                "action_name": "add_to_cart",
                                "query_id": query_id,
                                "timestamp": event_time.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z',
                                "user_id": user["id"],
                                "session_id": session_id,
                                "object_id": pid,
                                "object_id_field": "product_id",
                                "position": result_list.index(pid) + 1 if pid in result_list else 0,
                                "event_attributes": {"source": "product_page"}
                            })

                elif user["type"] == "impulse":
                    # Impulse buyers click 1-2 items and quickly purchase
                    if high_rel and result_list:
                        # Find highly relevant in results
                        for pid in high_rel[:1]:
                            if pid in result_list:
                                position = result_list.index(pid) + 1
                                events.append({
                                    "action_name": "click",
                                    "query_id": query_id,
                                    "timestamp": event_time.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z',
                                    "user_id": user["id"],
                                    "session_id": session_id,
                                    "object_id": pid,
                                    "object_id_field": "product_id",
                                    "position": position,
                                    "dwell_time": random.randint(20, 60),
                                    "event_attributes": {}
                                })
                                event_time += timedelta(seconds=random.randint(30, 90))

                                # High chance of purchase
                                if random.random() < 0.6:
                                    events.append({
                                        "action_name": "purchase",
                                        "query_id": query_id,
                                        "timestamp": event_time.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z',
                                        "user_id": user["id"],
                                        "session_id": session_id,
                                        "object_id": pid,
                                        "object_id_field": "product_id",
                                        "position": position,
                                        "event_attributes": {"price": product_by_id.get(pid, {}).get("price", 0)}
                                    })
                                break

                elif user["type"] == "comparison":
                    # Comparison shoppers click many items, comparing them
                    click_count = random.randint(4, 6)
                    clicked_items = []
                    for i, pid in enumerate(result_list[:click_count]):
                        position = i + 1
                        dwell = random.randint(15, 90)
                        clicked_items.append(pid)
                        events.append({
                            "action_name": "click",
                            "query_id": query_id,
                            "timestamp": event_time.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z',
                            "user_id": user["id"],
                            "session_id": session_id,
                            "object_id": pid,
                            "object_id_field": "product_id",
                            "position": position,
                            "dwell_time": dwell,
                            "event_attributes": {}
                        })
                        event_time += timedelta(seconds=dwell + 5)

                    # Add the best one to cart (prefer highly relevant)
                    best_choice = None
                    for pid in high_rel:
                        if pid in clicked_items:
                            best_choice = pid
                            break
                    if best_choice:
                        events.append({
                            "action_name": "add_to_cart",
                            "query_id": query_id,
                            "timestamp": event_time.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z',
                            "user_id": user["id"],
                            "session_id": session_id,
                            "object_id": best_choice,
                            "object_id_field": "product_id",
                            "position": result_list.index(best_choice) + 1,
                            "event_attributes": {}
                        })

                elif user["type"] == "brand_loyal":
                    # Brand loyal users look for specific brands
                    preferred_brands = ["Apple", "Sony", "Samsung"]
                    brand_items = [p["product_id"] for p in products
                                   if p["brand"] in preferred_brands and p["category"] == category_hint]

                    for pid in brand_items[:3]:
                        if pid in result_list:
                            position = result_list.index(pid) + 1
                            dwell = random.randint(30, 120)
                            events.append({
                                "action_name": "click",
                                "query_id": query_id,
                                "timestamp": event_time.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z',
                                "user_id": user["id"],
                                "session_id": session_id,
                                "object_id": pid,
                                "object_id_field": "product_id",
                                "position": position,
                                "dwell_time": dwell,
                                "event_attributes": {"brand_preference": True}
                            })
                            event_time += timedelta(seconds=dwell + 10)

                            if random.random() < 0.5:
                                events.append({
                                    "action_name": "purchase",
                                    "query_id": query_id,
                                    "timestamp": event_time.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z',
                                    "user_id": user["id"],
                                    "session_id": session_id,
                                    "object_id": pid,
                                    "object_id_field": "product_id",
                                    "position": position,
                                    "event_attributes": {}
                                })
                                break

                elif user["type"] in ["budget", "premium"]:
                    # Budget/Premium users filter by price
                    if user["type"] == "budget":
                        price_filter = lambda p: p.get("price", 9999) < 500
                    else:
                        price_filter = lambda p: p.get("price", 0) > 800

                    matching_products = [pid for pid in result_list
                                        if price_filter(product_by_id.get(pid, {}))]

                    for pid in matching_products[:3]:
                        position = result_list.index(pid) + 1
                        dwell = random.randint(20, 90)
                        events.append({
                            "action_name": "click",
                            "query_id": query_id,
                            "timestamp": event_time.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z',
                            "user_id": user["id"],
                            "session_id": session_id,
                            "object_id": pid,
                            "object_id_field": "product_id",
                            "position": position,
                            "dwell_time": dwell,
                            "event_attributes": {"price_range": user["type"]}
                        })
                        event_time += timedelta(seconds=dwell + 10)

                    # Add to cart for matching items in high relevance
                    for pid in high_rel:
                        if pid in matching_products and random.random() < 0.4:
                            events.append({
                                "action_name": "add_to_cart",
                                "query_id": query_id,
                                "timestamp": event_time.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z',
                                "user_id": user["id"],
                                "session_id": session_id,
                                "object_id": pid,
                                "object_id_field": "product_id",
                                "position": result_list.index(pid) + 1 if pid in result_list else 0,
                                "event_attributes": {}
                            })
                            break

    return queries, events


def add_sample_data(client: OpenSearch) -> dict:
    """Add comprehensive sample data for LTR training."""
    results = {"products_added": 0, "queries_added": 0, "events_added": 0}

    # Generate products
    products = generate_products()
    logger.info(f"Generated {len(products)} products")

    # Add embeddings and index products
    for product in products:
        try:
            # Generate random embedding (in production, use actual embedding model)
            product["embedding"] = [random.uniform(-1, 1) for _ in range(384)]
            client.index(
                index="products",
                id=product["product_id"],
                body=product,
                refresh=False
            )
            results["products_added"] += 1
        except Exception as e:
            logger.error(f"Failed to index product {product['product_id']}: {e}")

    # Generate LTR training data
    queries, events = generate_ltr_training_data(products)
    logger.info(f"Generated {len(queries)} queries and {len(events)} events")

    # Index queries
    for query in queries:
        try:
            client.index(
                index="ubi_queries",
                body=query,
                refresh=False
            )
            results["queries_added"] += 1
        except Exception as e:
            logger.error(f"Failed to index query: {e}")

    # Index events
    for event in events:
        try:
            client.index(
                index="ubi_events",
                body=event,
                refresh=False
            )
            results["events_added"] += 1
        except Exception as e:
            logger.error(f"Failed to index event: {e}")

    # Refresh indices
    try:
        client.indices.refresh(index="products,ubi_queries,ubi_events")
    except Exception as e:
        logger.warning(f"Failed to refresh indices: {e}")

    logger.info(f"Sample data results: {results}")
    return results


def handler(event, context):
    """
    Lambda handler for CDK Custom Resource Provider.

    IMPORTANT: When using CDK cr.Provider, the framework handles CloudFormation
    responses automatically. This handler should:
    - Return a dict with 'PhysicalResourceId' and 'Data' on success
    - Raise an exception on failure

    Do NOT call send_cfn_response or manually send responses to ResponseURL.
    """
    logger.info(f"Received event: {json.dumps(event)}")

    request_type = event.get('RequestType', 'Create')
    properties = event.get('ResourceProperties', {})

    # Extract parameters
    opensearch_endpoint = properties.get('OpenSearchEndpoint')
    master_user_secret_arn = properties.get('MasterUserSecretArn')
    lambda_role_arn = properties.get('LambdaRoleArn')
    osi_pipeline_role_arn = properties.get('OsiPipelineRoleArn')
    region = properties.get('Region', 'us-east-1')

    # Physical resource ID - use existing if updating, create new for create
    physical_resource_id = event.get('PhysicalResourceId') or f"opensearch-setup-{region}"

    if request_type == 'Delete':
        # Nothing to clean up on delete - indices persist
        logger.info("Delete request - no cleanup needed")
        return {
            'PhysicalResourceId': physical_resource_id,
            'Data': {
                'Message': 'Delete successful - no cleanup needed'
            }
        }

    if request_type in ['Create', 'Update']:
        # Get master user credentials
        secret = get_secret(master_user_secret_arn)
        username = secret['username']
        password = secret['password']

        # Create client with basic auth (master user)
        client = get_basic_auth_client(opensearch_endpoint, username, password)

        # 1. Map IAM roles to all_access
        roles_to_map = [lambda_role_arn, osi_pipeline_role_arn]
        map_iam_roles(client, roles_to_map)

        # 2. Create indices
        indices_result = create_indices(client)

        # 3. Add comprehensive sample data for LTR training
        sample_data_result = add_sample_data(client)

        result_data = {
            'Message': 'OpenSearch setup completed successfully',
            'IndicesCreated': json.dumps(indices_result),
            'SampleData': json.dumps(sample_data_result),
            'Endpoint': opensearch_endpoint
        }

        logger.info(f"Setup completed: {result_data}")

        # Return format expected by CDK Provider framework
        return {
            'PhysicalResourceId': physical_resource_id,
            'Data': result_data
        }

    # Unknown request type - still return success
    logger.warning(f"Unknown request type: {request_type}")
    return {
        'PhysicalResourceId': physical_resource_id,
        'Data': {
            'Message': f'Unknown request type: {request_type}'
        }
    }
