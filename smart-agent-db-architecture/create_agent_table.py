#!/usr/bin/env python3
import boto3
import json
from botocore.exceptions import ClientError


def create_dynamodb_table():
    """DynamoDB 테이블 생성"""
    dynamodb = boto3.client("dynamodb")

    table_name = "AgentTable"

    try:
        # 테이블 생성
        response = dynamodb.create_table(
            TableName=table_name,
            KeySchema=[
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "PK", "AttributeType": "S"},
                {"AttributeName": "SK", "AttributeType": "S"},
                {"AttributeName": "GSI1_PK", "AttributeType": "S"},
                {"AttributeName": "GSI1_SK", "AttributeType": "S"},
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "GSI1",
                    "KeySchema": [
                        {"AttributeName": "GSI1_PK", "KeyType": "HASH"},
                        {"AttributeName": "GSI1_SK", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                }
            ],
            BillingMode="PAY_PER_REQUEST",
        )

        print(f"테이블 '{table_name}' 생성 중...")

        # 테이블 생성 완료 대기
        waiter = dynamodb.get_waiter("table_exists")
        waiter.wait(TableName=table_name)

        print(f"테이블 '{table_name}' 생성 완료!")
        return True

    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceInUseException":
            print(f"테이블 '{table_name}'이 이미 존재합니다.")
            return True
        else:
            print(f"테이블 생성 실패: {e}")
            return False


