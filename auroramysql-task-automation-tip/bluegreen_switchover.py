import boto3
import sys

# AWS RDS 클라이언트 생성
if len(sys.argv) > 1:
    region_name = sys.argv[1]
else:
    region_name = "us-west-2"

# AWS RDS 클라이언트 생성
rds_client = boto3.client("rds", region_name=region_name)

# describe-blue-green-deployments API 호출
response = rds_client.describe_blue_green_deployments()

# BlueGreenDeploymentIdentifier 및 cluster이름 추출
deployment_cluster_map = {
    deployment["BlueGreenDeploymentIdentifier"]: deployment["BlueGreenDeploymentName"]
    for deployment in response["BlueGreenDeployments"]
}

if not deployment_cluster_map:
    print("현재 리전에 Blue/Green 배포가 없습니다.")
else:
    # BlueGreenDeploymentIdentifier 값 출력
    for identifier, cluster_name in deployment_cluster_map.items():
        # print(f"BlueGreenDeploymentIdentifier: {identifier}, ClusterName: {cluster_name}")
        try:
            status = rds_client.describe_blue_green_deployments(
                BlueGreenDeploymentIdentifier=identifier
            )["BlueGreenDeployments"][0]["Status"]

            if status == "AVAILABLE":
                response = rds_client.switchover_blue_green_deployment(
                    BlueGreenDeploymentIdentifier=identifier
                )
                print(f"블루그린 [{identifier}] {cluster_name} 스위치오버 완료")
            else:
                print(
                    f"블루그린 [{identifier}] {cluster_name} 이미 스위치오버가 끝났거나 시작되어 처리중입니다."
                )

        except Exception as e:
            print(f"Error: {e}")
