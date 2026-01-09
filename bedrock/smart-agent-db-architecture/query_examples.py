#!/usr/bin/env python3
import boto3
from boto3.dynamodb.conditions import Key
import json


def setup_dynamodb():
    """DynamoDB 리소스 설정"""
    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.Table("AgentTable")
    return table


def query_domains():
    """도메인 조회 예시"""
    table = setup_dynamodb()

    print("=== 1. 도메인 조회 ===")
    response = table.query(
        IndexName="GSI1", KeyConditionExpression=Key("GSI1_PK").eq("Domain")
    )

    print(f"조회된 도메인 수: {response['Count']}")
    for item in response["Items"]:
        print(f"- 도메인ID: {item['PK']}")
        print(f"  이름: {item['DomainNM']}")
        print(f"  설명: {item['Description']}")
        print()


def query_agents_by_score(domain_id="DMN001", limit=5):
    """스코어가 높은 에이전트 조회"""
    table = setup_dynamodb()

    print(f"=== 2. {domain_id} 도메인의 상위 에이전트 조회 (스코어순) ===")
    response = table.query(
        IndexName="GSI1",
        KeyConditionExpression=Key("GSI1_PK").eq(domain_id)
        & Key("GSI1_SK").begins_with("AGTSCORE"),
        ScanIndexForward=False,  # 내림차순 정렬
        Limit=limit,
    )

    print(f"조회된 에이전트 수: {response['Count']}")
    for item in response["Items"]:
        print(f"- 에이전트: {item.get('AgentNM', 'N/A')}")
        print(f"  스코어: {item.get('Score', 'N/A')}")
        print(f"  설명: {item.get('Description', 'N/A')}")
        print()


def query_tools_by_domain(domain_id="DMN001"):
    """도메인의 툴 조회"""
    table = setup_dynamodb()

    print(f"=== 3. {domain_id} 도메인의 툴 조회 ===")
    response = table.query(
        IndexName="GSI1",
        KeyConditionExpression=Key("GSI1_PK").eq(domain_id)
        & Key("GSI1_SK").begins_with("TL"),
    )

    print(f"조회된 툴 수: {response['Count']}")
    for item in response["Items"]:
        print(f"- 툴명: {item.get('ToolNM', 'N/A')}")
        print(f"  설명: {item.get('Description', 'N/A')}")
        print(f"  스펙: {item.get('ToolSpec', 'N/A')}")
        print()


def query_agent_tools():
    """각 에이전트별 툴 조회"""
    table = setup_dynamodb()

    print("=== 4. 각 에이전트별 툴 조회 ===")
    agents = ["AGT001", "AGT002", "AGT003"]

    for agent_id in agents:
        response = table.query(
            KeyConditionExpression=Key("PK").eq(agent_id) & Key("SK").begins_with("TL")
        )

        if response["Items"]:
            print(f"\n{agent_id} 에이전트의 툴 ({response['Count']}개):")
            for item in response["Items"]:
                print(
                    f"  - {item.get('ToolNM', 'N/A')}: {item.get('Description', 'N/A')}"
                )
        else:
            print(f"\n{agent_id} 에이전트: 툴 없음")
    print()


def query_user_sessions(limit=10):
    """각 사용자별 세션 조회"""
    table = setup_dynamodb()

    print("=== 5. 각 사용자별 세션 조회 ===")
    users = ["USR001", "USR002", "USR003"]

    for user_id in users:
        response = table.query(
            KeyConditionExpression=Key("PK").eq(user_id)
            & Key("SK").begins_with("SESS"),
            ScanIndexForward=False,  # 최신순 정렬
            Limit=limit,
        )

        if response["Items"]:
            print(f"\n{user_id} 사용자의 세션 ({response['Count']}개):")
            for item in response["Items"]:
                print(
                    f"  - {item.get('UserSessionNM', 'N/A')}: {item.get('SessionSummary', 'N/A')}"
                )
        else:
            print(f"\n{user_id} 사용자: 세션 없음")
    print()


def query_session_processes():
    """각 세션별 프로세스 조회"""
    table = setup_dynamodb()

    print("=== 6. 각 세션별 프로세스 조회 ===")
    sessions = [
        ("USR001", "SESS20250614001"),
        ("USR002", "SESS20250614002"),
        ("USR003", "SESS20250614003"),
    ]

    for user_id, session_id in sessions:
        pk = f"{user_id}#{session_id}"
        response = table.query(
            KeyConditionExpression=Key("PK").eq(pk) & Key("SK").begins_with("PRC")
        )

        processes = [
            item
            for item in response["Items"]
            if item.get("EntityType") == "UserSessionProcess"
        ]

        if processes:
            print(f"\n{session_id} 세션의 프로세스 ({len(processes)}개):")
            for item in processes:
                print(
                    f"  - {item.get('ProcNM', 'N/A')}: {item.get('ProcessDesc', 'N/A')}"
                )
        else:
            print(f"\n{session_id} 세션: 프로세스 없음")
    print()