def insert_sample_data():
    """샘플 데이터 입력"""
    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.Table("AgentTable")

    # 샘플 데이터 정의
    sample_items = [
        # 도메인 데이터
        {
            "PK": "DMN001",
            "SK": "METADATA",
            "EntityType": "Domain",
            "GSI1_PK": "Domain",
            "GSI1_SK": "매장검색서비스",
            "DomainNM": "매장검색서비스",
            "Description": "지역 기반의 매장 검색 서비스로 사용자가 요청한 지역의 카페, 레스토랑을 다양한 카테고리별로 검색하여 찾아주는 서비스",
        },
        # 에이전트 데이터
        {
            "PK": "AGT001",
            "SK": "METADATA",
            "EntityType": "Agent",
            "GSI1_PK": "DMN001",
            "GSI1_SK": "AGTSCORE#60",
            "AgentNM": "매장 검색 에이전트",
            "Score": "60",
            "Description": "지역기반 매장 검색서비스로 최근매장 리스트업이 잘되있음",
        },
        {
            "PK": "AGT002",
            "SK": "METADATA",
            "EntityType": "Agent",
            "GSI1_PK": "DMN001",
            "GSI1_SK": "AGTSCORE#40",
            "AgentNM": "매장 검색 에이전트2",
            "Score": "40",
            "Description": "지역 기반 매장 검색 및 추천 서비스 제공",
        },
        {
            "PK": "AGT003",
            "SK": "METADATA",
            "EntityType": "Agent",
            "GSI1_PK": "DMN001",
            "GSI1_SK": "AGTSCORE#50",
            "AgentNM": "매장 검색 에이전트3",
            "Score": "50",
            "Description": "동네 매장 검색 추천 서비스",
        },
        # 툴 데이터
        {
            "PK": "AGT001",
            "SK": "TL001",
            "EntityType": "Tool",
            "GSI1_PK": "DMN001",
            "GSI1_SK": "TL#FIND_LOC",
            "ToolNM": "FIND_LOC",
            "ToolSpec": '{"description": "특정 지역 검색", "parameters": {"location": "string", "radius": "string"}}',
            "Description": "특정지역주변의 매장을 검색하는 도구",
        },
        {
            "PK": "AGT001",
            "SK": "TL002",
            "EntityType": "Tool",
            "GSI1_PK": "DMN001",
            "GSI1_SK": "TL#USE_SEARCH_ENGINE_API",
            "ToolNM": "USE_SEARCH_ENGINE_API",
            "ToolSpec": '{"description": "검색엔진의 API 호출", "parameters": {"location": "string", "radius": "string", "cuisine": "string"}}',
            "Description": "위치값,반경등을 받아 검색엔진의 API를 순차적으로 검색",
        },
        {
            "PK": "AGT001",
            "SK": "TL003",
            "EntityType": "Tool",
            "GSI1_PK": "DMN001",
            "GSI1_SK": "TL#FORMAT_RESULTS",
            "ToolNM": "FORMAT_RESULTS",
            "ToolSpec": '{"description": "결과를 리스트형태로 전달", "parameters": {"results": "string"}}',
            "Description": "결과값을 포맷팅하여 리스트형태로 전달",
        },
        # AGT002 툴 데이터
        {
            "PK": "AGT002",
            "SK": "TL001",
            "EntityType": "Tool",
            "GSI1_PK": "DMN001",
            "GSI1_SK": "TL#FIND_LOC",
            "ToolNM": "FIND_LOC",
            "ToolSpec": '{"description": "특정 지역 검색", "parameters": {"location": "string", "radius": "string"}}',
            "Description": "특정지역주변의 매장을 검색하는 도구",
        },
        {
            "PK": "AGT002",
            "SK": "TL002",
            "EntityType": "Tool",
            "GSI1_PK": "DMN001",
            "GSI1_SK": "TL#USE_SEARCH_ENGINE_API",
            "ToolNM": "USE_SEARCH_ENGINE_API",
            "ToolSpec": '{"description": "검색엔진의 API 호출", "parameters": {"location": "string", "radius": "string", "cuisine": "string"}}',
            "Description": "위치값,반경등을 받아 검색엔진의 API를 순차적으로 검색",
        },
        {
            "PK": "AGT002",
            "SK": "TL003",
            "EntityType": "Tool",
            "GSI1_PK": "DMN001",
            "GSI1_SK": "TL#FORMAT_RESULTS",
            "ToolNM": "FORMAT_RESULTS",
            "ToolSpec": '{"description": "결과를 리스트형태로 전달", "parameters": {"results": "string"}}',
            "Description": "결과값을 포맷팅하여 리스트형태로 전달",
        },
        # AGT003 툴 데이터
        {
            "PK": "AGT003",
            "SK": "TL001",
            "EntityType": "Tool",
            "GSI1_PK": "DMN001",
            "GSI1_SK": "TL#FIND_LOC",
            "ToolNM": "FIND_LOC",
            "ToolSpec": '{"description": "특정 지역 검색", "parameters": {"location": "string", "radius": "string"}}',
            "Description": "특정지역주변의 매장을 검색하는 도구",
        },
        {
            "PK": "AGT003",
            "SK": "TL002",
            "EntityType": "Tool",
            "GSI1_PK": "DMN001",
            "GSI1_SK": "TL#USE_SEARCH_ENGINE_API",
            "ToolNM": "USE_SEARCH_ENGINE_API",
            "ToolSpec": '{"description": "검색엔진의 API 호출", "parameters": {"location": "string", "radius": "string", "cuisine": "string"}}',
            "Description": "위치값,반경등을 받아 검색엔진의 API를 순차적으로 검색",
        },
        {
            "PK": "AGT003",
            "SK": "TL003",
            "EntityType": "Tool",
            "GSI1_PK": "DMN001",
            "GSI1_SK": "TL#FORMAT_RESULTS",
            "ToolNM": "FORMAT_RESULTS",
            "ToolSpec": '{"description": "결과를 리스트형태로 전달", "parameters": {"results": "string"}}',
            "Description": "결과값을 포맷팅하여 리스트형태로 전달",
        },
        # 사용자 데이터
        {
            "PK": "USR001",
            "SK": "METADATA",
            "EntityType": "UserInfo",
            "UserNM": "돌칼",
            "UserProfile": '{"birth":"19741126","HP":"010-2222-3333","ADDR":"서울시 송파구 잠실동","age":"51"}',
            "LastLoginDT": "2025061414100223",
            "CreationDT": "20250601093210",
        },
        {
            "PK": "USR002",
            "SK": "METADATA",
            "EntityType": "UserInfo",
            "UserNM": "철수",
            "UserProfile": '{"birth":"19850315","HP":"010-3333-4444","ADDR":"서울시 강남구 역삼동","age":"39"}',
            "LastLoginDT": "20250614150000",
            "CreationDT": "20250601100000",
        },
        {
            "PK": "USR003",
            "SK": "METADATA",
            "EntityType": "UserInfo",
            "UserNM": "영희",
            "UserProfile": '{"birth":"19920720","HP":"010-5555-6666","ADDR":"서울시 마포구 홍대동","age":"32"}',
            "LastLoginDT": "20250614160000",
            "CreationDT": "20250601110000",
        },
        # 사용자 세션 데이터
        {
            "PK": "USR001",
            "SK": "SESS20250614001",
            "EntityType": "UserSession",
            "GSI1_PK": "USR001",
            "GSI1_SK": "잠실종합운동장 맛집 검색 세션",
            "UserSessionNM": "잠실종합운동장 맛집 검색 세션",
            "SessionSummary": "잠실종합 운동장 주변 맛집 검색 및 추천",
            "SessionStartDT": "20250614140530",
            "DtlFileLoc": "S3://usersess/2025...",
        },
        {
            "PK": "USR002",
            "SK": "SESS20250614002",
            "EntityType": "UserSession",
            "GSI1_PK": "USR002",
            "GSI1_SK": "강남역 맛집 검색 세션",
            "UserSessionNM": "강남역 맛집 검색 세션",
            "SessionSummary": "강남역 주변 맛집 검색 및 추천",
            "SessionStartDT": "20250614150530",
            "DtlFileLoc": "S3://usersess/2025...",
        },
        {
            "PK": "USR003",
            "SK": "SESS20250614003",
            "EntityType": "UserSession",
            "GSI1_PK": "USR003",
            "GSI1_SK": "홍대 카페 검색 세션",
            "UserSessionNM": "홍대 카페 검색 세션",
            "SessionSummary": "홍대 주변 카페 검색 및 추천",
            "SessionStartDT": "20250614160530",
            "DtlFileLoc": "S3://usersess/2025...",
        },
        # 사용자 세션 프로세스 데이터
        {
            "PK": "USR001#SESS20250614001",
            "SK": "PRC001",
            "EntityType": "UserSessionProcess",
            "UserPrompt": "잠실종합운동장 근처에 있는 N매장 근처의 최근에 생긴 카페를 찾아줘",
            "ProcNM": "위치확인",
            "ProcessDesc": "먼저 잠실종합운동장의 위치를 확인한다.",
            "ProcDT": "20250614140601",
        },
        {
            "PK": "USR001#SESS20250614001",
            "SK": "PRC002",
            "EntityType": "UserSessionProcess",
            "UserPrompt": "잠실종합운동장 근처에 있는 N매장 근처의 최근에 생긴 카페를 찾아줘",
            "ProcNM": "매장검색",
            "ProcessDesc": "잠실종합운동장 근처의 카페를 찾기 위해 검색엔진과 SNS의 API를 활용한다.",
            "ProcDT": "20250614140601",
        },
        {
            "PK": "USR001#SESS20250614001",
            "SK": "PRC003",
            "EntityType": "UserSessionProcess",
            "UserPrompt": "잠실종합운동장 근처에 있는 N매장 근처의 최근에 생긴 카페를 찾아줘",
            "ProcNM": "결과포맷팅",
            "ProcessDesc": "검색한결과를 포맷팅해서 최종결과를 응답한다",
            "ProcDT": "20250614140602",
        },
        # USR002 세션 프로세스
        {
            "PK": "USR002#SESS20250614002",
            "SK": "PRC001",
            "EntityType": "UserSessionProcess",
            "UserPrompt": "강남역 근처 맛집 찾아줘",
            "ProcNM": "위치확인",
            "ProcessDesc": "강남역의 위치를 확인한다.",
            "ProcDT": "20250614150601",
        },
        {
            "PK": "USR002#SESS20250614002",
            "SK": "PRC002",
            "EntityType": "UserSessionProcess",
            "UserPrompt": "강남역 근처 맛집 찾아줘",
            "ProcNM": "매장검색",
            "ProcessDesc": "강남역 근처의 맛집을 검색한다.",
            "ProcDT": "20250614150601",
        },
        {
            "PK": "USR002#SESS20250614002",
            "SK": "PRC003",
            "EntityType": "UserSessionProcess",
            "UserPrompt": "강남역 근처 맛집 찾아줘",
            "ProcNM": "결과포맷팅",
            "ProcessDesc": "검색한 맛집 결과를 포맷팅한다.",
            "ProcDT": "20250614150602",
        },
        # USR003 세션 프로세스
        {
            "PK": "USR003#SESS20250614003",
            "SK": "PRC001",
            "EntityType": "UserSessionProcess",
            "UserPrompt": "홍대 카페 추천해줘",
            "ProcNM": "위치확인",
            "ProcessDesc": "홍대의 위치를 확인한다.",
            "ProcDT": "20250614160601",
        },
        {
            "PK": "USR003#SESS20250614003",
            "SK": "PRC002",
            "EntityType": "UserSessionProcess",
            "UserPrompt": "홍대 카페 추천해줘",
            "ProcNM": "매장검색",
            "ProcessDesc": "홍대 근처의 카페를 검색한다.",
            "ProcDT": "20250614160601",
        },
        {
            "PK": "USR003#SESS20250614003",
            "SK": "PRC003",
            "EntityType": "UserSessionProcess",
            "UserPrompt": "홍대 카페 추천해줘",
            "ProcNM": "결과포맷팅",
            "ProcessDesc": "검색한 카페 결과를 포맷팅한다.",
            "ProcDT": "20250614160602",
        },
        # 사용자 세션 프로세스 툴 매핑이력
        {
            "PK": "USR001#SESS20250614001",
            "SK": "PRC001#AGT001#TL001",
            "EntityType": "UserSessPrcToolMappHist",
            "ToolNM": "FIND_LOC",
            "ToolValues": "잠실종합운동장 근처에 있는 N매장 근처의 최근에 생긴 카페를 찾아줘",
            "TransactDT": "20250614140605",
            "SuccYN": "Y",
            "ResultMsg": "사용자의 요청, 잠실종합운동장 위치",
        },
        {
            "PK": "USR001#SESS20250614001",
            "SK": "PRC002#AGT001#TL002",
            "EntityType": "UserSessPrcToolMappHist",
            "ToolNM": "USE_SEARCH_ENGINE_API",
            "ToolValues": "위 밸류값, 잠실종합운동장 위치, 네이버, 구글검색API",
            "TransactDT": "20250614140606",
            "SuccYN": "Y",
            "ResultMsg": "카페리스트",
        },
        {
            "PK": "USR001#SESS20250614001",
            "SK": "PRC003#AGT001#TL003",
            "EntityType": "UserSessPrcToolMappHist",
            "ToolNM": "FORMAT_RESULTS",
            "ToolValues": "맛집명단리스트, 포맷팅 템플릿 스크립트",
            "TransactDT": "20250614140607",
            "SuccYN": "Y",
            "ResultMsg": "포맷된 카페리스트",
        },
        # USR002 툴 매핑 이력
        {
            "PK": "USR002#SESS20250614002",
            "SK": "PRC001#AGT001#TL001",
            "EntityType": "UserSessPrcToolMappHist",
            "ToolNM": "FIND_LOC",
            "ToolValues": "강남역 근처 맛집 찾아줘",
            "TransactDT": "20250614150605",
            "SuccYN": "Y",
            "ResultMsg": "강남역 위치 확인",
        },
        {
            "PK": "USR002#SESS20250614002",
            "SK": "PRC002#AGT001#TL002",
            "EntityType": "UserSessPrcToolMappHist",
            "ToolNM": "USE_SEARCH_ENGINE_API",
            "ToolValues": "강남역, 맛집, 검색API",
            "TransactDT": "20250614150606",
            "SuccYN": "Y",
            "ResultMsg": "맛집리스트",
        },
        {
            "PK": "USR002#SESS20250614002",
            "SK": "PRC003#AGT001#TL003",
            "EntityType": "UserSessPrcToolMappHist",
            "ToolNM": "FORMAT_RESULTS",
            "ToolValues": "맛집리스트, 포맷팅",
            "TransactDT": "20250614150607",
            "SuccYN": "N",
            "ResultMsg": "포맷팅 실패",
        },
        # USR003 툴 매핑 이력
        {
            "PK": "USR003#SESS20250614003",
            "SK": "PRC001#AGT002#TL001",
            "EntityType": "UserSessPrcToolMappHist",
            "ToolNM": "FIND_LOC",
            "ToolValues": "홍대 카페 추천해줘",
            "TransactDT": "20250614160605",
            "SuccYN": "Y",
            "ResultMsg": "홍대 위치 확인",
        },
        {
            "PK": "USR003#SESS20250614003",
            "SK": "PRC002#AGT002#TL002",
            "EntityType": "UserSessPrcToolMappHist",
            "ToolNM": "USE_SEARCH_ENGINE_API",
            "ToolValues": "홍대, 카페, API호출",
            "TransactDT": "20250614160606",
            "SuccYN": "Y",
            "ResultMsg": "카페목록",
        },
        {
            "PK": "USR003#SESS20250614003",
            "SK": "PRC003#AGT002#TL003",
            "EntityType": "UserSessPrcToolMappHist",
            "ToolNM": "FORMAT_RESULTS",
            "ToolValues": "카페목록, 사용자친화적포맷",
            "TransactDT": "20250614160607",
            "SuccYN": "Y",
            "ResultMsg": "포맷된 카페목록",
        },
        # 사용자 프로세스 툴 매핑
        {
            "PK": "USR001",
            "SK": "UserPrcToolMapp#매장검색:카페,식당",
            "EntityType": "UserPrcToolMapp",
            "GSI1_PK": "UserPrcToolMapp",
            "GSI1_SK": "매장검색:카페,식당",
            "Proclist": '{"PRC001":"위치검색","PRC002":"매장검색","PRC003":"결과포맷팅"}',
            "AgentList": '{"AGT001":"매장검색에이전트"}',
            "Toollist": '{"PRC001#AGT001#TL001":"위치검색","PRC002#AGT001#TL002":"매장검색","PRC003#AGT001#TL003":"결과포맷팅"}',
        },
        {
            "PK": "USR003",
            "SK": "UserPrcToolMapp#매장검색:카페,식당",
            "EntityType": "UserPrcToolMapp",
            "GSI1_PK": "UserPrcToolMapp",
            "GSI1_SK": "매장검색:카페,식당",
            "Proclist": '{"PRC001":"위치검색","PRC002":"매장검색","PRC003":"결과포맷팅"}',
            "AgentList": '{"AGT003":"매장검색에이전트"}',
            "Toollist": '{"PRC001#AGT003#TL001":"위치검색","PRC002#AGT003#TL002":"매장검색","PRC003#AGT003#TL003":"결과포맷팅"}',
        },
    ]

    # 배치로 데이터 입력
    try:
        with table.batch_writer() as batch:
            for item in sample_items:
                batch.put_item(Item=item)

        print(f"총 {len(sample_items)}개의 샘플 데이터를 성공적으로 입력했습니다.")
        return True

    except Exception as e:
        print(f"데이터 입력 실패: {e}")
        return False


