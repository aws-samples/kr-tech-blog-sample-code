#!/usr/bin/env python3
"""Generate an importable OpenSearch Dashboards saved-objects NDJSON for the
VoltMall UBI/LTR demo.

Import via: Dashboards -> Stack Management -> Saved Objects -> Import
(or the API: POST /_dashboards/api/saved_objects/_import?overwrite=true)

The file contains 5 index patterns + 8 visualizations + 1 dashboard. Field
names and aggregations were verified live against the ltr-vector domain, and
migrationVersions mirror the versions this cluster's own saved objects use
(index-pattern 7.6.0 / visualization 7.10.0 / dashboard 7.9.3).
"""
import json
import os

OUT = os.path.join(os.path.dirname(__file__), "..", "dashboards", "voltmall-ubi-ltr.ndjson")

# ---- index patterns (fields omitted -> Dashboards refreshes on first open) ----
INDEX_PATTERNS = [
    ("ip-ubi-queries-ecom", "ubi_queries_ecom*", "@timestamp"),
    ("ip-ubi-events-ecom", "ubi_events_ecom*", "@timestamp"),
    ("ip-ecom-products", "ecom_products*", None),
    ("ip-ecom-judgments", "ecom_judgments*", "timestamp"),
    ("ip-ecom-ltr-metrics", "ecom_ltr_metrics*", "timestamp"),
]


def search_source(with_index_ref=True):
    s = {"query": {"query": "", "language": "kuery"}, "filter": []}
    if with_index_ref:
        s["indexRefName"] = "kibanaSavedObjectMeta.searchSourceJSON.index"
    return json.dumps(s)


def viz(vid, title, ip_id, vis_state):
    return {
        "id": vid,
        "type": "visualization",
        "attributes": {
            "title": title,
            "visState": json.dumps(vis_state, ensure_ascii=False),
            "uiStateJSON": "{}",
            "description": "",
            "version": 1,
            "kibanaSavedObjectMeta": {"searchSourceJSON": search_source(True)},
        },
        "references": [
            {"name": "kibanaSavedObjectMeta.searchSourceJSON.index",
             "type": "index-pattern", "id": ip_id}
        ],
        "migrationVersion": {"visualization": "7.10.0"},
    }


def metric(mid, agg_type, field=None, label=None):
    params = {"field": field} if field else {}
    a = {"id": mid, "enabled": True, "type": agg_type, "schema": "metric", "params": params}
    if label:
        a["params"]["customLabel"] = label
    return a


def terms(bid, field, size, schema="segment", order_by="1"):
    return {"id": bid, "enabled": True, "type": "terms", "schema": schema,
            "params": {"field": field, "size": size, "order": "desc", "orderBy": order_by,
                       "otherBucket": False, "missingBucket": False}}


VISUALS = [
    viz("viz-events-by-action", "VoltMall · UBI 액션 분포", "ip-ubi-events-ecom", {
        "title": "UBI 액션 분포", "type": "pie",
        "aggs": [metric("1", "count"), terms("2", "action_name", 10)],
        "params": {"type": "pie", "addTooltip": True, "addLegend": True, "isDonut": True,
                   "legendPosition": "right", "labels": {"show": True, "values": True}},
    }),
    viz("viz-events-over-time", "VoltMall · 행동 이벤트 추이", "ip-ubi-events-ecom", {
        "title": "행동 이벤트 추이", "type": "histogram",
        "aggs": [
            metric("1", "count"),
            {"id": "2", "enabled": True, "type": "date_histogram", "schema": "segment",
             "params": {"field": "@timestamp", "interval": "auto",
                        "useNormalizedOpenSearchInterval": True, "drop_partials": False,
                        "min_doc_count": 1}},
            terms("3", "action_name", 6, schema="group"),
        ],
        "params": {"type": "histogram", "grid": {"categoryLines": False},
                   "categoryAxes": [{"id": "CategoryAxis-1", "type": "category",
                                     "position": "bottom", "show": True, "scale": {"type": "linear"}}],
                   "valueAxes": [{"id": "ValueAxis-1", "position": "left", "show": True,
                                  "scale": {"type": "linear", "mode": "normal"}}],
                   "seriesParams": [{"show": True, "type": "histogram", "mode": "stacked",
                                     "data": {"label": "Count", "id": "1"}, "valueAxis": "ValueAxis-1"}],
                   "addTooltip": True, "addLegend": True, "legendPosition": "right"},
    }),
    viz("viz-total-searches", "VoltMall · 총 검색 수", "ip-ubi-queries-ecom", {
        "title": "총 검색 수", "type": "metric",
        "aggs": [metric("1", "count", label="검색(쿼리) 로그 수")],
        "params": {"metric": {"percentageMode": False, "useRanges": False,
                              "style": {"fontSize": 48}, "labels": {"show": True}}},
    }),
    viz("viz-top-queries", "VoltMall · 인기 검색어 Top 20", "ip-ubi-queries-ecom", {
        "title": "인기 검색어 Top 20", "type": "table",
        "aggs": [metric("1", "count", label="검색 수"),
                 terms("2", "user_query.keyword", 20, schema="bucket")],
        "params": {"perPage": 10, "showPartialRows": False, "showTotal": False,
                   "totalFunc": "sum", "showMetricsAtAllLevels": False},
    }),
    viz("viz-top-clicked-products", "VoltMall · 클릭 상위 상품", "ip-ecom-products", {
        "title": "클릭 상위 상품 (UBI 반영)", "type": "table",
        "aggs": [
            metric("1", "max", "click_count", "클릭수"),
            metric("3", "max", "ctr", "CTR"),
            metric("4", "max", "cart_rate", "장바구니율"),
            terms("2", "name.keyword", 20, schema="bucket", order_by="1"),
        ],
        "params": {"perPage": 10, "showPartialRows": False, "showTotal": False,
                   "totalFunc": "sum", "showMetricsAtAllLevels": False},
    }),
    viz("viz-ctr-by-category", "VoltMall · 카테고리별 평균 CTR", "ip-ecom-products", {
        "title": "카테고리별 평균 CTR", "type": "horizontal_bar",
        "aggs": [metric("1", "avg", "ctr", "평균 CTR"),
                 terms("2", "category.keyword", 20, order_by="1")],
        "params": {"type": "histogram",
                   "categoryAxes": [{"id": "CategoryAxis-1", "type": "category",
                                     "position": "left", "show": True, "scale": {"type": "linear"}}],
                   "valueAxes": [{"id": "ValueAxis-1", "position": "bottom", "show": True,
                                  "scale": {"type": "linear", "mode": "normal"}}],
                   "seriesParams": [{"show": True, "type": "histogram", "mode": "normal",
                                     "data": {"label": "평균 CTR", "id": "1"}, "valueAxis": "ValueAxis-1"}],
                   "addTooltip": True, "addLegend": False},
    }),
    viz("viz-judgment-grades", "VoltMall · 판정 등급 분포", "ip-ecom-judgments", {
        "title": "판정 등급 분포 (source별)", "type": "histogram",
        "aggs": [metric("1", "count"),
                 terms("2", "grade", 5, schema="segment"),
                 terms("3", "source", 5, schema="group")],
        "params": {"type": "histogram",
                   "categoryAxes": [{"id": "CategoryAxis-1", "type": "category",
                                     "position": "bottom", "show": True, "scale": {"type": "linear"}}],
                   "valueAxes": [{"id": "ValueAxis-1", "position": "left", "show": True,
                                  "scale": {"type": "linear", "mode": "normal"}}],
                   "seriesParams": [{"show": True, "type": "histogram", "mode": "stacked",
                                     "data": {"label": "Count", "id": "1"}, "valueAxis": "ValueAxis-1"}],
                   "addTooltip": True, "addLegend": True, "legendPosition": "right"},
    }),
    viz("viz-ltr-metrics", "VoltMall · LTR vs BM25 지표", "ip-ecom-ltr-metrics", {
        "title": "LTR vs BM25 (최근 run)", "type": "metric",
        "aggs": [
            metric("1", "max", "baseline.ndcg@10", "BM25 nDCG@10"),
            metric("2", "max", "ltr.ndcg@10", "LTR nDCG@10"),
            metric("3", "max", "lift_pct.ndcg@10", "nDCG 향상%"),
        ],
        "params": {"metric": {"percentageMode": False, "useRanges": False,
                              "style": {"fontSize": 36}, "labels": {"show": True}}},
    }),
]

