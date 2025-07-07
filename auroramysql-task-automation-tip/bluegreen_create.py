import boto3
import time
from rich import print
from rich.prompt import Prompt, Confirm
from rich.console import Console
from rich.panel import Panel

console = Console()


def get_current_account_info():
    sts_client = boto3.client("sts")
    try:
        account_info = sts_client.get_caller_identity()
        return {"account_id": account_info["Account"], "arn": account_info["Arn"]}
    except Exception as e:
        console.print(f"[red]AWS 계정 정보 조회 실패: {str(e)}[/red]")
        raise


def get_user_inputs():
    console.print(Panel.fit("Aurora MySQL Bluegreen 배포 설정", style="bold blue"))

    # 현재 계정 정보 가져오기
    account_info = get_current_account_info()
    console.print(f"[green]현재 AWS 계정: {account_info['account_id']}[/green]")

    inputs = {
        "account_id": account_info["account_id"],  # 자동으로 설정
        "region": Prompt.ask(
            "AWS 리전을 선택하세요",
            choices=["ap-northeast-2", "us-east-1", "eu-central-1", "us-west-2"],
            default="us-west-2",
        ),
        "cluster_identifier": Prompt.ask("DB Cluster 식별자를 입력하세요"),
        "target_engine_version": Prompt.ask(
            "대상 엔진 버전을 선택하세요",
            choices=[
                "8.0.mysql_aurora.3.05.2",
                "8.0.mysql_aurora.3.06.1",
                "8.0.mysql_aurora.3.07.1",
                "8.0.mysql_aurora.3.08.0",
            ],
            default="8.0.mysql_aurora.3.05.2",
        ),
        "cluster_parameter_group": Prompt.ask(
            "파라미터 그룹 이름을 입력하세요", default="mysql80"
        ),
    }

    # 입력 확인
    console.print("\n[bold]입력하신 정보를 확인해주세요:[/bold]")
    for key, value in inputs.items():
        console.print(f"{key}: {value}")

    if not Confirm.ask("\n입력하신 정보로 배포를 시작할까요?"):
        console.print("[red]배포가 취소되었습니다.[/red]")
        exit()

    return inputs


def construct_cluster_arn(inputs):
    return f"arn:aws:rds:{inputs['region']}:{inputs['account_id']}:cluster:{inputs['cluster_identifier']}"


def create_blue_green_deployment(source_cluster_arn, inputs):
    rds_client = boto3.client("rds", region_name=inputs["region"])

    with console.status("[bold green]Bluegreen 배포 생성 중...") as status:
        console.print(f"소스 DB Cluster명: {inputs['cluster_identifier']}")

        response = rds_client.create_blue_green_deployment(
            BlueGreenDeploymentName="bg-" + inputs["cluster_identifier"],
            Source=source_cluster_arn,
            TargetEngineVersion=inputs["target_engine_version"],
            TargetDBClusterParameterGroupName=inputs["cluster_parameter_group"],
        )

        deployment_id = response["BlueGreenDeployment"]["BlueGreenDeploymentIdentifier"]
        deployment_name = response["BlueGreenDeployment"]["BlueGreenDeploymentName"]

        status.update("[bold green]배포 상태 확인 중...")
        current_status = rds_client.describe_blue_green_deployments(
            BlueGreenDeploymentIdentifier=deployment_id
        )["BlueGreenDeployments"][0]["Status"]

        console.print(f"현재 상태: {current_status}")

    return deployment_name


def main():
    try:
        inputs = get_user_inputs()
        source_cluster_arn = construct_cluster_arn(inputs)
        deployment_name = create_blue_green_deployment(source_cluster_arn, inputs)
        console.print(
            f"[bold green]배포가 성공적으로 생성되었습니다. : {deployment_name}[/bold green]"
        )
    except KeyboardInterrupt:
        console.print("\n[yellow]프로그램이 사용자에 의해 중단되었습니다.[/yellow]")
    except Exception as e:
        console.print(
            f"[bold red]프로그램 실행 중 오류가 발생했습니다: {str(e)}[/bold red]"
        )


if __name__ == "__main__":
    main()