def verify_data():
    """데이터 입력 확인"""
    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.Table("AgentTable")

    print("\n=== 데이터 입력 확인 ===")

    # 도메인 조회
    print("\n1. 도메인 조회:")
    response = table.query(
        IndexName="GSI1",
        KeyConditionExpression="GSI1_PK = :pk",
        ExpressionAttributeValues={":pk": "Domain"},
    )
    for item in response["Items"]:
        print(f"  - {item['DomainNM']}: {item['Description']}")

    # 에이전트 조회 (스코어별)
    print("\n2. DMN001 도메인의 에이전트 조회 (스코어순):")
    response = table.query(
        IndexName="GSI1",
        KeyConditionExpression="GSI1_PK = :pk AND begins_with(GSI1_SK, :sk)",
        ExpressionAttributeValues={":pk": "DMN001", ":sk": "AGTSCORE"},
        ScanIndexForward=False,  # 내림차순 정렬
    )
    for item in response["Items"]:
        print(f"  - {item['AgentNM']} (스코어: {item['Score']}): {item['Description']}")

    # 각 에이전트별 툴 조회
    print("\n3. 각 에이전트별 툴 조회:")
    agents = ["AGT001", "AGT002", "AGT003"]
    for agent_id in agents:
        response = table.query(
            KeyConditionExpression="PK = :pk AND begins_with(SK, :sk)",
            ExpressionAttributeValues={":pk": agent_id, ":sk": "TL"},
        )
        if response["Items"]:
            print(f"  {agent_id} 에이전트의 툴:")
            for item in response["Items"]:
                print(f"    - {item['ToolNM']}: {item['Description']}")
        else:
            print(f"  {agent_id} 에이전트: 툴 없음")

    # 각 사용자별 세션 조회
    print("\n4. 각 사용자별 세션 조회:")
    users = ["USR001", "USR002", "USR003"]
    for user_id in users:
        response = table.query(
            KeyConditionExpression="PK = :pk AND begins_with(SK, :sk)",
            ExpressionAttributeValues={":pk": user_id, ":sk": "SESS"},
        )
        if response["Items"]:
            print(f"  {user_id} 사용자의 세션:")
            for item in response["Items"]:
                print(f"    - {item['UserSessionNM']}: {item['SessionSummary']}")
        else:
            print(f"  {user_id} 사용자: 세션 없음")

    # 각 세션별 프로세스 조회
    print("\n5. 각 세션별 프로세스 조회:")
    sessions = [
        "USR001#SESS20250614001",
        "USR002#SESS20250614002",
        "USR003#SESS20250614003",
    ]
    for session_id in sessions:
        response = table.query(
            KeyConditionExpression="PK = :pk AND begins_with(SK, :sk)",
            ExpressionAttributeValues={":pk": session_id, ":sk": "PRC"},
        )
        processes = [
            item
            for item in response["Items"]
            if item["EntityType"] == "UserSessionProcess"
        ]
        if processes:
            print(f"  {session_id} 세션의 프로세스:")
            for item in processes:
                print(f"    - {item['SK']}: {item['ProcessDesc']}")
        else:
            print(f"  {session_id} 세션: 프로세스 없음")

    # 각 세션별 툴 매핑 이력 조회
    print("\n6. 각 세션별 툴 매핑 이력 조회:")
    for session_id in sessions:
        response = table.query(
            KeyConditionExpression="PK = :pk AND begins_with(SK, :sk)",
            ExpressionAttributeValues={":pk": session_id, ":sk": "PRC"},
        )
        tool_mappings = [
            item
            for item in response["Items"]
            if item["EntityType"] == "UserSessPrcToolMappHist"
        ]
        if tool_mappings:
            print(f"  {session_id} 세션의 툴 매핑 이력:")
            for item in tool_mappings:
                status = "✓" if item["SuccYN"] == "Y" else "✗"
                print(
                    f"    - {item['SK']}: {item['ToolNM']} {status} ({item['ResultMsg']})"
                )
        else:
            print(f"  {session_id} 세션: 툴 매핑 이력 없음")


if __name__ == "__main__":
    print("DynamoDB 에이전트 테이블 생성 및 데이터 입력을 시작합니다...")

    # 테이블 생성
    if create_dynamodb_table():
        print("테이블 생성 완료!")

        # 샘플 데이터 입력
        if insert_sample_data():
            print("샘플 데이터 입력 완료!")

            # 데이터 확인
            verify_data()
        else:
            print("샘플 데이터 입력 실패!")
    else:
        print("테이블 생성 실패!")
