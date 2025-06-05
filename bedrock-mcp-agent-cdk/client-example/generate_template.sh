#!/bin/bash

# 특정 노트북 파일명 지정
NOTEBOOK_FILE="bedrock-agent-test.ipynb"

# 파일 존재 여부 확인
if [ ! -f "$NOTEBOOK_FILE" ]; then
    echo "Error: $NOTEBOOK_FILE not found in current directory"
    exit 1
fi

echo "Using notebook file: $NOTEBOOK_FILE"

# 결과 템플릿 파일명
OUTPUT_FILE="generated-sagemaker-notebook-template.yaml"

# notebook 내용을 가져와서 적절한 들여쓰기 적용
NOTEBOOK_CONTENT=$(cat "$NOTEBOOK_FILE" | sed 's/^/                  /')

# CloudFormation 템플릿 생성
cat << EOF > "$OUTPUT_FILE"
AWSTemplateFormatVersion: '2010-09-09'
Description: 'SageMaker Notebook Instance with embedded notebook file'

Parameters:
  NotebookInstanceType:
    Description: SageMaker notebook instance type
    Type: String
    Default: ml.t3.medium
    AllowedValues:
      - ml.t3.medium
      - ml.t3.large
      - ml.t3.xlarge

Resources:
  SageMakerExecutionRole:
    Type: AWS::IAM::Role
    Properties:
      AssumeRolePolicyDocument:
        Version: '2012-10-17'
        Statement:
          - Effect: Allow
            Principal:
              Service: sagemaker.amazonaws.com
            Action: sts:AssumeRole
      ManagedPolicyArns:
        - arn:aws:iam::aws:policy/AmazonBedrockFullAccess

  NotebookInstance:
    Type: AWS::SageMaker::NotebookInstance
    Properties:
      InstanceType: !Ref NotebookInstanceType
      RoleArn: !GetAtt SageMakerExecutionRole.Arn
      LifecycleConfigName: !GetAtt NotebookLifecycleConfig.NotebookInstanceLifecycleConfigName

  NotebookLifecycleConfig:
    Type: AWS::SageMaker::NotebookInstanceLifecycleConfig
    Properties:
      OnStart:
        - Content:
            Fn::Base64: |
              #!/bin/bash
              
              # JupyterLab의 notebooks 디렉토리로 이동
              cd /home/ec2-user/SageMaker
              
              # notebook 파일 생성
              cat << 'EOT' > ${NOTEBOOK_FILE}
${NOTEBOOK_CONTENT}
              EOT
              
              # 파일 권한 설정
              chown ec2-user:ec2-user ${NOTEBOOK_FILE}

Outputs:
  NotebookInstanceId:
    Description: SageMaker Notebook Instance ID
    Value: !Ref NotebookInstance
  NotebookInstanceUrl:
    Description: URL of the SageMaker Notebook Instance
    Value: !Sub https://console.aws.amazon.com/sagemaker/home?region=\${AWS::Region}#/notebook-instances/openNotebook/\${NotebookInstance}?view=classic
EOF

echo "CloudFormation template has been generated as $OUTPUT_FILE"