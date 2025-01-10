# Smart Database Assistant with GenAI:Claude3

# **Why this project is created**
이 소스코드는 대량의 Aurora MySQL 데이터베이스 관리를 간소화하기 위해 LLM을 적용하는 아이디어에서 시작되었습니다.<br>
LLM에 Agent 개념을 도입하여, 오류 로그를 분석하고 자연어로 Cloudwatch 메트릭 정보를 검색하며 그래프를 생성하는 간단한 데모를 만들었습니다.<br>
이 프로젝트가 데이터베이스 관리 효율성을 향상시키기 위해 LLM 구현을 고려하는 고객들에게 큰 도움이 되기를 바랍니다.<br>

## **How to deploy and test the solution**

### 1. CloudFormation 콘솔에 damon.yaml을 업로드하고 스택을 생성합니다.
- db-admin.yaml 파일은 이 GitHub 저장소에서 사용할 수 있습니다.
- 홈 디렉토리에서 yaml 파일을 다운로드하세요
- Cloudformation에 db-admin.yaml을 업로드하고 us-east-1에 스택을 생성하세요

### 2. 스택 생성이 성공하면 콘솔에서 생성된 EC2 인스턴스에 직접 연결하고 다음과 같이 환경을 설정하고 라이브러리를 설치합니다:
```
    python3 -m venv myenv      
    source myenv/bin/activate  
    pip install --upgrade pip
    pip install mysql-connector-python
    pip install mysql.connector
    pip install boto3       
    pip install langchain-aws
    pip install gdown
    pip install matplotlib
    export AWS_DEFAULT_REGION=us-east-1
```

### 3.아래 명령어로 데이터를 다운로드합니다: (주의 ec2 리눅스 내에서 실행해야 에러가 나지 않습니다)
```        
    gdown https://drive.google.com/drive/folders/15oie9_FlNv871sIIAFBPPM5h0J8s61TU?usp=sharing  --folder
```
- 다운받은 다음,ls 명령어로 db-admin 폴더와 파일들을 볼 수 있습니다: ls -al /home/ec2-user <br>
```
   - db-admin <folder>
     - setup.sh 
     - db-admin.py
     - load_data.py
     - data.json
```
- cd db-admin 실행하여 db-admin 폴더로 들어갑니다. <br>        
- setup.sh에 chmod를 실행하고 setup.sh를 실행합니다 <br>
```
    chmod +x /home/ec2-user/db-admin/setup.sh
    /home/ec2-user/db-admin/setup.sh
```
- 이제 /home/ec2-user/에 복사된 db-admin.py를 찾을 수 있습니다.<br>

### 4. db-admin.py를 편집하고 파일의 s3 버킷 이름 변수를 수정합니다

- cloudformation 콘솔로 가서 db-admin.yaml로 만든 스택을 찾으세요 <br>
- resource 또는 output tab에 가서 s3 bucket명을 찾아서 copy하세요 <br>
- db-admin.py 를 열어서 s3_bucket_name 변수를 검색해서 옆에 copy한 내용을 아래와 같은 방식으로 붙여넣으세요. <br>
```
ex : s3_bucket_name = "test-s3bucket-fugwilwec8mx" 
```

### (optional) 4-1. 모든 Aurora MySQL 클러스터에서 Performance Insights와 Enhanced Monitoring을 활성화합니다.

- Aurora mysql 의 Performance Insight정보등이 활성화 되어있지 않으면 에러가 날수 있습니다. <br>
  에러가 난다면, RDS콘솔에서 각각의 Aurora cluster들을 선택하고 활성화 체크버튼에 체크를 해줘야 합니다.  <br>

    
### 5. 애플리케이션 실행:

- ec2 인스턴스내의 db-admin 폴더밑에서 "streamlit run db-admin.py"를 실행하여 애플리케이션을 시작합니다. <br>

-    그런 다음 채팅 창에서 다음 질문들을 진행해스 테스트 해보세요 :<br>
   ```
    a. 어제 하루동안 gamedb로 시작하는 모든 디비의 cpu,memory의 평균,커넥션과 HLL의 max값과 각종 레이턴시(dml,select..)들의 평균값을 보여줘.
    b. 모든디비의 디비로드 등 성능을 보여주고 분석까지 부탁해 (참고: 왼쪽의 리전과 클러스터들을 선택하고 날짜와 시간을 확인하세요) 
    c. top쿼리도 보여주세요. 
    d. game으로 시작하는 모든 디비들의 innodb status를 확인하고 분석해줘.
    e. game으로 시작하는 모든 디비의 이벤트별 메모리 사용율을 보여줘.
    f. game으로 시작하는 모든 디비의 버퍼캐시 히트율을 보여줘.
    g. game으로 시작하는 모든 디비의 슬로우 쿼리를 분석해줘.
    h. 어제 하루동안 game으로 시작하는 모든 디비의 에러로그를 분석해줘.
   
   ```
