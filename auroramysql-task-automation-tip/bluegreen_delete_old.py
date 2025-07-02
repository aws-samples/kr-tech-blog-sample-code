import boto3
import sys
import time
import argparse


def parse_arguments():
    parser = argparse.ArgumentParser(
        description="Aurora 블루그린 배포 및 이전 클러스터 정리 도구"
    )
    parser.add_argument(
        "--region", default="us-west-2", help="AWS 리전 (기본값: us-west-2)"
    )
    parser.add_argument("--cluster_name", help="삭제할 특정 클러스터 이름 (선택사항)")
    return parser.parse_args()


def delete_blue_green_deployments(rds_client):
    """현재 존재하는 블루그린 배포를 삭제합니다."""
    try:
        response = rds_client.describe_blue_green_deployments()
        deployments = response["BlueGreenDeployments"]

        if not deployments:
            print("삭제할 블루그린 배포가 없습니다.")
            return

        for deployment in deployments:
            identifier = deployment["BlueGreenDeploymentIdentifier"]
            cluster_name = deployment["BlueGreenDeploymentName"]

            try:
                rds_client.delete_blue_green_deployment(
                    BlueGreenDeploymentIdentifier=identifier
                )
                print(f"블루그린 배포 삭제 완료: [{identifier}] {cluster_name}")

                # 배포 삭제 완료 대기
                while True:
                    try:
                        rds_client.describe_blue_green_deployments(
                            BlueGreenDeploymentIdentifier=identifier
                        )
                        time.sleep(30)
                    except:
                        break

            except Exception as e:
                print(f"블루그린 배포 [{identifier}] 삭제 중 에러 발생: {e}")

    except Exception as e:
        print(f"Error: {e}")


def get_old_clusters(rds_client, cluster_name=None):
    """이전 클러스터(_old suffix)를 찾습니다."""
    try:
        response = rds_client.describe_db_clusters()
        old_clusters = []

        for cluster in response["DBClusters"]:
            cluster_id = cluster["DBClusterIdentifier"]
            print("cluster_id", cluster_id)
            if cluster_id.endswith("-old1"):
                if cluster_name:
                    print("if cluster_name")
                    if cluster_name in cluster_id:
                        old_clusters.append(cluster_id)
                else:
                    print("else cluster_name")
                    old_clusters.append(cluster_id)

        return old_clusters
    except Exception as e:
        print(f"Error: {e}")
        return []


def delete_cluster(rds_client, cluster_identifier):
    """클러스터와 관련 인스턴스들을 삭제합니다."""
    try:
        # 클러스터에 속한 DB 인스턴스들을 먼저 삭제
        response = rds_client.describe_db_clusters(
            DBClusterIdentifier=cluster_identifier
        )

        # DB 인스턴스 삭제
        for instance in response["DBClusters"][0]["DBClusterMembers"]:
            instance_id = instance["DBInstanceIdentifier"]
            print(f"DB 인스턴스 삭제 중: {instance_id}")
            rds_client.delete_db_instance(
                DBInstanceIdentifier=instance_id, SkipFinalSnapshot=True
            )

        # 인스턴스 삭제 완료 대기
        for instance in response["DBClusters"][0]["DBClusterMembers"]:
            instance_id = instance["DBInstanceIdentifier"]
            while True:
                try:
                    rds_client.describe_db_instances(DBInstanceIdentifier=instance_id)
                    time.sleep(30)
                except:
                    break

        # 클러스터 삭제
        print(f"클러스터 삭제 중: {cluster_identifier}")
        rds_client.delete_db_cluster(
            DBClusterIdentifier=cluster_identifier, SkipFinalSnapshot=True
        )
        return True

    except Exception as e:
        print(f"Error: {e}")
        return False


def main():
    args = parse_arguments()

    # AWS RDS 클라이언트 생성
    rds_client = boto3.client("rds", region_name=args.region)

    # 1단계: 블루그린 배포 삭제
    print("=== 블루그린 배포 삭제 시작 ===")
    delete_blue_green_deployments(rds_client)

    # 2단계: 이전 클러스터 삭제
    print("\n=== 이전 클러스터 삭제 시작 ===")
    old_clusters = get_old_clusters(rds_client, args.cluster_name)

    if not old_clusters:
        print("삭제할 이전 클러스터가 없습니다.")
        return

    print(f"삭제할 클러스터: {old_clusters}")
    for cluster in old_clusters:
        if delete_cluster(rds_client, cluster):
            print(f"클러스터 {cluster} 삭제 완료")
        else:
            print(f"클러스터 {cluster} 삭제 실패")


if __name__ == "__main__":
    main()
