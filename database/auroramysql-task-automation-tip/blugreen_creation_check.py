import boto3
from datetime import datetime
from rich.console import Console
from rich.table import Table
from rich.prompt import Prompt
from collections import defaultdict
import argparse

console = Console()


def get_current_region():
    session = boto3.session.Session()
    return session.region_name or "us-east-1"


def parse_arguments():
    parser = argparse.ArgumentParser(
        description="Aurora MySQL 블루/그린 배포 상태 조회"
    )
    parser.add_argument(
        "--region", default=get_current_region(), help="AWS 리전 (기본값: 현재 리전)"
    )
    parser.add_argument(
        "--deployment-name", help="조회할 블루/그린 배포 이름 (기본값: 전체 조회)"
    )
    return parser.parse_args()


def get_deployment_status(rds_client, deployment_name=None):
    try:
        if deployment_name:
            response = rds_client.describe_blue_green_deployments(
                Filters=[
                    {"Name": "blue-green-deployment-name", "Values": [deployment_name]}
                ]
            )
        else:
            response = rds_client.describe_blue_green_deployments()

        deployments = response.get("BlueGreenDeployments", [])
        if deployment_name and not deployments:
            console.print(
                f"[yellow]지정한 배포명 '{deployment_name}'에 해당하는 배포를 찾을 수 없습니다.[/yellow]"
            )
        return deployments
    except Exception as e:
        console.print(f"[red]블루/그린 배포 조회 실패: {str(e)}[/red]")
        return []


def get_last_upgrade_event(deployment, region):
    # RDS 클라이언트 생성

    db_identifier = get_green_cluster_identifier(deployment, region)
    rds = boto3.client("rds", region)

    try:
        # RDS 이벤트 조회
        response = rds.describe_events(
            SourceIdentifier=db_identifier, SourceType="db-cluster", Duration=5000
        )

        # 업그레이드 관련 이벤트 필터링
        upgrade_events = [
            event
            for event in response["Events"]
            if "upgrade" in event["Message"].lower()
        ]

        # 업그레이드 이벤트가 있는 경우
        if upgrade_events:
            # 가장 최근 이벤트 선택 (Events는 시간순으로 정렬되어 있음)
            last_event = upgrade_events[-1]
            # 이벤트 시간을 한국 시간으로 변환
            event_time = last_event["Date"].astimezone()
            return event_time

        return "No upgrade events found in the last 24 hours"

    except Exception as e:
        return f"Error occurred: {str(e)}"


def get_green_cluster_identifier(deployment, region):
    rds = boto3.client("rds", region)

    try:
        response = rds.describe_blue_green_deployments(
            BlueGreenDeploymentIdentifier=deployment["BlueGreenDeploymentIdentifier"]
        )

        # Green 인스턴스 식별자 추출
        target_member = response["BlueGreenDeployments"][0]["SwitchoverDetails"][0][
            "TargetMember"
        ]

        # ARN에서 Cluster 식별자만 추출 (마지막 : 이후 문자열)
        green_cluster_id = target_member.split(":")[-1]

        return green_cluster_id

    except Exception as e:
        return f"Error occurred: {str(e)}"


def calculate_deployment_duration(deployment, region):
    create_time = deployment.get("CreateTime")
    if not create_time:
        return None
    complete_time = get_last_upgrade_event(deployment, region)
    current_time = datetime.now(create_time.tzinfo)

    if deployment["Status"] == "AVAILABLE":
        for task in deployment.get("Tasks", []):
            if task["Status"] == "COMPLETED":
                # print('deployment name : ',deployment['BlueGreenDeploymentName'],'CompletionTime  : ',complete_time)
                duration = complete_time - create_time
                return duration.total_seconds() / 60
    else:
        duration = current_time - create_time
        return duration.total_seconds() / 60
    return None


def analyze_deployments(deployments):
    status_count = defaultdict(int)
    completed_deployments = []
    in_progress_deployments = []

    for deployment in deployments:
        status = deployment["Status"]
        status_count[status] += 1

        if status == "AVAILABLE":
            completed_deployments.append(deployment)
        elif status in ["PROVISIONING", "IN_PROGRESS"]:
            in_progress_deployments.append(deployment)

    return status_count, completed_deployments, in_progress_deployments


def convert_duration_to_minutes_and_seconds(duration):
    # 전체 분 계산
    total_minutes = int(duration)
    # 초 계산 (소수점 부분을 60초로 변환)
    seconds = int((duration - total_minutes) * 60)

    return total_minutes, seconds


def display_deployment_status(region, deployment_name=None):
    rds_client = boto3.client("rds", region_name=region)
    deployments = get_deployment_status(rds_client, deployment_name)

    if not deployments:
        return

    # 상태별 집계 분석
    status_count, completed_deployments, in_progress_deployments = analyze_deployments(
        deployments
    )
    console.print("\n[bold]배포 상태 :[/bold]", "region: ", region)
    for status, count in status_count.items():
        console.print(f"{status}: {count}개")

    # 완료된 배포 시간
    for deployment in completed_deployments:
        bg_name = deployment["BlueGreenDeploymentName"]
        bg_status = deployment["Status"]
        bg_starttime = deployment["CreateTime"].strftime("%Y-%m-%d %H:%M:%S")
        bg_endtime = get_last_upgrade_event(deployment, region).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        bg_duration = calculate_deployment_duration(deployment, region)
        if bg_duration:
            minutes, seconds = convert_duration_to_minutes_and_seconds(bg_duration)
            console.print(
                f"배포명 : {bg_name}, "
                f"상태 : {bg_status}, "
                f"생성시간 : {bg_starttime}, "
                f"종료시간 : {bg_endtime}, "
                f"소요시간: {minutes}분 {seconds}초 "
            )
    # 미 완료된 배포 리스트
    for deployment in in_progress_deployments:
        bg_name = deployment["BlueGreenDeploymentName"]
        bg_status = deployment["Status"]
        bg_starttime = deployment["CreateTime"].strftime("%Y-%m-%d %H:%M:%S")
        bg_duration = calculate_deployment_duration(deployment, region)
        if bg_duration:
            minutes, seconds = convert_duration_to_minutes_and_seconds(bg_duration)
            console.print(
                f"배포명 : {bg_name}, "
                f"상태 : {bg_status}, "
                f"생성시간 : {bg_starttime}, "
                f"종료시간 : N/A , "
                f"소요시간: {minutes}분 {seconds}초 "
            )


def main():
    try:
        args = parse_arguments()
        console.print(
            f"[bold blue]Aurora MySQL 블루/그린 배포 상태 조회 (리전: {args.region})[/bold blue]"
        )
        if args.deployment_name:
            console.print(f"[bold blue]배포명 필터: {args.deployment_name}[/bold blue]")
        display_deployment_status(args.region, args.deployment_name)
    except KeyboardInterrupt:
        console.print("\n[yellow]프로그램이 사용자에 의해 중단되었습니다.[/yellow]")
    except Exception as e:
        console.print(f"[bold red]오류 발생: {str(e)}[/bold red]")


if __name__ == "__main__":
    main()
