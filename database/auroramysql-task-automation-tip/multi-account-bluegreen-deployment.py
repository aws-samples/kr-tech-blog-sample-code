import boto3
import sys
import csv
import json
import re


def get_account_credentials(secret_name, region):
    # print("AWS Secrets Manager에서 계정 자격 증명을 가져옵니다.")
    try:
        session = boto3.session.Session()
        client = session.client("secretsmanager", region_name=region)
        response = client.get_secret_value(SecretId=secret_name)
        return json.loads(response["SecretString"])
    except Exception as e:
        print(f"시크릿 조회 중 오류 발생: {e}")
        return None


def create_blue_green_deployment(
    session,
    region_name,
    target_version="8.0.mysql_aurora.3.05.2",
    name_filter="test",
    tag_key="need_upgrade",
    tag_value="y",
):
    try:
        rds_client = session.client("rds", region_name=region_name)
        account_id = session.client("sts").get_caller_identity()["Account"]

        # 클러스터 목록 조회
        paginator = rds_client.get_paginator("describe_db_clusters")
        clusters_to_upgrade = []

        for page in paginator.paginate():
            for cluster in page["DBClusters"]:
                cluster_identifier = cluster["DBClusterIdentifier"]
                engine_version = cluster["EngineVersion"]

                print("cluster_identifier: ", cluster_identifier)

                # 버전, 이름, 태그 기반 필터링
                version_check = float(engine_version.split(".")[0]) < float(
                    target_version.split(".")[0]
                )
                name_pattern = rf"^{name_filter}\d+$"

                # 정규식을 사용한 이름 패턴 체크
                name_check = (
                    re.match(name_pattern, cluster_identifier.lower()) is not None
                )

                # 태그 확인
                tags_response = rds_client.list_tags_for_resource(
                    ResourceName=f"arn:aws:rds:{region_name}:{account_id}:cluster:{cluster_identifier}"
                )
                tag_check = any(
                    tag["Key"] == tag_key and tag["Value"] == tag_value
                    for tag in tags_response["TagList"]
                )

                if version_check and (name_check or tag_check):
                    clusters_to_upgrade.append(cluster_identifier)

        # 필터링된 클러스터에 대해 블루그린 배포 생성
        for cluster_name in clusters_to_upgrade:
            cluster_arn = (
                f"arn:aws:rds:{region_name}:{account_id}:cluster:{cluster_name}"
            )
            print(f"블루그린 배포를 생성합니다: {cluster_name}")

            response = rds_client.create_blue_green_deployment(
                BlueGreenDeploymentName=f"bg-{cluster_name}",
                Source=cluster_arn,
                TargetEngineVersion=target_version,
                TargetDBClusterParameterGroupName="mysql80",
            )

            print(f"블루그린 배포 생성 완료: {cluster_name}")
            print(
                f"배포 ID: {response['BlueGreenDeployment']['BlueGreenDeploymentIdentifier']}"
            )

        return len(clusters_to_upgrade)

    except Exception as e:
        print(f"블루그린 배포 생성 중 오류 발생: {e}")
        return 0


def read_accounts_from_csv(file_path):
    """CSV 파일에서 계정 정보와 시크릿 이름을 읽어옵니다."""
    accounts = []
    with open(file_path, "r") as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            accounts.append(
                {
                    "account_id": row["account_id"],
                    "secret_name": row["secret_name"],
                    "region": row["region"],
                }
            )
    return accounts


def main():
    if len(sys.argv) < 2:
        print("Usage: python script.py <path_to_csv_file>")
        sys.exit(1)

    csv_file_path = sys.argv[1]
    accounts = read_accounts_from_csv(csv_file_path)

    for account in accounts:
        print(f"\nProcessing account: {account['account_id']}")

        credentials = get_account_credentials(account["secret_name"], account["region"])
        if not credentials:
            continue

        session = boto3.Session(
            aws_access_key_id=credentials["access_key"],
            aws_secret_access_key=credentials["secret_key"],
            region_name=account["region"],
        )

        # 블루그린 배포 생성
        upgraded_clusters = create_blue_green_deployment(
            session,
            account["region"],
            target_version="8.0.mysql_aurora.3.05.2",  # 업그레이드할 타겟버전
            name_filter="test",  # 클러스터 이름 필터
            tag_key="need_upgrade",  # 태그 키
            tag_value="y",  # 태그 값
        )
        print(
            f"계정 {account['account_id']}에서 {upgraded_clusters}개의 클러스터에 대해 블루그린 배포를 생성했습니다."
        )


if __name__ == "__main__":
    main()
