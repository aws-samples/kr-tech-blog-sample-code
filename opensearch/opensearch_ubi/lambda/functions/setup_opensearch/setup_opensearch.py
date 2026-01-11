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
                "client_id": {"type": "keyword"},
                "query_response_hit_ids": {"type": "keyword"},
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
                "message": {"type": "keyword"},
                "event_attributes": {
                    "properties": {
                        "session_id": {"type": "keyword"},
                        "browser": {
                            "type": "text",
                            "fields": {"keyword": {"type": "keyword"}}
                        },
                        "dwell_time": {"type": "float"},
                        "result_count": {"type": "long"},
                        "position": {
                            "properties": {
                                "ordinal": {"type": "integer"},
                                "x": {"type": "integer"},
                                "y": {"type": "integer"},
                                "page_depth": {"type": "integer"},
                                "scroll_depth": {"type": "integer"},
                                "trail": {
                                    "type": "text",
                                    "fields": {"keyword": {"type": "keyword"}}
                                }
                            }
                        },
                        "object": {
                            "properties": {
                                "object_id": {"type": "keyword"},
                                "object_id_field": {"type": "keyword"},
                                "name": {"type": "keyword"},
                                "description": {
                                    "type": "text",
                                    "fields": {"keyword": {"type": "keyword"}}
                                },
                                "object_detail": {
                                    "properties": {
                                        "price": {"type": "float"},
                                        "margin": {"type": "float"},
                                        "cost": {"type": "float"},
                                        "supplier": {
                                            "type": "text",
                                            "fields": {"keyword": {"type": "keyword"}}
                                        },
                                        "isTrusted": {"type": "boolean"}
                                    }
                                }
                            }
                        }
                    }
                }
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
                "margin": {"type": "float"},
                "cost": {"type": "float"},
                "supplier": {"type": "keyword"},
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

    # UBI indices need to be recreated to ensure correct mappings
    ubi_indices = ["ubi_queries", "ubi_events"]

    for index_name, mapping in indices.items():
        try:
            # Force recreate UBI indices to apply correct mappings
            if index_name in ubi_indices and client.indices.exists(index=index_name):
                client.indices.delete(index=index_name)
                logger.info(f"Deleted existing index for recreation: {index_name}")

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

    # Brand to supplier mapping
    brand_suppliers = {
        "Samsung": "Samsung Electronics Co., Ltd.",
        "Apple": "Apple Inc.",
        "Google": "Google LLC",
        "OnePlus": "OnePlus Technology Co., Ltd.",
        "Xiaomi": "Xiaomi Corporation",
        "Dell": "Dell Technologies Inc.",
        "Lenovo": "Lenovo Group Limited",
        "ASUS": "ASUSTeK Computer Inc.",
        "HP": "HP Inc.",
        "Razer": "Razer Inc.",
        "Microsoft": "Microsoft Corporation",
        "Acer": "Acer Inc.",
        "Sony": "Sony Corporation",
        "Bose": "Bose Corporation",
        "Sennheiser": "Sennheiser electronic GmbH",
        "Jabra": "GN Audio A/S",
        "Beats": "Beats Electronics LLC",
        "Garmin": "Garmin Ltd.",
        "Fitbit": "Fitbit Inc.",
        "Fujifilm": "Fujifilm Corporation",
        "Canon": "Canon Inc.",
        "GoPro": "GoPro Inc.",
        "DJI": "SZ DJI Technology Co., Ltd.",
        "Nintendo": "Nintendo Co., Ltd.",
        "Valve": "Valve Corporation",
        "Meta": "Meta Platforms Inc.",
        "Anker": "Anker Innovations Limited",
        "Belkin": "Belkin International, Inc.",
        "Spigen": "Spigen Inc.",
        "UGREEN": "Ugreen Group Limited",
        "Twelve South": "Twelve South LLC",
        "Mophie": "mophie Inc.",
        "Nikon": "Nikon Corporation",
        "Panasonic": "Panasonic Holdings Corporation",
        "JBL": "Harman International Industries",
        "Audio-Technica": "Audio-Technica Corporation",
        "Bang & Olufsen": "Bang & Olufsen A/S",
        "Motorola": "Motorola Mobility LLC",
        "Nothing": "Nothing Technology Limited",
        "OPPO": "Guangdong OPPO Mobile Telecom",
        "Huawei": "Huawei Technologies Co., Ltd.",
        "LG": "LG Electronics Inc.",
        "MSI": "Micro-Star International Co., Ltd.",
        "Logitech": "Logitech International S.A.",
        "SteelSeries": "SteelSeries ApS",
        "HyperX": "HP Inc.",
        "Corsair": "Corsair Gaming, Inc.",
        "ADATA": "ADATA Technology Co., Ltd.",
        "SanDisk": "Western Digital Corporation",
        "Caseology": "Caseology Inc.",
        "OtterBox": "Otter Products, LLC",
        "PopSockets": "PopSockets LLC",
        "Nomad": "Nomad Goods Inc.",
        "Peak Design": "Peak Design Ltd.",
        "Withings": "Withings SAS",
        "Amazfit": "Huami Corporation",
        "Suunto": "Suunto Oy",
        "Polar": "Polar Electro Oy",
        "Insta360": "Arashi Vision Inc.",
        "Blackmagic": "Blackmagic Design Pty Ltd",
        "Amazon": "Amazon.com, Inc.",
    }

    def calc_margin_cost(price: float, brand: str) -> tuple[float, float]:
        """Calculate margin and cost based on price and brand."""
        # Premium brands have higher margins (20-25%), others 15-20%
        premium_brands = {"Apple", "Sony", "Bose", "Razer", "Garmin"}
        margin_rate = random.uniform(0.20, 0.25) if brand in premium_brands else random.uniform(0.15, 0.20)
        margin = round(price * margin_rate, 2)
        cost = round(price - margin, 2)
        return margin, cost

    # Smartphones (30 products)
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
        {"id": "phone-011", "name": "Samsung Galaxy S24+", "desc": "Large flagship with 6.7-inch display, Galaxy AI, 50MP camera", "brand": "Samsung", "price": 999.99, "rating": 4.7, "reviews": 1876, "tags": ["flagship", "android", "5g", "ai", "large-screen"]},
        {"id": "phone-012", "name": "iPhone 15 Plus", "desc": "Large iPhone with all-day battery, Dynamic Island, 48MP camera", "brand": "Apple", "price": 899.99, "rating": 4.6, "reviews": 2341, "tags": ["ios", "5g", "large-screen", "battery"]},
        {"id": "phone-013", "name": "Nothing Phone 2", "desc": "Unique design with Glyph interface, clean Android experience", "brand": "Nothing", "price": 599.99, "rating": 4.4, "reviews": 1123, "tags": ["midrange", "android", "5g", "design", "unique"]},
        {"id": "phone-014", "name": "OnePlus 12R", "desc": "Performance flagship with Snapdragon 8 Gen 2, 80W charging", "brand": "OnePlus", "price": 499.99, "rating": 4.5, "reviews": 987, "tags": ["value", "android", "5g", "fast-charging", "gaming"]},
        {"id": "phone-015", "name": "Xiaomi 13T Pro", "desc": "MediaTek Dimensity 9200+, Leica optics, 144Hz AMOLED", "brand": "Xiaomi", "price": 649.99, "rating": 4.4, "reviews": 765, "tags": ["midrange", "android", "5g", "leica", "display"]},
        {"id": "phone-016", "name": "OPPO Find X7 Ultra", "desc": "Quad camera with Hasselblad tuning, periscope telephoto", "brand": "OPPO", "price": 1199.99, "rating": 4.6, "reviews": 543, "tags": ["flagship", "android", "5g", "camera", "hasselblad"]},
        {"id": "phone-017", "name": "Motorola Edge 50 Pro", "desc": "Curved pOLED display, 125W fast charging, 50MP triple camera", "brand": "Motorola", "price": 699.99, "rating": 4.3, "reviews": 678, "tags": ["midrange", "android", "5g", "fast-charging", "curved"]},
        {"id": "phone-018", "name": "Samsung Galaxy Z Flip 5", "desc": "Compact foldable with large cover screen, Flex Mode", "brand": "Samsung", "price": 999.99, "rating": 4.5, "reviews": 1456, "tags": ["foldable", "android", "5g", "compact", "stylish"]},
        {"id": "phone-019", "name": "Google Pixel Fold", "desc": "Google foldable with Tensor G2, best-in-class cameras", "brand": "Google", "price": 1799.99, "rating": 4.3, "reviews": 432, "tags": ["foldable", "android", "5g", "ai", "premium"]},
        {"id": "phone-020", "name": "iPhone 15 Pro", "desc": "Pro iPhone with titanium, Action button, USB-C", "brand": "Apple", "price": 999.99, "rating": 4.8, "reviews": 4567, "tags": ["flagship", "ios", "5g", "titanium", "pro"]},
        {"id": "phone-021", "name": "Samsung Galaxy A34", "desc": "Budget 5G phone with Super AMOLED, long software support", "brand": "Samsung", "price": 349.99, "rating": 4.3, "reviews": 2876, "tags": ["budget", "android", "5g", "amoled", "value"]},
        {"id": "phone-022", "name": "Xiaomi Redmi Note 13 Pro+", "desc": "200MP camera, 120W charging, curved AMOLED display", "brand": "Xiaomi", "price": 399.99, "rating": 4.4, "reviews": 1987, "tags": ["budget", "android", "5g", "camera", "fast-charging"]},
        {"id": "phone-023", "name": "OnePlus Nord 3", "desc": "Dimensity 9000, 80W charging, flagship-level performance", "brand": "OnePlus", "price": 449.99, "rating": 4.4, "reviews": 1234, "tags": ["midrange", "android", "5g", "performance", "value"]},
        {"id": "phone-024", "name": "Nothing Phone 2a", "desc": "Affordable Nothing phone with Glyph, clean software", "brand": "Nothing", "price": 349.99, "rating": 4.3, "reviews": 654, "tags": ["budget", "android", "5g", "design", "clean"]},
        {"id": "phone-025", "name": "Motorola Razr 40 Ultra", "desc": "Premium flip phone with large external display", "brand": "Motorola", "price": 1099.99, "rating": 4.2, "reviews": 543, "tags": ["foldable", "android", "5g", "flip", "premium"]},
        {"id": "phone-026", "name": "OPPO Reno 11 Pro", "desc": "Portrait expert with telephoto, 80W charging", "brand": "OPPO", "price": 549.99, "rating": 4.3, "reviews": 876, "tags": ["midrange", "android", "5g", "portrait", "camera"]},
        {"id": "phone-027", "name": "Samsung Galaxy S24", "desc": "Compact flagship with AI features, 50MP camera", "brand": "Samsung", "price": 799.99, "rating": 4.6, "reviews": 2134, "tags": ["flagship", "android", "5g", "ai", "compact"]},
        {"id": "phone-028", "name": "Google Pixel 7a", "desc": "Previous gen Pixel with Tensor G2, great value", "brand": "Google", "price": 399.99, "rating": 4.5, "reviews": 2341, "tags": ["value", "android", "5g", "ai", "camera"]},
        {"id": "phone-029", "name": "Xiaomi 14", "desc": "Compact flagship with Leica optics, Snapdragon 8 Gen 3", "brand": "Xiaomi", "price": 799.99, "rating": 4.5, "reviews": 765, "tags": ["flagship", "android", "5g", "leica", "compact"]},
        {"id": "phone-030", "name": "OnePlus Open", "desc": "OnePlus foldable with Hasselblad cameras, slim design", "brand": "OnePlus", "price": 1699.99, "rating": 4.4, "reviews": 321, "tags": ["foldable", "android", "5g", "hasselblad", "premium"]},
    ]

    for p in smartphones:
        margin, cost = calc_margin_cost(p["price"], p["brand"])
        products.append({
            "product_id": p["id"], "name": p["name"], "description": p["desc"],
            "category": "smartphones", "subcategory": "mobile-phones",
            "brand": p["brand"], "price": p["price"], "margin": margin, "cost": cost,
            "supplier": brand_suppliers.get(p["brand"], p["brand"]),
            "rating": p["rating"], "review_count": p["reviews"],
            "in_stock": True, "tags": p["tags"]
        })

    # Laptops (30 products)
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
        {"id": "laptop-011", "name": "Dell XPS 13 Plus", "desc": "Compact premium laptop with edge-to-edge keyboard, Intel Core Ultra", "brand": "Dell", "price": 1399.99, "rating": 4.5, "reviews": 1234, "tags": ["ultrabook", "compact", "premium", "windows"]},
        {"id": "laptop-012", "name": "Lenovo Yoga 9i", "desc": "Premium 2-in-1 with rotating soundbar, 4K OLED touchscreen", "brand": "Lenovo", "price": 1699.99, "rating": 4.6, "reviews": 987, "tags": ["2-in-1", "oled", "premium", "windows"]},
        {"id": "laptop-013", "name": "ASUS ROG Strix G18", "desc": "18-inch gaming powerhouse with RTX 4080, 240Hz display", "brand": "ASUS", "price": 2499.99, "rating": 4.6, "reviews": 654, "tags": ["gaming", "rtx-4080", "large-screen", "high-performance"]},
        {"id": "laptop-014", "name": "HP Envy 16", "desc": "Creative laptop with RTX 4060, 16-inch 2K+ display", "brand": "HP", "price": 1299.99, "rating": 4.4, "reviews": 765, "tags": ["creative", "windows", "rtx", "content-creation"]},
        {"id": "laptop-015", "name": "MacBook Air 13 M3", "desc": "Ultra-portable laptop with M3 chip, fanless design, 18-hour battery", "brand": "Apple", "price": 1099.99, "rating": 4.8, "reviews": 3421, "tags": ["ultrabook", "portable", "macos", "fanless"]},
        {"id": "laptop-016", "name": "MSI Titan 18 HX", "desc": "Ultimate gaming laptop with i9-14900HX, RTX 4090, 18-inch 4K", "brand": "MSI", "price": 4999.99, "rating": 4.5, "reviews": 234, "tags": ["gaming", "rtx-4090", "flagship", "desktop-replacement"]},
        {"id": "laptop-017", "name": "Lenovo Legion Pro 7i", "desc": "Gaming laptop with i9, RTX 4080, 240Hz QHD display", "brand": "Lenovo", "price": 2799.99, "rating": 4.5, "reviews": 543, "tags": ["gaming", "rtx-4080", "high-performance", "windows"]},
        {"id": "laptop-018", "name": "Dell Inspiron 16 Plus", "desc": "Productivity laptop with Intel Core i7, 16-inch 3K display", "brand": "Dell", "price": 1199.99, "rating": 4.3, "reviews": 1123, "tags": ["productivity", "windows", "large-screen", "value"]},
        {"id": "laptop-019", "name": "ASUS Zenbook 14 OLED", "desc": "Slim ultrabook with 2.8K OLED display, Intel Core Ultra 7", "brand": "ASUS", "price": 999.99, "rating": 4.5, "reviews": 1456, "tags": ["ultrabook", "oled", "compact", "premium"]},
        {"id": "laptop-020", "name": "Microsoft Surface Pro 9", "desc": "Versatile 2-in-1 tablet with Windows 11, Intel Core i7", "brand": "Microsoft", "price": 1599.99, "rating": 4.4, "reviews": 1876, "tags": ["2-in-1", "tablet", "windows", "versatile"]},
        {"id": "laptop-021", "name": "Razer Blade 14", "desc": "Compact gaming laptop with AMD Ryzen 9, RTX 4070, 240Hz", "brand": "Razer", "price": 2799.99, "rating": 4.4, "reviews": 432, "tags": ["gaming", "compact", "rtx", "premium"]},
        {"id": "laptop-022", "name": "Acer Predator Helios 16", "desc": "Gaming laptop with RTX 4080, i9 processor, 500Hz display option", "brand": "Acer", "price": 2299.99, "rating": 4.4, "reviews": 567, "tags": ["gaming", "rtx-4080", "high-refresh", "windows"]},
        {"id": "laptop-023", "name": "HP Omen 16", "desc": "Gaming laptop with RTX 4070, 165Hz QHD display, advanced cooling", "brand": "HP", "price": 1599.99, "rating": 4.3, "reviews": 789, "tags": ["gaming", "rtx", "windows", "value"]},
        {"id": "laptop-024", "name": "Lenovo IdeaPad Pro 5", "desc": "Productivity laptop with AMD Ryzen 7, 2.5K display, all-metal build", "brand": "Lenovo", "price": 899.99, "rating": 4.3, "reviews": 654, "tags": ["productivity", "windows", "value", "amd"]},
        {"id": "laptop-025", "name": "Dell Latitude 7440", "desc": "Business laptop with Intel vPro, security features, durable build", "brand": "Dell", "price": 1499.99, "rating": 4.4, "reviews": 543, "tags": ["business", "security", "windows", "enterprise"]},
        {"id": "laptop-026", "name": "ASUS TUF Gaming A15", "desc": "Budget gaming laptop with RTX 4060, AMD Ryzen 7, military-grade durability", "brand": "ASUS", "price": 1099.99, "rating": 4.3, "reviews": 1234, "tags": ["gaming", "budget", "durable", "value"]},
        {"id": "laptop-027", "name": "LG Gram 17", "desc": "Ultra-light 17-inch laptop weighing only 1.35kg, all-day battery", "brand": "LG", "price": 1699.99, "rating": 4.4, "reviews": 432, "tags": ["ultrabook", "lightweight", "large-screen", "battery"]},
        {"id": "laptop-028", "name": "Samsung Galaxy Book4 Pro", "desc": "Premium AMOLED laptop with Intel Core Ultra, slim design", "brand": "Samsung", "price": 1449.99, "rating": 4.5, "reviews": 765, "tags": ["ultrabook", "amoled", "premium", "windows"]},
        {"id": "laptop-029", "name": "Acer Nitro 5", "desc": "Entry gaming laptop with RTX 4050, Intel Core i5, affordable", "brand": "Acer", "price": 799.99, "rating": 4.2, "reviews": 2134, "tags": ["gaming", "budget", "entry-level", "value"]},
        {"id": "laptop-030", "name": "HP Pavilion Plus 14", "desc": "Mainstream laptop with 2.8K OLED, Intel Core i7, good value", "brand": "HP", "price": 899.99, "rating": 4.3, "reviews": 987, "tags": ["mainstream", "oled", "value", "windows"]},
    ]

    for p in laptops:
        margin, cost = calc_margin_cost(p["price"], p["brand"])
        products.append({
            "product_id": p["id"], "name": p["name"], "description": p["desc"],
            "category": "laptops", "subcategory": "notebooks",
            "brand": p["brand"], "price": p["price"], "margin": margin, "cost": cost,
            "supplier": brand_suppliers.get(p["brand"], p["brand"]),
            "rating": p["rating"], "review_count": p["reviews"],
            "in_stock": True, "tags": p["tags"]
        })

    # Headphones & Earbuds (25 products)
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
        {"id": "audio-011", "name": "Bose QuietComfort Earbuds II", "desc": "Compact earbuds with CustomTune sound calibration and ANC", "brand": "Bose", "price": 279.99, "rating": 4.6, "reviews": 2134, "subcat": "earbuds", "tags": ["noise-cancelling", "wireless", "premium", "custom-fit"]},
        {"id": "audio-012", "name": "JBL Tour One M2", "desc": "Wireless headphones with True Adaptive ANC and spatial sound", "brand": "JBL", "price": 299.99, "rating": 4.4, "reviews": 987, "subcat": "headphones", "tags": ["noise-cancelling", "wireless", "spatial", "comfortable"]},
        {"id": "audio-013", "name": "Audio-Technica ATH-M50xBT2", "desc": "Professional studio headphones with wireless capability", "brand": "Audio-Technica", "price": 199.99, "rating": 4.6, "reviews": 1567, "subcat": "headphones", "tags": ["studio", "wireless", "professional", "accurate"]},
        {"id": "audio-014", "name": "Bang & Olufsen Beoplay H95", "desc": "Luxury wireless headphones with titanium drivers and premium materials", "brand": "Bang & Olufsen", "price": 899.99, "rating": 4.5, "reviews": 432, "subcat": "headphones", "tags": ["luxury", "wireless", "premium", "design"]},
        {"id": "audio-015", "name": "Samsung Galaxy Buds FE", "desc": "Feature-packed earbuds with ANC at an affordable price", "brand": "Samsung", "price": 99.99, "rating": 4.3, "reviews": 2341, "subcat": "earbuds", "tags": ["budget", "wireless", "anc", "value"]},
        {"id": "audio-016", "name": "Sony LinkBuds S", "desc": "Ultra-lightweight earbuds with ANC and open-ear design option", "brand": "Sony", "price": 199.99, "rating": 4.4, "reviews": 1234, "subcat": "earbuds", "tags": ["lightweight", "wireless", "anc", "comfortable"]},
        {"id": "audio-017", "name": "JBL Tune 770NC", "desc": "Budget-friendly headphones with hybrid ANC and 70-hour battery", "brand": "JBL", "price": 129.99, "rating": 4.2, "reviews": 1876, "subcat": "headphones", "tags": ["budget", "wireless", "anc", "battery"]},
        {"id": "audio-018", "name": "Beats Fit Pro", "desc": "Sports earbuds with secure fit, ANC, and Apple integration", "brand": "Beats", "price": 199.99, "rating": 4.4, "reviews": 1987, "subcat": "earbuds", "tags": ["sports", "wireless", "anc", "fitness"]},
        {"id": "audio-019", "name": "Sennheiser Momentum True Wireless 4", "desc": "Premium earbuds with audiophile sound and aptX Lossless", "brand": "Sennheiser", "price": 299.99, "rating": 4.6, "reviews": 765, "subcat": "earbuds", "tags": ["audiophile", "wireless", "lossless", "premium"]},
        {"id": "audio-020", "name": "Apple AirPods 3", "desc": "Standard AirPods with spatial audio and MagSafe charging", "brand": "Apple", "price": 169.99, "rating": 4.5, "reviews": 4321, "subcat": "earbuds", "tags": ["wireless", "ios", "spatial-audio", "magsafe"]},
        {"id": "audio-021", "name": "Jabra Elite 10", "desc": "Premium earbuds with Dolby Atmos and semi-open design", "brand": "Jabra", "price": 249.99, "rating": 4.5, "reviews": 654, "subcat": "earbuds", "tags": ["dolby-atmos", "wireless", "premium", "comfort"]},
        {"id": "audio-022", "name": "Bose SoundLink Flex", "desc": "Portable Bluetooth speaker with deep bass and rugged design", "brand": "Bose", "price": 149.99, "rating": 4.6, "reviews": 2876, "subcat": "speakers", "tags": ["portable", "bluetooth", "waterproof", "outdoor"]},
        {"id": "audio-023", "name": "Sony ULT Wear", "desc": "Bass-focused headphones with ULT button for extra thump", "brand": "Sony", "price": 199.99, "rating": 4.3, "reviews": 543, "subcat": "headphones", "tags": ["bass", "wireless", "anc", "fun"]},
        {"id": "audio-024", "name": "JBL Charge 5", "desc": "Powerful Bluetooth speaker with 20-hour battery and powerbank feature", "brand": "JBL", "price": 179.99, "rating": 4.7, "reviews": 5432, "subcat": "speakers", "tags": ["portable", "bluetooth", "waterproof", "powerbank"]},
        {"id": "audio-025", "name": "Beats Solo 4", "desc": "Compact on-ear headphones with 50-hour battery and Apple integration", "brand": "Beats", "price": 199.99, "rating": 4.3, "reviews": 876, "subcat": "headphones", "tags": ["on-ear", "wireless", "battery", "portable"]},
    ]

    for p in audio:
        margin, cost = calc_margin_cost(p["price"], p["brand"])
        products.append({
            "product_id": p["id"], "name": p["name"], "description": p["desc"],
            "category": "audio", "subcategory": p["subcat"],
            "brand": p["brand"], "price": p["price"], "margin": margin, "cost": cost,
            "supplier": brand_suppliers.get(p["brand"], p["brand"]),
            "rating": p["rating"], "review_count": p["reviews"],
            "in_stock": True, "tags": p["tags"]
        })

    # Smartwatches & Wearables (25 products)
    wearables = [
        {"id": "watch-001", "name": "Apple Watch Ultra 2", "desc": "Rugged smartwatch for extreme sports with titanium case, 36-hour battery", "brand": "Apple", "price": 799.99, "rating": 4.8, "reviews": 2134, "tags": ["rugged", "fitness", "ios", "premium"]},
        {"id": "watch-002", "name": "Apple Watch Series 9", "desc": "Advanced smartwatch with S9 chip, health monitoring, always-on display", "brand": "Apple", "price": 399.99, "rating": 4.7, "reviews": 4567, "tags": ["health", "fitness", "ios", "smartwatch"]},
        {"id": "watch-003", "name": "Samsung Galaxy Watch 6 Classic", "desc": "Premium smartwatch with rotating bezel, advanced health tracking", "brand": "Samsung", "price": 399.99, "rating": 4.5, "reviews": 2341, "tags": ["classic", "health", "android", "premium"]},
        {"id": "watch-004", "name": "Garmin Fenix 8", "desc": "Multisport GPS watch with solar charging, maps, advanced training features", "brand": "Garmin", "price": 999.99, "rating": 4.7, "reviews": 1234, "tags": ["sports", "gps", "outdoor", "solar"]},
        {"id": "watch-005", "name": "Fitbit Sense 2", "desc": "Health-focused smartwatch with stress management, ECG, skin temperature", "brand": "Fitbit", "price": 299.99, "rating": 4.3, "reviews": 3421, "tags": ["health", "fitness", "stress", "value"]},
        {"id": "watch-006", "name": "Google Pixel Watch 2", "desc": "Google smartwatch with Fitbit health tracking, Wear OS, AI features", "brand": "Google", "price": 349.99, "rating": 4.4, "reviews": 1567, "tags": ["health", "fitness", "android", "ai"]},
        {"id": "watch-007", "name": "Garmin Forerunner 965", "desc": "Premium running watch with AMOLED display, training metrics, maps", "brand": "Garmin", "price": 599.99, "rating": 4.6, "reviews": 876, "tags": ["running", "gps", "training", "amoled"]},
        {"id": "watch-008", "name": "Samsung Galaxy Watch 6", "desc": "Sleek smartwatch with BioActive sensor, sleep coaching, workout tracking", "brand": "Samsung", "price": 299.99, "rating": 4.4, "reviews": 2876, "tags": ["health", "fitness", "android", "sleep"]},
        {"id": "watch-009", "name": "Apple Watch SE 2", "desc": "Affordable Apple Watch with essential features and crash detection", "brand": "Apple", "price": 249.99, "rating": 4.5, "reviews": 3456, "tags": ["value", "fitness", "ios", "safety"]},
        {"id": "watch-010", "name": "Garmin Venu 3", "desc": "Lifestyle GPS smartwatch with health monitoring and AMOLED display", "brand": "Garmin", "price": 449.99, "rating": 4.5, "reviews": 987, "tags": ["lifestyle", "gps", "health", "amoled"]},
        {"id": "watch-011", "name": "Fitbit Charge 6", "desc": "Advanced fitness tracker with Google integration and stress management", "brand": "Fitbit", "price": 159.99, "rating": 4.4, "reviews": 2567, "tags": ["fitness", "tracker", "google", "value"]},
        {"id": "watch-012", "name": "Garmin Forerunner 265", "desc": "Running watch with AMOLED display, training readiness, recovery time", "brand": "Garmin", "price": 449.99, "rating": 4.6, "reviews": 765, "tags": ["running", "gps", "training", "amoled"]},
        {"id": "watch-013", "name": "Samsung Galaxy Watch Ultra", "desc": "Premium rugged smartwatch with titanium case and dual GPS", "brand": "Samsung", "price": 649.99, "rating": 4.5, "reviews": 432, "tags": ["rugged", "premium", "android", "outdoor"]},
        {"id": "watch-014", "name": "Withings ScanWatch 2", "desc": "Hybrid smartwatch with ECG, SpO2, and 30-day battery life", "brand": "Withings", "price": 349.99, "rating": 4.4, "reviews": 654, "tags": ["hybrid", "health", "ecg", "battery"]},
        {"id": "watch-015", "name": "Amazfit GTR 4", "desc": "Feature-packed smartwatch with dual-band GPS and 14-day battery", "brand": "Amazfit", "price": 199.99, "rating": 4.3, "reviews": 1876, "tags": ["value", "gps", "battery", "fitness"]},
        {"id": "watch-016", "name": "Garmin Instinct 2X Solar", "desc": "Rugged outdoor GPS watch with unlimited solar battery life", "brand": "Garmin", "price": 449.99, "rating": 4.6, "reviews": 543, "tags": ["rugged", "solar", "outdoor", "gps"]},
        {"id": "watch-017", "name": "Suunto Race", "desc": "Sports watch with AMOLED display, offline maps, 100m water resistance", "brand": "Suunto", "price": 449.99, "rating": 4.4, "reviews": 321, "tags": ["sports", "maps", "waterproof", "amoled"]},
        {"id": "watch-018", "name": "Polar Vantage V3", "desc": "Premium multisport watch with biosensing and performance insights", "brand": "Polar", "price": 599.99, "rating": 4.5, "reviews": 234, "tags": ["sports", "training", "biosensing", "premium"]},
        {"id": "watch-019", "name": "Fitbit Versa 4", "desc": "Smartwatch with 6+ day battery, Google apps, and health tracking", "brand": "Fitbit", "price": 229.99, "rating": 4.3, "reviews": 1987, "tags": ["smartwatch", "health", "google", "battery"]},
        {"id": "watch-020", "name": "Garmin Enduro 3", "desc": "Ultra-endurance GPS watch with 90-hour battery and solar charging", "brand": "Garmin", "price": 899.99, "rating": 4.7, "reviews": 187, "tags": ["endurance", "ultra", "solar", "premium"]},
        {"id": "watch-021", "name": "Amazfit T-Rex Ultra", "desc": "Rugged outdoor smartwatch with dive mode and extreme temperature rating", "brand": "Amazfit", "price": 399.99, "rating": 4.4, "reviews": 654, "tags": ["rugged", "dive", "outdoor", "extreme"]},
        {"id": "watch-022", "name": "Samsung Galaxy Fit 3", "desc": "Slim fitness band with AMOLED display and 13-day battery", "brand": "Samsung", "price": 59.99, "rating": 4.2, "reviews": 1234, "tags": ["fitness", "band", "value", "battery"]},
        {"id": "watch-023", "name": "Suunto Vertical", "desc": "Adventure GPS watch with offline maps and 85-hour GPS battery", "brand": "Suunto", "price": 629.99, "rating": 4.5, "reviews": 234, "tags": ["adventure", "maps", "gps", "battery"]},
        {"id": "watch-024", "name": "Polar Ignite 3", "desc": "Fitness watch with sleep tracking, FitSpark workouts, and GPS", "brand": "Polar", "price": 329.99, "rating": 4.4, "reviews": 432, "tags": ["fitness", "sleep", "gps", "training"]},
        {"id": "watch-025", "name": "Garmin Lily 2", "desc": "Stylish small smartwatch for women with health monitoring", "brand": "Garmin", "price": 249.99, "rating": 4.3, "reviews": 765, "tags": ["style", "small", "health", "women"]},
    ]

    for p in wearables:
        margin, cost = calc_margin_cost(p["price"], p["brand"])
        products.append({
            "product_id": p["id"], "name": p["name"], "description": p["desc"],
            "category": "wearables", "subcategory": "smartwatches",
            "brand": p["brand"], "price": p["price"], "margin": margin, "cost": cost,
            "supplier": brand_suppliers.get(p["brand"], p["brand"]),
            "rating": p["rating"], "review_count": p["reviews"],
            "in_stock": True, "tags": p["tags"]
        })

    # Tablets (20 products)
    tablets = [
        {"id": "tablet-001", "name": "iPad Pro 12.9 M4", "desc": "Ultimate iPad with M4 chip, OLED display, Apple Pencil Pro support", "brand": "Apple", "price": 1099.99, "rating": 4.9, "reviews": 2341, "tags": ["professional", "creative", "oled", "pencil"]},
        {"id": "tablet-002", "name": "iPad Air M2", "desc": "Versatile tablet with M2 chip, 10.9-inch display, great for productivity", "brand": "Apple", "price": 599.99, "rating": 4.7, "reviews": 3456, "tags": ["versatile", "productivity", "m2", "value"]},
        {"id": "tablet-003", "name": "Samsung Galaxy Tab S9 Ultra", "desc": "Massive 14.6-inch AMOLED tablet with S Pen, DeX support", "brand": "Samsung", "price": 1199.99, "rating": 4.6, "reviews": 1234, "tags": ["large", "amoled", "android", "productivity"]},
        {"id": "tablet-004", "name": "iPad 10th Gen", "desc": "Colorful iPad with A14 chip, USB-C, great for everyday use", "brand": "Apple", "price": 449.99, "rating": 4.5, "reviews": 4567, "tags": ["value", "colorful", "usb-c", "everyday"]},
        {"id": "tablet-005", "name": "Samsung Galaxy Tab S9", "desc": "Compact flagship tablet with S Pen, IP68 water resistance", "brand": "Samsung", "price": 849.99, "rating": 4.5, "reviews": 1876, "tags": ["compact", "waterproof", "android", "s-pen"]},
        {"id": "tablet-006", "name": "Microsoft Surface Pro 9", "desc": "2-in-1 tablet with Windows 11, kickstand, detachable keyboard", "brand": "Microsoft", "price": 999.99, "rating": 4.4, "reviews": 2134, "tags": ["2-in-1", "windows", "productivity", "business"]},
        {"id": "tablet-007", "name": "iPad Pro 11 M4", "desc": "Compact pro tablet with M4 chip, ProMotion, Face ID", "brand": "Apple", "price": 999.99, "rating": 4.8, "reviews": 1987, "tags": ["professional", "compact", "m4", "creative"]},
        {"id": "tablet-008", "name": "Samsung Galaxy Tab S9+", "desc": "Large AMOLED tablet with S Pen and premium features", "brand": "Samsung", "price": 999.99, "rating": 4.5, "reviews": 987, "tags": ["large", "amoled", "android", "premium"]},
        {"id": "tablet-009", "name": "iPad mini 6", "desc": "Compact 8.3-inch tablet with A15 chip, Apple Pencil support", "brand": "Apple", "price": 499.99, "rating": 4.6, "reviews": 2876, "tags": ["compact", "portable", "pencil", "ios"]},
        {"id": "tablet-010", "name": "Samsung Galaxy Tab A9+", "desc": "Affordable Android tablet with large display for entertainment", "brand": "Samsung", "price": 269.99, "rating": 4.2, "reviews": 1567, "tags": ["budget", "entertainment", "android", "value"]},
        {"id": "tablet-011", "name": "Lenovo Tab P12 Pro", "desc": "Premium Android tablet with OLED display and productivity features", "brand": "Lenovo", "price": 679.99, "rating": 4.4, "reviews": 654, "tags": ["premium", "oled", "android", "productivity"]},
        {"id": "tablet-012", "name": "Microsoft Surface Go 3", "desc": "Compact 2-in-1 tablet for portability and light productivity", "brand": "Microsoft", "price": 399.99, "rating": 4.1, "reviews": 876, "tags": ["compact", "2-in-1", "windows", "portable"]},
        {"id": "tablet-013", "name": "Xiaomi Pad 6 Pro", "desc": "High-performance Android tablet with 144Hz display", "brand": "Xiaomi", "price": 499.99, "rating": 4.4, "reviews": 765, "tags": ["performance", "high-refresh", "android", "value"]},
        {"id": "tablet-014", "name": "Amazon Fire Max 11", "desc": "Large Fire tablet with productivity dock support", "brand": "Amazon", "price": 229.99, "rating": 4.2, "reviews": 2341, "tags": ["budget", "entertainment", "alexa", "large"]},
        {"id": "tablet-015", "name": "OnePlus Pad", "desc": "Premium Android tablet with MediaTek Dimensity 9000", "brand": "OnePlus", "price": 479.99, "rating": 4.3, "reviews": 543, "tags": ["premium", "android", "stylus", "performance"]},
        {"id": "tablet-016", "name": "Lenovo Tab P11 Pro Gen 2", "desc": "OLED tablet with JBL speakers and productivity keyboard", "brand": "Lenovo", "price": 399.99, "rating": 4.3, "reviews": 432, "tags": ["oled", "entertainment", "android", "jbl"]},
        {"id": "tablet-017", "name": "Samsung Galaxy Tab S6 Lite 2024", "desc": "Affordable tablet with S Pen included for note-taking", "brand": "Samsung", "price": 329.99, "rating": 4.3, "reviews": 1876, "tags": ["budget", "s-pen", "android", "students"]},
        {"id": "tablet-018", "name": "iPad 9th Gen", "desc": "Classic iPad design with A13 chip at budget price", "brand": "Apple", "price": 329.99, "rating": 4.5, "reviews": 5432, "tags": ["value", "classic", "ios", "budget"]},
        {"id": "tablet-019", "name": "ASUS ROG Flow Z13", "desc": "Gaming tablet with RTX 4050, detachable keyboard", "brand": "ASUS", "price": 1499.99, "rating": 4.3, "reviews": 321, "tags": ["gaming", "rtx", "windows", "portable"]},
        {"id": "tablet-020", "name": "Huawei MatePad Pro 13.2", "desc": "Large OLED tablet with M-Pencil and productivity focus", "brand": "Huawei", "price": 799.99, "rating": 4.4, "reviews": 234, "tags": ["large", "oled", "productivity", "stylus"]},
    ]

    for p in tablets:
        margin, cost = calc_margin_cost(p["price"], p["brand"])
        products.append({
            "product_id": p["id"], "name": p["name"], "description": p["desc"],
            "category": "tablets", "subcategory": "tablet-computers",
            "brand": p["brand"], "price": p["price"], "margin": margin, "cost": cost,
            "supplier": brand_suppliers.get(p["brand"], p["brand"]),
            "rating": p["rating"], "review_count": p["reviews"],
            "in_stock": True, "tags": p["tags"]
        })

    # Cameras (20 products)
    cameras = [
        {"id": "camera-001", "name": "Sony A7 IV", "desc": "Full-frame mirrorless camera with 33MP sensor, 4K video, advanced AF", "brand": "Sony", "price": 2499.99, "rating": 4.8, "reviews": 1234, "subcat": "mirrorless", "tags": ["full-frame", "mirrorless", "4k", "professional"]},
        {"id": "camera-002", "name": "Canon EOS R6 Mark II", "desc": "Fast mirrorless camera with 24MP sensor, excellent autofocus, 6K video", "brand": "Canon", "price": 2499.99, "rating": 4.7, "reviews": 987, "subcat": "mirrorless", "tags": ["full-frame", "mirrorless", "6k", "fast-af"]},
        {"id": "camera-003", "name": "Sony ZV-E10 II", "desc": "Vlogging camera with APS-C sensor, flip screen, excellent video features", "brand": "Sony", "price": 999.99, "rating": 4.6, "reviews": 1567, "subcat": "mirrorless", "tags": ["vlogging", "aps-c", "4k", "content-creator"]},
        {"id": "camera-004", "name": "Fujifilm X-T5", "desc": "Retro-styled mirrorless with 40MP sensor, film simulations", "brand": "Fujifilm", "price": 1699.99, "rating": 4.7, "reviews": 876, "subcat": "mirrorless", "tags": ["retro", "aps-c", "film-simulation", "photography"]},
        {"id": "camera-005", "name": "GoPro Hero 12 Black", "desc": "Action camera with 5.3K video, HyperSmooth stabilization, waterproof", "brand": "GoPro", "price": 399.99, "rating": 4.5, "reviews": 3421, "subcat": "action", "tags": ["action", "waterproof", "5k", "adventure"]},
        {"id": "camera-006", "name": "DJI Osmo Pocket 3", "desc": "Pocket gimbal camera with 1-inch sensor, 4K video, 3-axis stabilization", "brand": "DJI", "price": 519.99, "rating": 4.6, "reviews": 1234, "subcat": "gimbal", "tags": ["gimbal", "pocket", "4k", "stabilization"]},
        {"id": "camera-007", "name": "Sony A7R V", "desc": "High-resolution 61MP full-frame camera with AI AF system", "brand": "Sony", "price": 3899.99, "rating": 4.8, "reviews": 654, "subcat": "mirrorless", "tags": ["full-frame", "high-resolution", "ai-af", "professional"]},
        {"id": "camera-008", "name": "Canon EOS R5", "desc": "Professional mirrorless with 45MP sensor, 8K video, IBIS", "brand": "Canon", "price": 3899.99, "rating": 4.8, "reviews": 1234, "subcat": "mirrorless", "tags": ["full-frame", "8k", "professional", "ibis"]},
        {"id": "camera-009", "name": "Nikon Z8", "desc": "Flagship mirrorless with 45.7MP sensor, 8K video, rugged build", "brand": "Nikon", "price": 3999.99, "rating": 4.7, "reviews": 543, "subcat": "mirrorless", "tags": ["full-frame", "8k", "flagship", "rugged"]},
        {"id": "camera-010", "name": "Fujifilm X-S20", "desc": "Compact mirrorless with 26MP sensor, 6.2K video, AI AF", "brand": "Fujifilm", "price": 1299.99, "rating": 4.6, "reviews": 765, "subcat": "mirrorless", "tags": ["compact", "aps-c", "6k", "ai-af"]},
        {"id": "camera-011", "name": "Sony A6700", "desc": "Flagship APS-C mirrorless with AI AF, 4K 120p video", "brand": "Sony", "price": 1399.99, "rating": 4.6, "reviews": 876, "subcat": "mirrorless", "tags": ["aps-c", "ai-af", "4k", "flagship"]},
        {"id": "camera-012", "name": "Canon EOS R8", "desc": "Lightweight full-frame mirrorless with 24.2MP and 4K video", "brand": "Canon", "price": 1499.99, "rating": 4.5, "reviews": 654, "subcat": "mirrorless", "tags": ["full-frame", "lightweight", "4k", "value"]},
        {"id": "camera-013", "name": "Nikon Z6 III", "desc": "Versatile full-frame with 24.5MP, partially stacked sensor", "brand": "Nikon", "price": 2499.99, "rating": 4.6, "reviews": 432, "subcat": "mirrorless", "tags": ["full-frame", "versatile", "6k", "hybrid"]},
        {"id": "camera-014", "name": "Panasonic Lumix S5 II", "desc": "Full-frame with phase-detect AF, 6K video, excellent IBIS", "brand": "Panasonic", "price": 1999.99, "rating": 4.5, "reviews": 543, "subcat": "mirrorless", "tags": ["full-frame", "6k", "ibis", "video"]},
        {"id": "camera-015", "name": "GoPro Hero 11 Black Mini", "desc": "Compact action camera with 5.3K video, rugged design", "brand": "GoPro", "price": 299.99, "rating": 4.4, "reviews": 1234, "subcat": "action", "tags": ["action", "compact", "5k", "rugged"]},
        {"id": "camera-016", "name": "DJI Action 4", "desc": "Action camera with 4K 120fps, 1/1.3-inch sensor, magnetic mount", "brand": "DJI", "price": 349.99, "rating": 4.5, "reviews": 876, "subcat": "action", "tags": ["action", "4k", "magnetic", "waterproof"]},
        {"id": "camera-017", "name": "Insta360 X4", "desc": "360 camera with 8K video, invisible selfie stick, AI editing", "brand": "Insta360", "price": 499.99, "rating": 4.5, "reviews": 654, "subcat": "action", "tags": ["360", "8k", "vr", "creative"]},
        {"id": "camera-018", "name": "Canon EOS R100", "desc": "Entry-level mirrorless for beginners with 24.1MP sensor", "brand": "Canon", "price": 479.99, "rating": 4.2, "reviews": 987, "subcat": "mirrorless", "tags": ["entry-level", "aps-c", "beginner", "compact"]},
        {"id": "camera-019", "name": "Blackmagic Pocket Cinema 6K G2", "desc": "Cinema camera with Super 35 sensor, 6K recording, pro features", "brand": "Blackmagic", "price": 1995.99, "rating": 4.6, "reviews": 321, "subcat": "cinema", "tags": ["cinema", "6k", "professional", "video"]},
        {"id": "camera-020", "name": "DJI Mavic 3 Pro", "desc": "Professional drone with Hasselblad camera, triple lens system", "brand": "DJI", "price": 2199.99, "rating": 4.7, "reviews": 876, "subcat": "drone", "tags": ["drone", "hasselblad", "4k", "professional"]},
    ]

    for p in cameras:
        margin, cost = calc_margin_cost(p["price"], p["brand"])
        products.append({
            "product_id": p["id"], "name": p["name"], "description": p["desc"],
            "category": "cameras", "subcategory": p["subcat"],
            "brand": p["brand"], "price": p["price"], "margin": margin, "cost": cost,
            "supplier": brand_suppliers.get(p["brand"], p["brand"]),
            "rating": p["rating"], "review_count": p["reviews"],
            "in_stock": True, "tags": p["tags"]
        })

    # Gaming (20 products)
    gaming = [
        {"id": "gaming-001", "name": "PlayStation 5", "desc": "Next-gen gaming console with ultra-fast SSD, 4K gaming, DualSense controller", "brand": "Sony", "price": 499.99, "rating": 4.8, "reviews": 8765, "subcat": "consoles", "tags": ["console", "4k", "gaming", "exclusive"]},
        {"id": "gaming-002", "name": "Xbox Series X", "desc": "Most powerful Xbox with 4K gaming, Game Pass, backward compatibility", "brand": "Microsoft", "price": 499.99, "rating": 4.7, "reviews": 6543, "subcat": "consoles", "tags": ["console", "4k", "game-pass", "powerful"]},
        {"id": "gaming-003", "name": "Nintendo Switch OLED", "desc": "Hybrid gaming console with OLED screen, portable and docked modes", "brand": "Nintendo", "price": 349.99, "rating": 4.7, "reviews": 7654, "subcat": "consoles", "tags": ["hybrid", "portable", "oled", "nintendo"]},
        {"id": "gaming-004", "name": "Steam Deck OLED", "desc": "Handheld PC gaming device with OLED display, full Steam library access", "brand": "Valve", "price": 549.99, "rating": 4.6, "reviews": 2341, "subcat": "handheld", "tags": ["handheld", "pc-gaming", "oled", "steam"]},
        {"id": "gaming-005", "name": "Meta Quest 3", "desc": "Mixed reality VR headset with high-res displays, full-color passthrough", "brand": "Meta", "price": 499.99, "rating": 4.5, "reviews": 3456, "subcat": "vr", "tags": ["vr", "mixed-reality", "standalone", "gaming"]},
        {"id": "gaming-006", "name": "ASUS ROG Ally", "desc": "Windows handheld gaming device with powerful AMD chip, 1080p display", "brand": "ASUS", "price": 599.99, "rating": 4.3, "reviews": 1234, "subcat": "handheld", "tags": ["handheld", "windows", "pc-gaming", "portable"]},
        {"id": "gaming-007", "name": "PlayStation 5 Slim", "desc": "Slimmer PS5 with smaller footprint, detachable disc drive option", "brand": "Sony", "price": 449.99, "rating": 4.7, "reviews": 2134, "subcat": "consoles", "tags": ["console", "4k", "slim", "gaming"]},
        {"id": "gaming-008", "name": "Xbox Series S", "desc": "Compact digital Xbox with 1440p gaming, Game Pass ready", "brand": "Microsoft", "price": 299.99, "rating": 4.5, "reviews": 4321, "subcat": "consoles", "tags": ["console", "digital", "compact", "value"]},
        {"id": "gaming-009", "name": "Nintendo Switch Lite", "desc": "Portable-only Switch with smaller form factor, built-in controls", "brand": "Nintendo", "price": 199.99, "rating": 4.5, "reviews": 5432, "subcat": "handheld", "tags": ["handheld", "portable", "nintendo", "value"]},
        {"id": "gaming-010", "name": "Steam Deck LCD", "desc": "Original Steam Deck with LCD display, PC gaming on the go", "brand": "Valve", "price": 399.99, "rating": 4.5, "reviews": 3456, "subcat": "handheld", "tags": ["handheld", "pc-gaming", "steam", "value"]},
        {"id": "gaming-011", "name": "Meta Quest 3S", "desc": "Affordable mixed reality headset with Quest 3 features", "brand": "Meta", "price": 299.99, "rating": 4.4, "reviews": 1234, "subcat": "vr", "tags": ["vr", "mixed-reality", "standalone", "value"]},
        {"id": "gaming-012", "name": "Lenovo Legion Go", "desc": "Windows handheld with detachable controllers, 8.8-inch QHD display", "brand": "Lenovo", "price": 699.99, "rating": 4.2, "reviews": 654, "subcat": "handheld", "tags": ["handheld", "windows", "detachable", "large-screen"]},
        {"id": "gaming-013", "name": "Razer Edge", "desc": "Android gaming handheld with 5G option, cloud gaming ready", "brand": "Razer", "price": 399.99, "rating": 4.1, "reviews": 432, "subcat": "handheld", "tags": ["handheld", "android", "cloud-gaming", "5g"]},
        {"id": "gaming-014", "name": "Logitech G Cloud", "desc": "Cloud gaming handheld with 7-inch display, lightweight design", "brand": "Logitech", "price": 349.99, "rating": 4.0, "reviews": 543, "subcat": "handheld", "tags": ["handheld", "cloud-gaming", "lightweight", "android"]},
        {"id": "gaming-015", "name": "PlayStation VR2", "desc": "Next-gen VR for PS5 with OLED displays, eye tracking, haptic feedback", "brand": "Sony", "price": 549.99, "rating": 4.4, "reviews": 1876, "subcat": "vr", "tags": ["vr", "ps5", "oled", "haptic"]},
        {"id": "gaming-016", "name": "SteelSeries Arctis Nova Pro", "desc": "Premium gaming headset with active noise cancelling, hot-swap battery", "brand": "SteelSeries", "price": 349.99, "rating": 4.6, "reviews": 1234, "subcat": "accessories", "tags": ["headset", "gaming", "anc", "premium"]},
        {"id": "gaming-017", "name": "Razer BlackShark V2 Pro", "desc": "Wireless gaming headset with THX spatial audio, 70-hour battery", "brand": "Razer", "price": 199.99, "rating": 4.5, "reviews": 2341, "subcat": "accessories", "tags": ["headset", "wireless", "gaming", "thx"]},
        {"id": "gaming-018", "name": "Xbox Elite Controller Series 2", "desc": "Pro controller with adjustable tension thumbsticks, paddles", "brand": "Microsoft", "price": 179.99, "rating": 4.4, "reviews": 3456, "subcat": "accessories", "tags": ["controller", "pro", "xbox", "customizable"]},
        {"id": "gaming-019", "name": "DualSense Edge", "desc": "Pro controller for PS5 with remappable buttons, adjustable triggers", "brand": "Sony", "price": 199.99, "rating": 4.3, "reviews": 1567, "subcat": "accessories", "tags": ["controller", "pro", "ps5", "customizable"]},
        {"id": "gaming-020", "name": "MSI MEG Trident X2", "desc": "Compact gaming desktop with RTX 4090, i9 processor, small form factor", "brand": "MSI", "price": 4299.99, "rating": 4.5, "reviews": 234, "subcat": "desktops", "tags": ["desktop", "rtx-4090", "compact", "high-end"]},
    ]

    for p in gaming:
        margin, cost = calc_margin_cost(p["price"], p["brand"])
        products.append({
            "product_id": p["id"], "name": p["name"], "description": p["desc"],
            "category": "gaming", "subcategory": p["subcat"],
            "brand": p["brand"], "price": p["price"], "margin": margin, "cost": cost,
            "supplier": brand_suppliers.get(p["brand"], p["brand"]),
            "rating": p["rating"], "review_count": p["reviews"],
            "in_stock": True, "tags": p["tags"]
        })

    # Accessories (30 products) - NEW CATEGORY
    accessories = [
        {"id": "acc-001", "name": "Anker 737 GaNPrime 120W Charger", "desc": "Compact 120W USB-C charger with 3 ports, GaN technology", "brand": "Anker", "price": 89.99, "rating": 4.7, "reviews": 3421, "subcat": "chargers", "tags": ["charger", "usb-c", "gan", "fast-charging"]},
        {"id": "acc-002", "name": "Belkin BoostCharge Pro 3-in-1", "desc": "MagSafe charging stand for iPhone, Apple Watch, and AirPods", "brand": "Belkin", "price": 149.99, "rating": 4.6, "reviews": 2134, "subcat": "chargers", "tags": ["magsafe", "wireless", "apple", "charging-stand"]},
        {"id": "acc-003", "name": "Spigen Tough Armor iPhone 15 Pro Case", "desc": "Heavy-duty protective case with kickstand, military-grade protection", "brand": "Spigen", "price": 34.99, "rating": 4.6, "reviews": 5432, "subcat": "cases", "tags": ["case", "iphone", "protective", "kickstand"]},
        {"id": "acc-004", "name": "UGREEN 100W USB-C Cable 2m", "desc": "Braided USB-C to USB-C cable with 100W PD and 480Mbps data", "brand": "UGREEN", "price": 15.99, "rating": 4.5, "reviews": 8765, "subcat": "cables", "tags": ["cable", "usb-c", "fast-charging", "braided"]},
        {"id": "acc-005", "name": "Twelve South BookArc for MacBook", "desc": "Vertical stand for MacBook in clamshell mode, aluminum design", "brand": "Twelve South", "price": 59.99, "rating": 4.7, "reviews": 1234, "subcat": "stands", "tags": ["stand", "macbook", "aluminum", "desk"]},
        {"id": "acc-006", "name": "Mophie Snap+ Powerstation", "desc": "10,000mAh MagSafe power bank with snap adapter", "brand": "Mophie", "price": 79.99, "rating": 4.4, "reviews": 1567, "subcat": "chargers", "tags": ["powerbank", "magsafe", "portable", "wireless"]},
        {"id": "acc-007", "name": "Anker Nano II 65W Charger", "desc": "Ultra-compact 65W USB-C charger for laptops and phones", "brand": "Anker", "price": 39.99, "rating": 4.7, "reviews": 4567, "subcat": "chargers", "tags": ["charger", "usb-c", "compact", "laptop"]},
        {"id": "acc-008", "name": "Belkin Screen Protector iPhone 15 Pro", "desc": "Tempered glass screen protector with easy align tray", "brand": "Belkin", "price": 39.99, "rating": 4.5, "reviews": 3421, "subcat": "screen-protectors", "tags": ["screen-protector", "iphone", "tempered-glass", "easy-install"]},
        {"id": "acc-009", "name": "Spigen Rugged Armor Galaxy S24 Ultra", "desc": "Slim protective case with carbon fiber design, air cushion", "brand": "Spigen", "price": 29.99, "rating": 4.5, "reviews": 2876, "subcat": "cases", "tags": ["case", "samsung", "slim", "carbon-fiber"]},
        {"id": "acc-010", "name": "UGREEN USB-C Hub 10-in-1", "desc": "Multiport hub with HDMI, USB-A, USB-C, SD card, Ethernet", "brand": "UGREEN", "price": 69.99, "rating": 4.4, "reviews": 2341, "subcat": "cables", "tags": ["hub", "usb-c", "hdmi", "multiport"]},
        {"id": "acc-011", "name": "Twelve South HiRise 3 Deluxe", "desc": "3-in-1 wireless charging stand for iPhone, Apple Watch, AirPods", "brand": "Twelve South", "price": 129.99, "rating": 4.6, "reviews": 876, "subcat": "chargers", "tags": ["wireless", "charging-stand", "apple", "premium"]},
        {"id": "acc-012", "name": "Anker PowerCore 26800mAh", "desc": "High-capacity power bank with dual USB ports and fast charging", "brand": "Anker", "price": 65.99, "rating": 4.6, "reviews": 6543, "subcat": "chargers", "tags": ["powerbank", "high-capacity", "usb", "travel"]},
        {"id": "acc-013", "name": "OtterBox Defender iPhone 15 Pro Max", "desc": "Ultimate protection case with multi-layer defense, port covers", "brand": "OtterBox", "price": 64.99, "rating": 4.5, "reviews": 3876, "subcat": "cases", "tags": ["case", "iphone", "rugged", "military-grade"]},
        {"id": "acc-014", "name": "Caseology Parallax Galaxy S24", "desc": "3D geometric design case with secure grip and slim profile", "brand": "Caseology", "price": 19.99, "rating": 4.4, "reviews": 1987, "subcat": "cases", "tags": ["case", "samsung", "design", "grip"]},
        {"id": "acc-015", "name": "Belkin Thunderbolt 4 Cable 2m", "desc": "High-speed Thunderbolt 4 cable with 40Gbps and 100W PD", "brand": "Belkin", "price": 49.99, "rating": 4.6, "reviews": 987, "subcat": "cables", "tags": ["cable", "thunderbolt", "fast-data", "high-speed"]},
        {"id": "acc-016", "name": "UGREEN MagSafe Battery Pack", "desc": "5000mAh magnetic wireless power bank for iPhone", "brand": "UGREEN", "price": 35.99, "rating": 4.3, "reviews": 2134, "subcat": "chargers", "tags": ["powerbank", "magsafe", "wireless", "compact"]},
        {"id": "acc-017", "name": "Nomad Base One Max", "desc": "Premium MagSafe charging base with metal and glass design", "brand": "Nomad", "price": 149.99, "rating": 4.5, "reviews": 543, "subcat": "chargers", "tags": ["magsafe", "wireless", "premium", "design"]},
        {"id": "acc-018", "name": "Peak Design Mobile Tripod", "desc": "Compact tripod with magnetic mount for smartphone photography", "brand": "Peak Design", "price": 89.99, "rating": 4.6, "reviews": 765, "subcat": "stands", "tags": ["tripod", "mobile", "magnetic", "photography"]},
        {"id": "acc-019", "name": "Spigen EZ Fit Glas.tR Galaxy Watch 6", "desc": "Tempered glass protector for Galaxy Watch with easy installation", "brand": "Spigen", "price": 14.99, "rating": 4.4, "reviews": 1234, "subcat": "screen-protectors", "tags": ["screen-protector", "watch", "tempered-glass", "samsung"]},
        {"id": "acc-020", "name": "Anker 735 Charger (Nano II 65W)", "desc": "3-port compact charger with 2 USB-C and 1 USB-A", "brand": "Anker", "price": 54.99, "rating": 4.6, "reviews": 2567, "subcat": "chargers", "tags": ["charger", "usb-c", "multiport", "compact"]},
        {"id": "acc-021", "name": "Belkin USB-C to Lightning Cable 2m", "desc": "MFi certified cable for fast charging iPhone", "brand": "Belkin", "price": 24.99, "rating": 4.5, "reviews": 4321, "subcat": "cables", "tags": ["cable", "lightning", "mfi", "iphone"]},
        {"id": "acc-022", "name": "OtterBox Symmetry Clear iPhone 15", "desc": "Slim clear case with military-grade drop protection", "brand": "OtterBox", "price": 49.99, "rating": 4.5, "reviews": 2876, "subcat": "cases", "tags": ["case", "iphone", "clear", "slim"]},
        {"id": "acc-023", "name": "UGREEN Tablet Stand Adjustable", "desc": "Aluminum adjustable stand for tablets and phones, foldable", "brand": "UGREEN", "price": 25.99, "rating": 4.5, "reviews": 3654, "subcat": "stands", "tags": ["stand", "tablet", "adjustable", "aluminum"]},
        {"id": "acc-024", "name": "Mophie 3-in-1 Travel Charger", "desc": "Foldable travel charger for iPhone, Apple Watch, AirPods", "brand": "Mophie", "price": 149.99, "rating": 4.4, "reviews": 654, "subcat": "chargers", "tags": ["wireless", "travel", "apple", "foldable"]},
        {"id": "acc-025", "name": "PopSockets MagSafe Grip", "desc": "Magnetic phone grip with swappable top, MagSafe compatible", "brand": "PopSockets", "price": 29.99, "rating": 4.3, "reviews": 5678, "subcat": "cases", "tags": ["grip", "magsafe", "accessory", "customizable"]},
        {"id": "acc-026", "name": "Twelve South Curve SE MacBook Stand", "desc": "Ergonomic aluminum stand for MacBook, raises screen height", "brand": "Twelve South", "price": 49.99, "rating": 4.6, "reviews": 987, "subcat": "stands", "tags": ["stand", "macbook", "ergonomic", "aluminum"]},
        {"id": "acc-027", "name": "Anker 313 Wireless Charger Pad", "desc": "10W Qi wireless charging pad with LED indicator", "brand": "Anker", "price": 15.99, "rating": 4.4, "reviews": 7654, "subcat": "chargers", "tags": ["wireless", "qi", "charging-pad", "value"]},
        {"id": "acc-028", "name": "SanDisk 1TB Extreme Portable SSD", "desc": "Rugged portable SSD with 1050MB/s read speed, IP65 rated", "brand": "SanDisk", "price": 99.99, "rating": 4.7, "reviews": 4321, "subcat": "cables", "tags": ["ssd", "portable", "fast", "rugged"]},
        {"id": "acc-029", "name": "Spigen Ultra Hybrid Apple Watch Band", "desc": "Transparent protective band for Apple Watch with secure fit", "brand": "Spigen", "price": 24.99, "rating": 4.4, "reviews": 1567, "subcat": "cases", "tags": ["watch-band", "apple-watch", "transparent", "protective"]},
        {"id": "acc-030", "name": "Belkin MagSafe Car Vent Mount Pro", "desc": "Magnetic car mount for iPhone with vent clip, adjustable viewing", "brand": "Belkin", "price": 39.99, "rating": 4.5, "reviews": 2134, "subcat": "stands", "tags": ["car-mount", "magsafe", "vent", "magnetic"]},
    ]

    for p in accessories:
        margin, cost = calc_margin_cost(p["price"], p["brand"])
        products.append({
            "product_id": p["id"], "name": p["name"], "description": p["desc"],
            "category": "accessories", "subcategory": p["subcat"],
            "brand": p["brand"], "price": p["price"], "margin": margin, "cost": cost,
            "supplier": brand_suppliers.get(p["brand"], p["brand"]),
            "rating": p["rating"], "review_count": p["reviews"],
            "in_stock": True, "tags": p["tags"]
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

    # Browser list for random selection
    browsers = [
        "Chrome/120.0", "Chrome/121.0", "Firefox/122.0", "Safari/17.2",
        "Edge/120.0", "Chrome/119.0", "Firefox/121.0", "Safari/17.1"
    ]

    # Message templates for different actions (defined here for use in create_event)
    action_messages = {
        "search": ["User searched for products", "Search query submitted", "Product search initiated", "User looking for items"],
        "click": ["User clicked on product", "Product detail viewed", "User opened product page", "Product selected from results"],
        "add_to_cart": ["Product added to cart", "User added item to shopping cart", "Item placed in cart", "Added to basket"],
        "purchase": ["Order completed", "Purchase confirmed", "User bought product", "Transaction successful"],
    }

    def create_event(
        action: str,
        query_id: str,
        timestamp: str,
        user_id: str,
        session_id: str,
        product: dict | None,
        position: int,
        dwell_time: float | None = None,
        result_count: int | None = None,
        extra_attrs: dict | None = None
    ) -> dict:
        """Create event with new nested schema structure."""
        # Select appropriate message for action
        messages = action_messages.get(action, [f"user {action} product"])
        message = random.choice(messages)

        event = {
            "action_name": action,
            "query_id": query_id,
            "timestamp": timestamp,
            "client_id": f"client-{user_id}",
            "user_id": user_id,
            "message": message,
            "event_attributes": {
                "session_id": session_id,
                "browser": random.choice(browsers),
                "position": {"ordinal": position},
            }
        }

        if dwell_time is not None:
            event["event_attributes"]["dwell_time"] = float(dwell_time)

        if result_count is not None:
            event["event_attributes"]["result_count"] = result_count

        if product:
            event["event_attributes"]["object"] = {
                "object_id": product["product_id"],
                "object_id_field": "product_id",
                "name": product["name"],
                "description": product.get("description", ""),
                "object_detail": {
                    "price": product.get("price", 0.0),
                    "margin": product.get("margin", 0.0),
                    "cost": product.get("cost", 0.0),
                    "supplier": product.get("supplier", ""),
                    "isTrusted": True
                }
            }

        if extra_attrs:
            for k, v in extra_attrs.items():
                event["event_attributes"][k] = v

        return event

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
                query_response_id = str(uuid.uuid4())
                query_time = session_time + timedelta(minutes=random.randint(0, 60))

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

                result_count = len(result_list)

                # Create query with query_response_id and hit IDs
                queries.append({
                    "query_id": query_id,
                    "query_response_id": query_response_id,
                    "user_query": query_text,
                    "timestamp": query_time.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z',
                    "user_id": user["id"],
                    "client_id": f"client-{user['id']}",
                    "session_id": session_id,
                    "application": "search-app",
                    "query_response_hit_ids": result_list,
                    "query_attributes": {"category_hint": category_hint}
                })

                # Create search event with result_count
                search_event_time = query_time + timedelta(milliseconds=random.randint(100, 500))
                events.append(create_event(
                    action="search",
                    query_id=query_id,
                    timestamp=search_event_time.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z',
                    user_id=user["id"],
                    session_id=session_id,
                    product=None,
                    position=0,
                    result_count=result_count,
                    extra_attrs={"query_text": query_text}
                ))

                # Generate events based on user behavior type
                event_time = query_time + timedelta(seconds=random.randint(2, 10))

                if user["type"] == "researcher":
                    # Researchers click multiple items, spend time reading
                    click_count = random.randint(3, 5)
                    for i, pid in enumerate(result_list[:click_count]):
                        position = i + 1
                        dwell = random.randint(30, 180) if pid in high_rel else random.randint(5, 30)
                        product = product_by_id.get(pid)
                        events.append(create_event(
                            action="click",
                            query_id=query_id,
                            timestamp=event_time.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z',
                            user_id=user["id"],
                            session_id=session_id,
                            product=product,
                            position=position,
                            dwell_time=dwell,
                            extra_attrs={"source": "search_results"}
                        ))
                        event_time += timedelta(seconds=dwell + random.randint(2, 10))

                    # Sometimes add to cart (40% chance for highly relevant)
                    for pid in high_rel[:2]:
                        if pid in result_list and random.random() < 0.4:
                            product = product_by_id.get(pid)
                            events.append(create_event(
                                action="add_to_cart",
                                query_id=query_id,
                                timestamp=event_time.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z',
                                user_id=user["id"],
                                session_id=session_id,
                                product=product,
                                position=result_list.index(pid) + 1 if pid in result_list else 0,
                                extra_attrs={"source": "product_page"}
                            ))

                elif user["type"] == "impulse":
                    # Impulse buyers click 1-2 items and quickly purchase
                    if high_rel and result_list:
                        # Find highly relevant in results
                        for pid in high_rel[:1]:
                            if pid in result_list:
                                position = result_list.index(pid) + 1
                                product = product_by_id.get(pid)
                                dwell = random.randint(20, 60)
                                events.append(create_event(
                                    action="click",
                                    query_id=query_id,
                                    timestamp=event_time.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z',
                                    user_id=user["id"],
                                    session_id=session_id,
                                    product=product,
                                    position=position,
                                    dwell_time=dwell
                                ))
                                event_time += timedelta(seconds=random.randint(30, 90))

                                # High chance of purchase
                                if random.random() < 0.6:
                                    events.append(create_event(
                                        action="purchase",
                                        query_id=query_id,
                                        timestamp=event_time.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z',
                                        user_id=user["id"],
                                        session_id=session_id,
                                        product=product,
                                        position=position
                                    ))
                                break

                elif user["type"] == "comparison":
                    # Comparison shoppers click many items, comparing them
                    click_count = random.randint(4, 6)
                    clicked_items = []
                    for i, pid in enumerate(result_list[:click_count]):
                        position = i + 1
                        dwell = random.randint(15, 90)
                        clicked_items.append(pid)
                        product = product_by_id.get(pid)
                        events.append(create_event(
                            action="click",
                            query_id=query_id,
                            timestamp=event_time.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z',
                            user_id=user["id"],
                            session_id=session_id,
                            product=product,
                            position=position,
                            dwell_time=dwell
                        ))
                        event_time += timedelta(seconds=dwell + 5)

                    # Add the best one to cart (prefer highly relevant)
                    best_choice = None
                    for pid in high_rel:
                        if pid in clicked_items:
                            best_choice = pid
                            break
                    if best_choice:
                        product = product_by_id.get(best_choice)
                        events.append(create_event(
                            action="add_to_cart",
                            query_id=query_id,
                            timestamp=event_time.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z',
                            user_id=user["id"],
                            session_id=session_id,
                            product=product,
                            position=result_list.index(best_choice) + 1
                        ))

                elif user["type"] == "brand_loyal":
                    # Brand loyal users look for specific brands
                    preferred_brands = ["Apple", "Sony", "Samsung"]
                    brand_items = [p["product_id"] for p in products
                                   if p["brand"] in preferred_brands and p["category"] == category_hint]

                    for pid in brand_items[:3]:
                        if pid in result_list:
                            position = result_list.index(pid) + 1
                            dwell = random.randint(30, 120)
                            product = product_by_id.get(pid)
                            events.append(create_event(
                                action="click",
                                query_id=query_id,
                                timestamp=event_time.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z',
                                user_id=user["id"],
                                session_id=session_id,
                                product=product,
                                position=position,
                                dwell_time=dwell,
                                extra_attrs={"brand_preference": True}
                            ))
                            event_time += timedelta(seconds=dwell + 10)

                            if random.random() < 0.5:
                                events.append(create_event(
                                    action="purchase",
                                    query_id=query_id,
                                    timestamp=event_time.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z',
                                    user_id=user["id"],
                                    session_id=session_id,
                                    product=product,
                                    position=position
                                ))
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
                        product = product_by_id.get(pid)
                        events.append(create_event(
                            action="click",
                            query_id=query_id,
                            timestamp=event_time.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z',
                            user_id=user["id"],
                            session_id=session_id,
                            product=product,
                            position=position,
                            dwell_time=dwell,
                            extra_attrs={"price_range": user["type"]}
                        ))
                        event_time += timedelta(seconds=dwell + 10)

                    # Add to cart for matching items in high relevance
                    for pid in high_rel:
                        if pid in matching_products and random.random() < 0.4:
                            product = product_by_id.get(pid)
                            events.append(create_event(
                                action="add_to_cart",
                                query_id=query_id,
                                timestamp=event_time.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z',
                                user_id=user["id"],
                                session_id=session_id,
                                product=product,
                                position=result_list.index(pid) + 1 if pid in result_list else 0
                            ))
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
