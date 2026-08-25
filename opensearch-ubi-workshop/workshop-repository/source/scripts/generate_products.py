#!/usr/bin/env python3
"""Deterministic electronics catalog generator for the VoltMall UBI/LTR sample.

Produces data/products.json (~2400 products). Re-running always yields the same
catalog (fixed seed) so judgments/models stay comparable across runs.
"""
import json
import os
import random

random.seed(20260703)

OUT = os.path.join(os.path.dirname(__file__), "..", "data", "products.json")

# category: (emoji, brands, series pool, price range(만원), spec builder keys)
CATALOG = {
    "노트북": {
        "emoji": "💻",
        "brands": ["삼성전자", "LG전자", "Apple", "레노버", "ASUS", "HP", "Dell", "MSI"],
        "series": {
            "삼성전자": ["갤럭시북4", "갤럭시북4 프로", "갤럭시북4 울트라", "노트북 플러스2"],
            "LG전자": ["그램 14", "그램 16", "그램 17", "그램 프로 16", "울트라PC"],
            "Apple": ["맥북 에어 13", "맥북 에어 15", "맥북 프로 14", "맥북 프로 16"],
            "레노버": ["씽크패드 X1 카본", "아이디어패드 슬림5", "리전5 프로", "요가 슬림7"],
            "ASUS": ["젠북 14 OLED", "비보북 15", "ROG 제피러스 G14", "TUF 게이밍 A15"],
            "HP": ["스펙터 x360", "파빌리온 15", "오멘 16", "엘리트북 840"],
            "Dell": ["XPS 13", "XPS 15", "인스피론 15", "에일리언웨어 m16"],
            "MSI": ["스텔스 14", "카타나 15", "프레스티지 16", "사이보그 15"],
        },
        "price": (59, 420),
        "specs": lambda r: {
            "화면": r.choice(["13.3인치", "14인치", "15.6인치", "16인치", "17인치"]),
            "CPU": r.choice(["인텔 Core Ultra 5", "인텔 Core Ultra 7", "인텔 Core i5", "AMD 라이젠7 8840HS", "Apple M4", "Apple M4 Pro"]),
            "RAM": r.choice(["16GB", "32GB", "8GB", "64GB"]),
            "저장장치": r.choice(["256GB SSD", "512GB SSD", "1TB SSD", "2TB SSD"]),
            "무게": r.choice(["0.99kg", "1.19kg", "1.4kg", "1.8kg", "2.1kg"]),
        },
        "adjectives": ["초경량", "고성능", "가성비", "게이밍", "휴대용", "업무용", "대학생 추천"],
    },
    "스마트폰": {
        "emoji": "📱",
        "brands": ["삼성전자", "Apple", "샤오미", "구글", "모토로라"],
        "series": {
            "삼성전자": ["갤럭시 S25", "갤럭시 S25 울트라", "갤럭시 Z 플립6", "갤럭시 Z 폴드6", "갤럭시 A56"],
            "Apple": ["아이폰 16", "아이폰 16 프로", "아이폰 16 프로 맥스", "아이폰 SE"],
            "샤오미": ["레드미 노트 14", "샤오미 14T", "포코 X7 프로"],
            "구글": ["픽셀 9", "픽셀 9 프로", "픽셀 8a"],
            "모토로라": ["엣지 50", "모토 G85", "레이저 50 울트라"],
        },
        "price": (29, 250),
        "specs": lambda r: {
            "화면": r.choice(["6.1인치", "6.4인치", "6.7인치", "6.9인치"]),
            "저장용량": r.choice(["128GB", "256GB", "512GB", "1TB"]),
            "색상": r.choice(["티타늄 블랙", "실버", "네이비", "라벤더", "민트"]),
            "배터리": r.choice(["4000mAh", "4700mAh", "5000mAh"]),
            "카메라": r.choice(["5000만 화소", "1억800만 화소", "2억 화소"]),
        },
        "adjectives": ["자급제", "5G", "폴더블", "카메라 특화", "대화면", "배터리 강화"],
    },
    "태블릿": {
        "emoji": "📲",
        "brands": ["삼성전자", "Apple", "레노버", "샤오미"],
        "series": {
            "삼성전자": ["갤럭시 탭 S10", "갤럭시 탭 S10 울트라", "갤럭시 탭 A9"],
            "Apple": ["아이패드 프로 13", "아이패드 에어 11", "아이패드 미니", "아이패드 10세대"],
            "레노버": ["탭 P12", "요가 탭 13"],
            "샤오미": ["패드 7", "패드 7 프로"],
        },
        "price": (25, 230),
        "specs": lambda r: {
            "화면": r.choice(["8.3인치", "10.9인치", "11인치", "12.9인치", "14.6인치"]),
            "저장용량": r.choice(["64GB", "128GB", "256GB", "512GB"]),
            "연결": r.choice(["Wi-Fi", "Wi-Fi+Cellular"]),
            "펜 지원": r.choice(["S펜 포함", "애플펜슬 별매", "펜 미지원"]),
        },
        "adjectives": ["필기용", "그림용", "인강용", "휴대용", "대화면", "가성비"],
    },
    "TV": {
        "emoji": "📺",
        "brands": ["삼성전자", "LG전자", "소니", "TCL", "샤오미"],
        "series": {
            "삼성전자": ["Neo QLED QN90D", "OLED S95D", "Crystal UHD DU8000", "The Frame"],
            "LG전자": ["올레드 evo C4", "올레드 evo G4", "QNED85", "울트라HD UT80"],
            "소니": ["브라비아 8 OLED", "브라비아 X90L"],
            "TCL": ["QM8 미니LED", "C755 QLED"],
            "샤오미": ["TV A Pro", "TV S 미니LED"],
        },
        "price": (35, 890),
        "specs": lambda r: {
            "화면": r.choice(["43인치", "55인치", "65인치", "75인치", "85인치"]),
            "해상도": r.choice(["4K UHD", "8K UHD"]),
            "패널": r.choice(["OLED", "QLED", "미니LED", "LED"]),
            "주사율": r.choice(["60Hz", "120Hz", "144Hz"]),
            "스마트": "스마트TV(넷플릭스/유튜브)",
        },
        "adjectives": ["거실용", "게이밍", "벽걸이", "스탠드", "영화감상용"],
    },
    "모니터": {
        "emoji": "🖥️",
        "brands": ["삼성전자", "LG전자", "Dell", "BenQ", "알파스캔", "MSI"],
        "series": {
            "삼성전자": ["오디세이 G8", "오디세이 G5", "뷰피니티 S9", "스마트모니터 M8"],
            "LG전자": ["울트라기어 27GP850", "울트라와이드 34WQ73", "울트라파인 32UN880"],
            "Dell": ["울트라샤프 U2723QE", "S2722DGM 게이밍"],
            "BenQ": ["EX2710Q 모비우스", "PD2705Q 디자이너"],
            "알파스캔": ["AOC 27G2", "AOC Q27G3XMN"],
            "MSI": ["MAG 274UPF", "G274QPF-QD"],
        },
        "price": (15, 180),
        "specs": lambda r: {
            "화면": r.choice(["24인치", "27인치", "32인치", "34인치 울트라와이드"]),
            "해상도": r.choice(["FHD", "QHD", "4K UHD"]),
            "주사율": r.choice(["75Hz", "144Hz", "165Hz", "240Hz"]),
            "패널": r.choice(["IPS", "VA", "OLED"]),
        },
        "adjectives": ["게이밍", "사무용", "디자이너용", "고주사율", "피벗 지원"],
    },
    "이어폰/헤드폰": {
        "emoji": "🎧",
        "brands": ["삼성전자", "Apple", "소니", "Bose", "젠하이저", "QCY", "앤커"],
        "series": {
            "삼성전자": ["갤럭시 버즈3 프로", "갤럭시 버즈3", "갤럭시 버즈 FE"],
            "Apple": ["에어팟 프로 2세대", "에어팟 4세대", "에어팟 맥스"],
            "소니": ["WH-1000XM5", "WF-1000XM5", "링크버즈 S"],
            "Bose": ["QC 울트라 헤드폰", "QC 울트라 이어버드"],
            "젠하이저": ["모멘텀 4", "모멘텀 트루와이어리스 4"],
            "QCY": ["T13 ANC", "멜로버즈 프로"],
            "앤커": ["사운드코어 리버티4", "사운드코어 스페이스 원"],
        },
        "price": (3, 65),
        "specs": lambda r: {
            "타입": r.choice(["커널형 무선", "오픈형 무선", "오버이어 헤드폰"]),
            "노이즈캔슬링": r.choice(["액티브 노이즈캔슬링", "노이즈캔슬링 미지원"]),
            "재생시간": r.choice(["6시간", "8시간", "24시간(케이스 포함)", "30시간"]),
            "방수": r.choice(["IPX4", "IPX5", "IPX7", "미지원"]),
        },
        "adjectives": ["블루투스", "무선", "노캔", "운동용", "통화품질", "가성비"],
    },
    "스피커": {
        "emoji": "🔊",
        "brands": ["JBL", "Bose", "소니", "마샬", "하만카돈", "브리츠"],
        "series": {
            "JBL": ["플립6", "차지5", "파티박스 110", "고3"],
            "Bose": ["사운드링크 플렉스", "사운드링크 맥스"],
            "소니": ["SRS-XB100", "SRS-XG300"],
            "마샬": ["엠버튼2", "스탠모어3", "액턴3"],
            "하만카돈": ["오라 스튜디오4", "오닉스 스튜디오8"],
            "브리츠": ["BR-1600BT", "BZ-T7800"],
        },
        "price": (3, 60),
        "specs": lambda r: {
            "타입": r.choice(["블루투스 포터블", "북쉘프", "사운드바"]),
            "출력": r.choice(["10W", "20W", "30W", "80W"]),
            "방수": r.choice(["IP67", "IPX5", "미지원"]),
            "재생시간": r.choice(["12시간", "20시간", "상시전원"]),
        },
        "adjectives": ["캠핑용", "파티용", "휴대용", "고음질", "우퍼 탑재"],
    },
    "카메라": {
        "emoji": "📷",
        "brands": ["소니", "캐논", "니콘", "후지필름", "고프로", "DJI"],
        "series": {
            "소니": ["A7 IV", "A6700", "ZV-E10 II", "RX100 VII"],
            "캐논": ["EOS R6 Mark II", "EOS R50", "EOS R100", "파워샷 G7X"],
            "니콘": ["Z6 III", "Z50 II", "Zf"],
            "후지필름": ["X-T5", "X100VI", "X-S20"],
            "고프로": ["히어로 13 블랙", "히어로 12"],
            "DJI": ["오즈모 포켓3", "오즈모 액션5 프로"],
        },
        "price": (35, 450),
        "specs": lambda r: {
            "센서": r.choice(["풀프레임", "APS-C", "1인치", "마이크로포서드"]),
            "화소": r.choice(["2420만", "3300만", "4020만", "6100만"]),
            "영상": r.choice(["4K 60p", "4K 120p", "6K 30p", "8K 30p"]),
            "손떨림보정": r.choice(["바디 5축 보정", "전자식 보정"]),
        },
        "adjectives": ["미러리스", "브이로그", "여행용", "입문용", "유튜버 추천"],
    },
    "게임/콘솔": {
        "emoji": "🎮",
        "brands": ["소니", "닌텐도", "마이크로소프트", "밸브", "레이저"],
        "series": {
            "소니": ["플레이스테이션5 프로", "플레이스테이션5 슬림", "PS 포탈"],
            "닌텐도": ["스위치 2", "스위치 OLED", "스위치 라이트"],
            "마이크로소프트": ["Xbox 시리즈 X", "Xbox 시리즈 S"],
            "밸브": ["스팀덱 OLED 512GB", "스팀덱 LCD 256GB"],
            "레이저": ["키시 울트라", "울버린 V2"],
        },
        "price": (15, 110),
        "specs": lambda r: {
            "저장용량": r.choice(["256GB", "512GB", "1TB", "2TB"]),
            "구성": r.choice(["본체+패드", "본체 단품", "디지털 에디션"]),
            "해상도": r.choice(["4K 120fps", "1440p", "8K 지원"]),
        },
        "adjectives": ["신형", "한정판", "패키지", "휴대용", "거치형"],
    },
    "키보드/마우스": {
        "emoji": "⌨️",
        "brands": ["로지텍", "레이저", "키크론", "앱코", "커세어", "리얼포스"],
        "series": {
            "로지텍": ["MX 키즈 S", "G913 TKL", "MX 마스터 3S", "G502 X", "K380"],
            "레이저": ["블랙위도우 V4", "데스애더 V3", "바실리스크 V3"],
            "키크론": ["K8 프로", "Q1 프로", "V3 맥스"],
            "앱코": ["K660", "해커 K640"],
            "커세어": ["K70 RGB 프로", "M65 울트라"],
            "리얼포스": ["R3S 무접점", "GX1 게이밍"],
        },
        "price": (2, 45),
        "specs": lambda r: {
            "타입": r.choice(["기계식 청축", "기계식 적축", "무접점", "멤브레인", "게이밍 마우스", "무선 마우스"]),
            "연결": r.choice(["유선", "블루투스", "무선 2.4GHz", "블루투스+2.4GHz"]),
            "백라이트": r.choice(["RGB", "화이트 LED", "미지원"]),
        },
        "adjectives": ["게이밍", "사무용", "텐키리스", "저소음", "인체공학"],
    },
    "냉장고": {
        "emoji": "🧊",
        "brands": ["삼성전자", "LG전자", "위니아", "캐리어"],
        "series": {
            "삼성전자": ["비스포크 냉장고 4도어", "비스포크 김치플러스", "일반형 냉장고"],
            "LG전자": ["디오스 오브제컬렉션", "디오스 김치톡톡", "일반형 냉장고"],
            "위니아": ["딤채 김치냉장고", "프라우드 4도어"],
            "캐리어": ["클라윈드 슬림", "모드비 냉장고"],
        },
        "price": (35, 450),
        "specs": lambda r: {
            "용량": r.choice(["300L", "500L", "615L", "870L"]),
            "도어": r.choice(["2도어", "3도어", "4도어"]),
            "색상": r.choice(["글램 화이트", "새틴 베이지", "메탈 실버", "글램 핑크"]),
            "에너지등급": r.choice(["1등급", "2등급"]),
        },
        "adjectives": ["대용량", "신혼가전", "김치냉장고", "미니", "절전형"],
    },
    "세탁기/건조기": {
        "emoji": "🧺",
        "brands": ["삼성전자", "LG전자", "위니아"],
        "series": {
            "삼성전자": ["비스포크 그랑데 AI 세탁기", "비스포크 그랑데 건조기", "워블 통돌이"],
            "LG전자": ["트롬 오브제 세탁기", "트롬 건조기", "통돌이 블랙라벨", "워시타워"],
            "위니아": ["클라쎄 드럼세탁기", "크린 통돌이"],
        },
        "price": (30, 350),
        "specs": lambda r: {
            "용량": r.choice(["12kg", "17kg", "21kg", "25kg"]),
            "타입": r.choice(["드럼", "통돌이", "건조기", "워시타워"]),
            "AI기능": r.choice(["AI 맞춤세탁", "미지원"]),
            "에너지등급": r.choice(["1등급", "2등급"]),
        },
        "adjectives": ["대용량", "신혼가전", "저소음", "스팀살균", "직렬설치"],
    },
    "에어컨/공기청정기": {
        "emoji": "❄️",
        "brands": ["삼성전자", "LG전자", "위닉스", "다이슨", "샤오미"],
        "series": {
            "삼성전자": ["비스포크 무풍에어컨 갤러리", "윈도우핏 창문형", "블루스카이 공기청정기"],
            "LG전자": ["휘센 타워 에어컨", "휘센 창호형", "퓨리케어 360 공기청정기"],
            "위닉스": ["타워 XQ 공기청정기", "제로S 공기청정기"],
            "다이슨": ["퓨리파이어 쿨 TP09", "핫앤쿨 HP07"],
            "샤오미": ["미에어 프로 4", "스마트 공기청정기 4"],
        },
        "price": (15, 320),
        "specs": lambda r: {
            "평형/면적": r.choice(["6평형", "16평형", "18평형", "58㎡", "100㎡"]),
            "타입": r.choice(["스탠드", "벽걸이", "창문형", "타워형"]),
            "필터": r.choice(["헤파 H13", "헤파 H14", "일체형 필터"]),
            "부가기능": r.choice(["무풍", "AI 절전", "IoT 원격제어", "제습 겸용"]),
        },
        "adjectives": ["원룸용", "거실용", "절전형", "저소음", "알레르기 케어"],
    },
    "청소기": {
        "emoji": "🧹",
        "brands": ["삼성전자", "LG전자", "다이슨", "로보락", "샤오미"],
        "series": {
            "삼성전자": ["비스포크 제트 AI", "비스포크 제트봇 콤보", "파워건"],
            "LG전자": ["코드제로 A9S", "코드제로 R9 로봇청소기", "오브제 M9"],
            "다이슨": ["V15 디텍트", "V12 슬림", "젠5 디텍트"],
            "로보락": ["S8 맥스V 울트라", "Q레보", "S8 프로 울트라"],
            "샤오미": ["로봇청소기 X20+", "무선청소기 G11"],
        },
        "price": (12, 190),
        "specs": lambda r: {
            "타입": r.choice(["무선 스틱", "로봇청소기", "물걸레 겸용"]),
            "흡입력": r.choice(["150W", "210W", "280AW", "8000Pa"]),
            "배터리": r.choice(["40분", "60분", "90분"]),
            "부가기능": r.choice(["자동 먼지비움", "물걸레 세척 스테이션", "AI 장애물 인식", "헤파필터"]),
        },
        "adjectives": ["무선", "로봇", "물걸레", "펫가족 추천", "원룸용"],
    },
    "주방가전": {
        "emoji": "🍳",
        "brands": ["쿠쿠", "쿠첸", "삼성전자", "LG전자", "필립스", "테팔", "발뮤다"],
        "series": {
            "쿠쿠": ["트윈프레셔 압력밥솥", "IH 전기밥솥 10인용", "정수기 인스퓨어"],
            "쿠첸": ["121 압력밥솥", "미니 밥솥 3인용"],
            "삼성전자": ["비스포크 큐커", "비스포크 전자레인지", "비스포크 인덕션"],
            "LG전자": ["디오스 광파오븐", "디오스 식기세척기 12인용", "디오스 인덕션"],
            "필립스": ["에어프라이어 XXL", "라떼고 커피머신", "블렌더 5000"],
            "테팔": ["매직핸즈 인덕션 프라이팬", "액티프라이", "전기포트 세이프티"],
            "발뮤다": ["더 토스터", "더 레인지", "더 포트"],
        },
        "price": (3, 120),
        "specs": lambda r: {
            "용량/인용": r.choice(["3인용", "6인용", "10인용", "5.5L", "1.8L"]),
            "타입": r.choice(["IH압력", "열판", "스팀", "컨벡션", "인덕션 3구"]),
            "부가기능": r.choice(["보온 12시간", "자동세척", "예약취사", "저소음"]),
        },
        "adjectives": ["신혼", "자취", "1인가구", "혼수", "미니멀"],
    },
}