DASHBOARD_ID = "dashboard-voltmall-ubi-ltr"

# grid layout: 48-col grid
LAYOUT = [
    ("viz-total-searches",       0,  0, 12, 8),
    ("viz-ltr-metrics",         12,  0, 24, 8),
    ("viz-events-by-action",    36,  0, 12, 8),
    ("viz-events-over-time",     0,  8, 48, 12),
    ("viz-top-queries",          0, 20, 24, 15),
    ("viz-top-clicked-products",24, 20, 24, 15),
    ("viz-ctr-by-category",      0, 35, 24, 14),
    ("viz-judgment-grades",     24, 35, 24, 14),
]


def build_dashboard():
    panels, refs = [], []
    for i, (vid, x, y, w, h) in enumerate(LAYOUT, 1):
        ref = f"panel_{i}"
        panels.append({"version": "7.10.0", "type": "visualization",
                       "gridData": {"x": x, "y": y, "w": w, "h": h, "i": str(i)},
                       "panelIndex": str(i), "embeddableConfig": {}, "panelRefName": ref})
        refs.append({"name": ref, "type": "visualization", "id": vid})
    return {
        "id": DASHBOARD_ID,
        "type": "dashboard",
        "attributes": {
            "title": "VoltMall · UBI → LTR 대시보드",
            "hits": 0,
            "description": "검색·클릭·장바구니·구매(UBI) 지표와 LLM 판정, LTR nDCG/Recall 성과",
            "panelsJSON": json.dumps(panels, ensure_ascii=False),
            "optionsJSON": json.dumps({"useMargins": True, "hidePanelTitles": False}),
            "version": 1,
            "timeRestore": False,
            "kibanaSavedObjectMeta": {"searchSourceJSON": search_source(False)},
        },
        "references": refs,
        "migrationVersion": {"dashboard": "7.9.3"},
    }


def main():
    objects = []
    for ip_id, title, tf in INDEX_PATTERNS:
        attrs = {"title": title}
        if tf:
            attrs["timeFieldName"] = tf
        objects.append({"id": ip_id, "type": "index-pattern", "attributes": attrs,
                        "references": [], "migrationVersion": {"index-pattern": "7.6.0"}})
    objects.extend(VISUALS)
    objects.append(build_dashboard())

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        for o in objects:
            f.write(json.dumps(o, ensure_ascii=False) + "\n")

    # validate: every reference id resolves within the file
    ids = {o["id"] for o in objects}
    dangling = [(o["id"], r["id"]) for o in objects for r in o.get("references", [])
                if r["id"] not in ids]
    assert not dangling, f"dangling references: {dangling}"
    print(f"wrote {len(objects)} saved objects -> {os.path.abspath(OUT)}")
    print(f"  index-patterns: {len(INDEX_PATTERNS)}, visualizations: {len(VISUALS)}, dashboards: 1")
    print("  all references resolve OK")


if __name__ == "__main__":
    main()