def query_user_tool_mapping():
    """각 사용자별 툴 매핑 정보 조회"""
    table = setup_dynamodb()

    print("=== 7. 각 사용자별 툴 매핑 정보 조회 ===")
    users = ["USR001", "USR002", "USR003"]

    for user_id in users:
        response = table.query(
            KeyConditionExpression=Key("PK").eq(user_id)
            & Key("SK").begins_with("UserPrcToolMapp")
        )

        if response["Items"]:
            print(f"\n{user_id} 사용자의 툴 매핑 ({response['Count']}개):")
            for item in response["Items"]:
                print(
                    f"  - 매핑타입: {item['SK'].split('#')[1] if '#' in item['SK'] else 'N/A'}"
                )
                print(f"    프로세스: {item.get('Proclist', 'N/A')}")
        else:
            print(f"\n{user_id} 사용자: 툴 매핑 없음")
    print()


def query_session_tool_mappings():
    """각 세션별 툴 매핑 이력 조회"""
    table = setup_dynamodb()

    print("=== 8. 각 세션별 툴 매핑 이력 조회 ===")
    sessions = [
        ("USR001", "SESS20250614001"),
        ("USR002", "SESS20250614002"),
        ("USR003", "SESS20250614003"),
    ]

    for user_id, session_id in sessions:
        pk = f"{user_id}#{session_id}"
        response = table.query(
            KeyConditionExpression=Key("PK").eq(pk) & Key("SK").begins_with("PRC")
        )

        tool_mappings = [
            item
            for item in response["Items"]
            if item.get("EntityType") == "UserSessPrcToolMappHist"
        ]

        if tool_mappings:
            print(f"\n{session_id} 세션의 툴 매핑 이력 ({len(tool_mappings)}개):")
            for item in tool_mappings:
                status = "✓" if item.get("SuccYN") == "Y" else "✗"
                print(
                    f"  - {item.get('ToolNM', 'N/A')} {status}: {item.get('ResultMsg', 'N/A')}"
                )
        else:
            print(f"\n{session_id} 세션: 툴 매핑 이력 없음")
    print()


def query_all_user_tool_mappings():
    """전체 사용자의 툴 매핑 정보 조회 (GSI 사용)"""
    table = setup_dynamodb()

    print("=== 9. 전체 사용자의 툴 매핑 정보 조회 (GSI) ===")
    response = table.query(
        IndexName="GSI1", KeyConditionExpression=Key("GSI1_PK").eq("UserPrcToolMapp")
    )

    print(f"조회된 매핑 수: {response['Count']}")
    for item in response["Items"]:
        print(f"- 사용자: {item['PK']}")
        print(f"  매핑 타입: {item.get('GSI1_SK', 'N/A')}")
        print(f"  프로세스 리스트: {item.get('Proclist', 'N/A')}")
        print()


def comprehensive_query_example():
    """종합적인 쿼리 예시"""
    print("=== 10. 종합 쿼리 예시: 사용자 요청 처리 전체 플로우 ===")

    # 1. 사용자 요청에 적합한 도메인 찾기
    print("\n[단계 1] 사용자 요청에 적합한 도메인 찾기")
    query_domains()

    # 2. 해당 도메인의 최고 스코어 에이전트 찾기
    print("\n[단계 2] 최고 스코어 에이전트 찾기")
    query_agents_by_score(limit=1)

    # 3. 선택된 에이전트의 툴 확인
    print("\n[단계 3] 선택된 에이전트의 툴 확인")
    query_agent_tools()

    # 4. 사용자의 기존 매핑 정보 확인
    print("\n[단계 4] 사용자의 기존 매핑 정보 확인")
    query_user_tool_mapping()


if __name__ == "__main__":
    print("DynamoDB 에이전트 테이블 쿼리 예시를 실행합니다...\n")

    try:
        # 개별 쿼리 실행
        query_domains()
        query_agents_by_score()
        query_tools_by_domain()
        query_agent_tools()
        query_user_sessions()
        query_session_processes()
        query_user_tool_mapping()
        query_session_tool_mappings()
        query_all_user_tool_mappings()

        # 종합 예시
        comprehensive_query_example()

    except Exception as e:
        print(f"쿼리 실행 중 오류 발생: {e}")
        print("테이블이 존재하는지, 데이터가 입력되었는지 확인해주세요.")
