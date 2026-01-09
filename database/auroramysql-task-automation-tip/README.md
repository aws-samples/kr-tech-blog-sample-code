# AWS Aurora MySQL Blue/Green Deployment Automation Tool

이 프로젝트의 내용은 AWS 환경 전반에 걸쳐 Amazon Aurora MySQL 클러스터의 블루/그린 배포를 관리하기 위한 종합적인 자동화 툴킷을 제공합니다. 이를 통해서 Aurora mysql의 블루그린 배포 프로세스를 단순화하고, 다운타임을 줄이며, 안전한 데이터베이스 버전 업그레이드를 원활하게 진행하는데 도움이 될 것입니다. 
아래에서 소개하는 각각의 파이썬 스크립트는 블루그린 배포 생성, 배포과정의 상태 모니터링, 블루와 그린의 전환과정, 배포이후 old 클러스터(블루클러스트)의 정리 작업을 포함한 전체 블루/그린 배포 수명 주기의 자동화된 관리를 제공합니다. 단일 및 다중 계정 배포를 모두 지원하여 소수의 인원으로 많은 수의 데이터베이스를 업그레이드 해야 하는 기업 환경에 가장 적합합니다. 

## Repository Structure
```
.
├── bluegreen_create.py              # 새로운 Blue/Green 배포를 생성하는데 사용하는 스크립트입니다. 
├── blugreen_creation_check.py       # Blue/Green 배포 생성과정에서 진행상태를 체크하는데 사용하는 스크립트입니다. 
├── bluegreen_switchover_precheck.py # Blue/Green을 전환하기전, 사전 체크하는 스크립트입니다. 
├── bluegreen_switchover.py          # Blue/Green을 전환할때 사용하는 스크립트 입니다. 
├── bluegreen_delete_old.py          # Blue/Green 배포 이후 구 클러스터를 삭제할때 사용하는 스크립트입니다. 
└── multi-account-bluegreen-deployment.py    # 여러개의 어카운트, 리전에 있는 Aurora mysql 클러스터의 Blue/Green 배포를 생성합니다. 
```

## Usage Instructions
### 사전준비사항 
- Python 3.6 또는 그 이상
- AWS 자격 증명이 적절한 권한으로 구성되었는지 확인 
- boto3 ,rich 라이브러리 설치 되었는지 확인 

실행에 필요한 AWS 권한들:
- rds:CreateBlueGreenDeployment
- rds:DeleteBlueGreenDeployment
- rds:DescribeBlueGreenDeployments
- rds:SwitchoverBlueGreenDeployment
- rds:DescribeDBClusters
- rds:DeleteDBCluster
- rds:DeleteDBInstance
- sts:GetCallerIdentity

### 환경 배포 과정 
```bash
# Clone the repository
git clone <repository-url>
cd aurora-bluegreen-deployment

# Install required Python packages
pip install boto3 rich
```

### Quick Start
1. Create a new Blue/Green deployment:
```bash
python bluegreen_create.py
```
1. 위 스크립트를 실행할때 다음 사항들을 입력해주세요:
- AWS region
- DB Cluster identifier
- Target engine version
- Parameter group name

2. 배포를 실행한 다음 배포상태를 아래 스크립트로 체크합니다:
```bash
python blugreen_creation_check.py --region us-west-2
```

3. 배포가 잘 되고 업그레이드가 잘 진행되었다면 사전체크를 진행하여 문제가 없다면, Blue/Green 전환을 진행합니다:
```bash
python bluegreen_switchover_pre_check,py us-west-2 
python bluegreen_switchover.py us-west-2
```

4. 배포 이후 사용하지 않는 old cluster 삭제과정입니다:
```bash
# 특정리전에 있는 클러스터들을 모두 삭제할때 사용합니다. 
python bluegreen_delete_old.py --region us-west-2

# 특정 클러스터만 삭제할 때 사용합니다. 
python bluegreen_delete_old.py --region us-west-2 --cluster_name mydb
```

### 멀티 어카운트, 멀티 리전에 배포하는 예제 
1. Multi-account, Multi-region에 Blue/Green 배포를 생성하는 과정입니다. 
```bash
# account_id,secret_name,region 정보가 accounts.csv에 들어가 있어야 합니다. 
python multi-account-bluegreen-deployment.py accounts.csv
```


### Troubleshooting
Common issues and solutions:

1. Deployment Creation Fails
- Error: "InvalidParameterCombination"
  - 새로운 데이터베이스 버전이 현재 버전과 호환되는지 확인하세요.
  - 설정한 파라미터 그룹이 실제로 존재하는지, 그리고 새 데이터베이스 버전과 호환되는지 확인하세요.
  - 원본 데이터베이스 클러스터가 현재 사용 가능한 상태인지 확인하세요. 유지보수 중이거나 다른 작업 중이면 배포를 시작할 수 없습니다.

2. Switchover Issues
- Error: "InvalidDBClusterState"
  - 새로 만든 데이터베이스 배포가 완전히 준비되어 "사용 가능(AVAILABLE)" 상태인지 확인하세요. 아직 준비 중이면 전환할 수 없습니다.
  - 데이터베이스에 예정된 유지보수 작업이 있는지 확인하세요. 있다면 먼저 처리해야 합니다.
  - 백업이나 복원 같은 다른 작업이 진행 중인지 확인하고, 완료될 때까지 기다리세요.

3. Deletion Failures
- Error: "ResourceBusy"
  - 데이터베이스에서 진행 중인 작업(예: 백업, 복원, 구성 변경)이 있다면 완료될 때까지 기다리세요.
  - 이 데이터베이스를 사용 중인 다른 서비스나 애플리케이션이 있는지 확인하세요. 있다면 먼저 연결을 끊어야 합니다.
  - 이 작업을 수행할 권한이 충분한지 확인하세요. 특히 데이터베이스 삭제 권한이 있는지 체크해보세요.

Debug Mode:
```bash
# Enable debug logging
export AWS_DEBUG=True
export AWS_LOG_LEVEL=DEBUG
```

## Data Flow
The toolkit manages Aurora MySQL cluster upgrades through AWS Blue/Green deployment mechanism, coordinating creation, validation, and switchover processes.

```ascii
[Source Cluster] --> [Blue/Green Creation] --> [Green Cluster]
                                                    |
[Validation & Monitoring] <-------------------------|
          |
          v
[Switchover] --> [Cleanup Old Resources]
```

Blue/Green 배포 전 과정을 정리하면 다음과 같습니다:
1. 생성 프로세스는 소스 클러스터를 검증하고 Green 환경을 생성합니다.
2. 모니터링은 배포 상태를 확인하여 배포가 제대로 되었는지 검증합니다. 
3. 전환과정을 통해 효과적으로 Blue/Green 전환을 진행합니다. (사전에 꼭 먼저 체크하시기 바랍니다)
4. 구 클러스터(old_로 시작하는 블루 클러스터)를 충분한 시간동안 확인하고 나서, 제거합니다. 