GENERIC_TAGS = ["무료배송", "당일출고", "인기상품", "리뷰많은", "특가", "신상품", "베스트"]


def krw(min_man: int, max_man: int, r: random.Random) -> int:
    """Price in KRW rounded to a shopping-friendly value."""
    v = r.uniform(min_man, max_man) * 10000
    return int(round(v / 1000) * 1000 - 100)


def main() -> None:
    products = []
    pid = 0
    for category, cfg in CATALOG.items():
        brands = cfg["brands"]
        # 160 products per category -> 15 categories x 160 = 2400 products total
        per_cat = 160
        for i in range(per_cat):
            pid += 1
            r = random.Random(f"{category}-{i}-seed")
            brand = brands[i % len(brands)]
            series = r.choice(cfg["series"][brand])
            model_no = f"{r.choice('ABCDEFGHJKMNPQRSTVWX')}{r.randint(100, 999)}{r.choice(['', '-K', '-W', '-S', 'X', 'P'])}"
            specs = cfg["specs"](r)
            if category == "노트북" and "CPU" in specs:
                if brand == "Apple":
                    specs["CPU"] = r.choice(["Apple M4", "Apple M4 Pro", "Apple M3"])
                elif specs["CPU"].startswith("Apple"):
                    specs["CPU"] = r.choice(["인텔 Core Ultra 5", "인텔 Core Ultra 7", "인텔 Core i7", "AMD 라이젠7 8840HS", "AMD 라이젠5 7535HS"])
            adjective = r.choice(cfg["adjectives"])
            spec_head = list(specs.values())[0]
            name = f"{brand} {series} {model_no} {spec_head}"
            spec_txt = ", ".join(f"{k} {v}" for k, v in specs.items())
            description = (
                f"{adjective} {category} {brand} {series}. {spec_txt}. "
                f"{r.choice(['정품 보증 1년', '공식 인증 리셀러 상품', 'AS 2년 지원', '온라인 전용 모델'])}, "
                f"{r.choice(['무료배송', '오늘출발', '설치기사 방문 설치', '리뷰 이벤트 진행중'])}."
            )
            rating = round(r.uniform(3.4, 5.0), 1)
            review_count = int(r.betavariate(1.2, 6.0) * 4800)
            popularity = round(r.betavariate(1.5, 5.0), 4)
            tags = r.sample(GENERIC_TAGS, 3) + [adjective]
            products.append({
                "id": f"P{pid:04d}",
                "name": name,
                "brand": brand,
                "category": category,
                "series": series,
                "model_no": model_no,
                "description": description,
                "specs": specs,
                "price": krw(*cfg["price"], r),
                "currency": "KRW",
                "rating": rating,
                "review_count": review_count,
                "popularity": popularity,
                "stock": r.randint(0, 500),
                "release_year": r.choice([2023, 2024, 2025, 2026]),
                "emoji": cfg["emoji"],
                "tags": tags,
                # UBI-derived fields, updated by the extract pipeline step
                "ctr": 0.0,
                "cart_rate": 0.0,
                "click_count": 0,
            })
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(products, f, ensure_ascii=False, indent=1)
    print(f"wrote {len(products)} products -> {os.path.abspath(OUT)}")
    cats = {}
    for p in products:
        cats[p["category"]] = cats.get(p["category"], 0) + 1
    print(json.dumps(cats, ensure_ascii=False))


if __name__ == "__main__":
    main()
