import streamlit as st
from pathlib import Path
import pandas as pd
import mysql.connector
import boto3
import json
import re
import os
import requests
from datetime import datetime
import csv
from io import StringIO
import datetime
from botocore.exceptions import ClientError
import time
import logging
from langchain_aws import ChatBedrock
from langchain_core.messages import HumanMessage, AIMessage
from streamlit.web import cli as stcli
from streamlit import runtime
import sys
import matplotlib.pyplot as plt
from datetime import datetime, timedelta
import pytz
import io

#region_val = "us-east-1"

# Initialize logging
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

st.title("Aurora MySQL Database Management Demo with Claude3")

#이전 질문내용을 여기에 담아둔다. 
prv_prompt = '';

def format_text(text):
    # 여러 줄의 공백을 하나의 줄바꿈으로 대체
    text = re.sub(r"\n\s*\n", "\n", text)

    # '•' 기호 앞에 줄바꿈 추가 (첫 번째 '•' 제외)
    text = re.sub(r"(?<!^)\s*•", "\n•", text)

    # 각 '•' 항목 들여쓰기
    lines = text.split("\n")
    formatted_lines = []
    for line in lines:
        if line.strip().startswith("•"):
            formatted_lines.append(line)
        else:
            formatted_lines.append("  " + line)

    return "\n".join(formatted_lines)




# ChatBedrock instance creation
@st.cache_resource
def get_chat_model():
    return ChatBedrock(
        model_id="anthropic.claude-3-sonnet-20240229-v1:0",
        model_kwargs={"temperature": 0.7, "max_tokens": 4096},
    )


chat = get_chat_model()

# Session state initialization
if "messages" not in st.session_state:
    st.session_state.messages = []
if "mode" not in st.session_state:
    st.session_state.mode = "context"
if "context_window" not in st.session_state:
    st.session_state.context_window = 10

# Sidebar configuration
st.sidebar.title("Chat Settings")
st.session_state.mode = st.sidebar.radio("Chat Mode", ["context", "single"])
st.session_state.context_window = st.sidebar.slider("Context Window Size", 1, 10, 5)

# Reset conversation button
if st.sidebar.button("Reset Conversation"):
    st.session_state.messages = []
    st.rerun()
    prv_prompt =''

# Display chat history
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# Debug information
#if st.sidebar.checkbox("Show Debug Info"):
#    st.sidebar.write("Current Mode:", st.session_state.mode)
#    st.sidebar.write("Context Window Size:", st.session_state.context_window)
#    st.sidebar.write("Total Messages:", len(st.session_state.messages))

# AWS 리전 목록
regions = ['us-east-1', 'us-west-2', 'ap-northeast-2']

# 사이드바에서 사용자 입력 받기
region_name = st.sidebar.selectbox('AWS Region', regions)

# Initialize AWS clients
rds_client = boto3.client(service_name="rds",region_name=region_name)
pi_client = boto3.client(service_name="pi",region_name=region_name)
cw_client = boto3.client(service_name="cloudwatch",region_name=region_name)
athena_client = boto3.client(service_name="athena",region_name=region_name)

def get_aurora_clusters():
    clusters = []
    paginator = rds_client.get_paginator('describe_db_clusters')
    for page in paginator.paginate():
        for cluster in page['DBClusters']:
            if cluster['Engine'].startswith('aurora-mysql'):
                clusters.append(cluster['DBClusterIdentifier'])
    return clusters

# 데이터베이스 선택
clusters = get_aurora_clusters()
selected_clusters = st.sidebar.multiselect('Select DB Clusters', clusters)

#st.session_state.selected_clusters=selected_clusters
#print('first selected_clusters : ',selected_clusters)

# 선택된 클러스터의 인스턴스 목록 가져오기
instances = []
for cluster in selected_clusters:
    response = rds_client.describe_db_instances(Filters=[{'Name': 'db-cluster-id', 'Values': [cluster]}])
    instances.extend([instance['DBInstanceIdentifier'] for instance in response['DBInstances']])


# Database configuration
database_name = "sales"
pi_table_name = "performance_insights_data"
cw_table_name = "cw_monitoring_data"
s3_bucket_name = "test-s3bucket-fugwilwec8mx"
s3_bucket_path = f"s3://{s3_bucket_name}/{database_name}"
s3_bucket_table_cw_path = f"{s3_bucket_path}/data/cw_monitoring_data"
s3_bucket_table_pi_path = f"{s3_bucket_path}/data/performance_insight_monitoring_data"
s3_bucket_meta_path = f"{s3_bucket_path}/meta"


def interact_with_llm(secret_name, query):
    client = boto3.client("bedrock-runtime")
    model_Id = "anthropic.claude-3-sonnet-20240229-v1:0"
    accept = "application/json"
    contentType = "application/json"

    # Fetch Database Information Dynamically
    schema_context = get_database_info(secret_name)
    schema_context += "generate a sql command between <begin sql> and </end sql>"
    print("-----interact_with_llm:get_database_info:schema_context: ", schema_context)

    prompt_data = f"""Human: 당신은 Aurora MySQL 전문 DBA이며 Aurora MySQL에 관한 모든 질문에 답변할 수 있습니다.
                             제공된 맥락에서 정보가 없는 경우 '모르겠습니다'라고 응답해 주세요.
                             <context></context> 태그 안에는 테이블, 컬럼, 인덱스와 같은 스키마 정보가 있습니다.
                             <context>에 기반하여 정확한 테이블과 컬럼에서 정확한 컬럼명과 테이블명만 작성하세요.
                             또한 SQL 작성할때, <example></example> 태그에 있는 쿼리들을 참조해주세요.
                             다른 테이블과 조인할때, 동일한 컬럼명을 가져오면 다른 별칭을 추가하세요. <example>의 별칭 쿼리를 참조하세요.
                             프롬프트 입력으로 쿼리 또는 쿼리들을 받으면 그대로 반환해 주세요.
                             데이터베이스 키워드, 예약어, 모든 SQL문 및 AWS CLI를 포함한 명령어를 제외하고는 요청받았을 때 한국어로 설명해 주세요.
    <context>
    {schema_context}
    </context>
    <example>
    --별칭쿼리 : 서로 다른 테이블을 조인할때, select절에 동일한 이름이 있는 경우, 테이블의 별칭을 앞에 붙여, c.CustomerID,o.CustomerID형태로 사용 
    SELECT p.ProductID, p.ProductName, p.Price, p.StockQuantity, p.CategoryID, p.tag, p.new_column, p.tag2, p.tag3,
       c.CustomerID, c.FirstName, c.LastName, c.Email, c.Address, c.Phone,
       o.OrderID, o.CustomerID as o_CustomerID, o.ProductID as o_ProductID, o.Quantity, o.OrderDate, o.TotalPrice
    FROM products p
    JOIN orders o ON p.ProductID = o.ProductID
    JOIN customers c ON o.CustomerID = c.CustomerID;
    
    --여러개의 컬럼들을 한개로 합치는 쿼리 및 sum 함수를 이용한 컬럼값을 정렬하는 쿼리 
    SELECT CONCAT(c.FirstName, ' ', c.LastName) AS customer_name,
       o.OrderDate,
       p.ProductName,
       SUM(o.Quantity * p.Price) AS total_order_amt
    FROM orders o
    JOIN customers c ON o.CustomerID = c.CustomerID
    JOIN products p ON o.ProductID = p.ProductID
    GROUP BY customer_name, o.OrderDate, p.ProductName
    ORDER BY total_order_amt DESC; 
    
    --상위 top 쿼리 (부하가 가장 많은 쿼리)
    SELECT digest_text, count_star, sum_rows_examined, sum_created_tmp_disk_tables, sum_no_index_used  
    FROM performance_schema.events_statements_summary_by_digest
    ORDER BY SUM_TIMER_WAIT DESC, count_star DESC, 
             sum_rows_examined DESC,sum_no_index_used DESC, 
             sum_created_tmp_disk_tables DESC;
             
    --데이터베이스 전체상태 조회할때 명령어  :현재 접속한 디비의 Queries, Slow_queries, Thread_connected, Thread_running 정보를 보여줌 
    show global status 
    
    --현재 실행중인 모든 쿼리 
    SELECT * 
    FROM performance_schema.events_statements_current 
    WHERE SQL_TEXT IS NOT NULL;
    
    --InnoDB 상태확인 : 트랜잭션 락, 버퍼풀 상태 확인할때 사용 
    SHOW ENGINE INNODB STATUS;
    
    --테이블 상태 확인: 가장 큰 테이블이 어떤 테이블인지 확인 
    SELECT TABLE_SCHEMA, TABLE_NAME, ENGINE, ROW_FORMAT, TABLE_ROWS, AVG_ROW_LENGTH, DATA_LENGTH, INDEX_LENGTH
    FROM information_schema.TABLES
    WHERE TABLE_SCHEMA NOT IN ('mysql', 'information_schema', 'performance_schema')
    ORDER BY DATA_LENGTH + INDEX_LENGTH DESC
    LIMIT 10;
    
    --인덱스 사용통계 : 사용되지 않는 인덱스 식별 
    SELECT * FROM performance_schema.table_io_waits_summary_by_index_usage
    WHERE INDEX_NAME IS NOT NULL
    ORDER BY COUNT_STAR DESC;
    
    --이벤트별 메모리 사용율: 이벤트별 디비안에서 메모리 사용율을 보여준다. 
    SELECT EVENT_NAME,CURRENT_NUMBER_OF_BYTES_USED/1024/1024 as used_mem_mb 
    FROM performance_schema.memory_summary_global_by_event_name 
    ORDER BY 2 desc  
    limit 20;
    
    </example>
    <question>
    {query}
    </question>
    Assistant:"""

    claude_input = json.dumps(
        {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 1024,
            "messages": [
                {"role": "user", "content": [{"type": "text", "text": prompt_data}]}
            ],
            "temperature": 0.5,
            "top_k": 250,
            "top_p": 1,
            "stop_sequences": [],
        }
    )

    response = client.invoke_model(modelId=model_Id, body=claude_input)
    response_body = json.loads(response.get("body").read())
    print("------prompt:", prompt_data)

    try:
        message = response_body.get("content", [])
        result = message[0]["text"]
    except (KeyError, IndexError):
        result = "I'm sorry, I couldn't generate a response."

    print("interact_with_llm result:", result)
    return result


def interact_with_general_llm(user_request):
    client = boto3.client("bedrock-runtime")
    model_Id = "anthropic.claude-3-sonnet-20240229-v1:0"

    prompt_data = f"""Human: 당신은 Aurora MySQL 전문 DBA이며 Aurora MySQL에 관한 모든 질문에 답변할 수 있으며 다른 주제나 일반적인 대화도 가능합니다.
                             제공된 컨텍스트에 필요한 정보가 없으며 잘 모르는 경우 '모르겠습니다'라고 응답해 주세요.
                             스키마 정보를 사용하여 쿼리 실행 계획과 계획의 순서를 쉽게 분석하고 상세히 설명할 수 있습니다.
                             질문을 받았을 때 데이터베이스 키워드, 예약어, 모든 SQL문 및 AWS CLI를 포함한 명령어를 제외하고는 한글로 설명해주세요.
    
    <question>
    {user_request}
    </question>
    Assistant:"""

    claude_input = json.dumps(
        {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 4096,
            "messages": [
                {"role": "user", "content": [{"type": "text", "text": prompt_data}]}
            ],
            "temperature": 0.5,
            "top_k": 250,
            "top_p": 1,
            "stop_sequences": [],
        }
    )

    response = client.invoke_model(modelId=model_Id, body=claude_input)
    response_body = json.loads(response.get("body").read())
    print("------prompt:", prompt_data)

    try:
        message = response_body.get("content", [])
        result = message[0]["text"]
    except (KeyError, IndexError):
        result = "I'm sorry, I couldn't generate a response."

    print("interact_with_general llm result:", result)
    return result


def interact_with_llm_athena(database_name, query):
    
    print("query:",query)
    client = boto3.client("bedrock-runtime")
    model_Id = "anthropic.claude-3-sonnet-20240229-v1:0"

    # Fetch Database Information Dynamically
    schema_context = """TABLE performance_insights_data 
                            cluster_id string,
                            instance_id string,
                            metric string,
                            timestamp string,
                            value double
                        
                        TABLE cw_monitoring_data
                            cluster_id string,
                            instance_id string,
                            metric string,
                            timestamp string,
                            value double
                        TABLE cw_monitoring_data' Data: metric column has values like following
                             CPUUtilization, FreeableMemory, DatabaseConnections,Deadlocks,SelectLatency,ActiveTransactions,DMLLatency,CommitLatency, DDlLatency,RollbackSegmentHistoryListLength
                             
                     """
    print("schema_context", schema_context)
    schema_context += (
        "generate a sql command between <begin sql> and </end sql> refer example1,2! Don't use having clause "
    )

    prompt_data = f"""Human:   당신은 AWS 아테나의 쿼리를 잘 짜는 데이터 분석 전문가입니다. 자연어로 요청을 받으면, 요청받은 내용을 아테나쿼리로 바꿔서 답변해주세요. 
                               두개의 테이블을 조회하게 됩니다. 하나는 cw_monitoring_data 테이블입니다.  다른 하나는 performance_insights_data 테이블입니다. 
                               일반적인 use case로 요청사항이 CPU, Memory, HLL등과 같은 Cloudwatch metric을 물어볼때는 cw_monitoring_data테이블을 조회합니다.
                               SQL의 키워드와 테이블명, 컬럼명은 모두 영어입니다. 아래 제공되는 <context></context> 사이의 테이블 스키마를 참조해주세요. 
                               쿼리를 작성할때 <example1></example1> 과 같이 example2,example3...의 example tag 사이에 있는 쿼리들을 참조해주세요.
                               아테나에서는 쿼리할때 SELECT 절의 sum,avg같은 함수를 써서 가공한 컬럼들은 바로 having절에서 사용하지 못합니다. 
                               이런 경우는 쿼리를 select ...(select ...,sum(col1) as sum_col1...) where sum_col1 >=10 과 같은 형태로 쿼리를 만들어서 주세요.
                               이런 쿼리에 대한 예제로서 <example3>을 참조해주세요.
                               그리고,요청중에서 몇개만 보여주세요 하면 쿼리 마지막에 limit n(요청한 몇개) 을 붙여주세요 
                               예를 들어 CPU사용율이 높은 디비 2개만 보여주세요 하면 쿼리문 마지막에 limit 2 를 붙여주면 됩니다.
                               또는 cpu사용율이 60 이상인 값만 보여주세요 하면 where 절에 avg_cpu_per >=60 이렇게 조건절을 붙여서 쿼리를 생성해주세요. 
                               쿼리 생성할때 반드시, <context></context> 사이에 넣은 테이블 스키마정보를 가지고 테이블및 컬럼명에 맞는 쿼리를 만들어주세요.
                               테이블의 컬럼안의 값이 RollbackSegmentHistoryListLength 는 HLL이라고 alias를 만들어주세요 
                               또한, 성능지표 value값에서 메모리 사용율이 높은순으로, CPU 사용율이 높은순으로 보여달라고 할때는 Order by 절에 Desc를 사용하고
                               낮은순으로라고 하면 ASC를 써주세요.
                               만약 쿼리가 여러개를 만들면 가장 적합한 쿼리 한개만 실행해주시거나 union all로 두개이상의 쿼리가 합칠수 있는 쿼리(컬럼갯수와 명칭, 데이터타입이 맞으면)면 
                               union all로 쿼리를 합쳐서 생성해주세요. 기본적으로는 한개의 가장 적합한 쿼리만 만들어주세요. 
    <context>
    {schema_context}
    </context>
    <example1> 
        --이 쿼리는 Cloudwatch metric의 특정일시의 구간동안  cpu와 메모리의 평균값을 보여줍니다.  
        SELECT cluster_id, instance_id,
                        ROUND(max(CASE WHEN metric = 'CPUUtilization' THEN value else 0 END),2) AS max_cpu_per,
                        ROUND(min(CASE WHEN metric = 'FreeableMemory' THEN (value/1024/1024/1024) else 0 END),2) AS min_freeMemory_gb
        FROM cw_monitoring_data
        WHERE timestamp BETWEEN '2024-06-19 22:00' AND '2024-06-19 23:00'
        GROUP BY cluster_id, instance_id
        ORDER BY max_cpu_per DESC, min_freeMemory_gb ASC;
    </example1>
    <example2>
         --아래 쿼리는 Cloudwatch metric의 특정일시의 구간동안 cpu와 메모리의 평균값을 보여주되, 그중에 cpu평균값이 50 이상인 데이터를 보여줍니다. 
         SELECT cluster_id, instance_id,avg_cpu_per,avg_freeMemory_gb
         FROM (
                SELECT cluster_id, instance_id,
                        ROUND(AVG(CASE WHEN metric = 'CPUUtilization' THEN value else 0 END),2) AS max_cpu_per,
                        ROUND(AVG(CASE WHEN metric = 'FreeableMemory' THEN (value/1024/1024/1024) else 0 END),2) AS min_freeMemory_gb
                FROM cw_monitoring_data
                WHERE timestamp BETWEEN '2024-06-19 22:00' AND '2024-06-19 23:00'
                GROUP BY cluster_id, instance_id
                ORDER BY max_cpu_per DESC, min_freeMemory_gb ASC 
             )
        WHERE max_cpu_per >=50;
    </example2>
    <example3>
         --아래 쿼리는 Cloudwatch metric의 특정일시의 구간동안 cpu와 메모리의 평균값을 보여주고, 그중에서 cpu평균과 메모리 평균값이 높은 2건만 가져옵니다.  
         SELECT cluster_id, instance_id,max_cpu_per,min_freeMemory_gb
         FROM (
                SELECT cluster_id, instance_id,
                        ROUND(max(CASE WHEN metric = 'CPUUtilization' THEN value else 0 END),2) AS max_cpu_per,
                        ROUND(min(CASE WHEN metric = 'FreeableMemory' THEN (value/1024/1024/1024) else 0 END),2) AS min_freeMemory_gb,
                        ROUND(max(CASE WHEN metric = 'RollbackSegmentHistoryListLength' THEN value ELSE 0 END), 2) AS max_hll
                FROM cw_monitoring_data
                WHERE timestamp BETWEEN '2024-06-19 22:00' AND '2024-06-19 23:00'
                GROUP BY cluster_id, instance_id
                ORDER BY max_cpu_per DESC, min_freeMemory_gb ASC 
             )
        WHERE max_cpu_per >=50
        limit 2;
    </example3>
    <question>
    {query}
    </question>
    Assistant:"""

    print("prompt_data:", prompt_data)
    claude_input = json.dumps(
        {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 1024,
            "messages": [
                {"role": "user", "content": [{"type": "text", "text": prompt_data}]}
            ],
            "temperature": 0.5,
            "top_k": 250,
            "top_p": 1,
            "stop_sequences": [],
        }
    )

    response = client.invoke_model(modelId=model_Id, body=claude_input)
    response_body = json.loads(response.get("body").read())

    try:
        message = response_body.get("content", [])
        result = message[0]["text"]
    except (KeyError, IndexError):
        result = "I'm sorry, I couldn't generate a response."

    return result


# New function to interact with Knowledge Base
def query_knowledge_base(kb_id, query):
    client = boto3.client("bedrock-agent-runtime")
    try:
        response = client.retrieve(
            knowledgeBaseId=kb_id,
            retrievalQuery={"text": query},
            retrievalConfiguration={
                "vectorSearchConfiguration": {"numberOfResults": 3}
            },
        )
        return response["retrievalResults"]
    except Exception as e:
        logger.error(f"Error querying Knowledge Base: {str(e)}")
        return []


# get_database_info 에서 호출
def connect_to_db(secret_name):
    # Fetch the secret values
    secret_values = get_secret(secret_name)
    print("---------secret_values:", secret_values)
    # try:

    connection = mysql.connector.connect(
        host=secret_values["host"],
        user=secret_values["username"],
        password=secret_values["password"],
        port=secret_values["port"],
        database=secret_values["dbname"],
    )
    return connection
    # except Exception as e:
    #    print(f"Database connect Error: {e}")
    #    return None


# get_database_info 에서 호출
def get_secret(secret_name):
    # Initialize a session using Amazon Secrets Manager
    session = boto3.session.Session()
    client = session.client(service_name="secretsmanager")

    # Get the secret value
    get_secret_value_response = client.get_secret_value(SecretId=secret_name)
    secret = get_secret_value_response["SecretString"]
    return json.loads(secret)


# get_database_info 에서 호출
def save_to_s3(secret_name, metadata_info):
    s3 = boto3.client("s3")
    bucket_name = "using-genai-for-private-files-workshopoutputbucket-xi57to3uszjx"  # 버킷 이름 설정

    # 현재 날짜와 시간을 포함한 폴더 이름 생성
    # now = datetime.now()
    folder_name = secret_name  # {now.strftime('%Y%m%d_%H%M%S')}"

    # 데이터베이스 정보를 문자열로 변환
    metadata_info_str = "".join(metadata_info)

    # 기존 폴더 확인 및 삭제
    prefix = f"{folder_name}/"
    existing_objects = s3.list_objects(Bucket=bucket_name, Prefix=prefix)
    if "Contents" in existing_objects:
        for obj in existing_objects["Contents"]:
            s3.delete_object(Bucket=bucket_name, Key=obj["Key"])
        print(f"Existing folder '{folder_name}' deleted.")
    else:
        print(f"No existing folder found for '{folder_name}'.")

    # S3에 파일 업로드
    file_name = f"{folder_name}.txt"
    s3.put_object(
        Body=metadata_info_str.encode("utf-8"),
        Bucket=bucket_name,
        Key=f"{folder_name}/{file_name}",
    )

    print(
        f"Database information for {secret_name} uploaded to S3 bucket '{bucket_name}' in folder '{folder_name}'"
    )


def get_database_info(secret_name):
    secret_values = get_secret(secret_name)
    connection = mysql.connector.connect(
        host=secret_values["host"],
        user=secret_values["username"],
        password=secret_values["password"],
        port=secret_values["port"],
        database=secret_values["dbname"],
    )

    cursor = connection.cursor()
    cursor.execute("SELECT DATABASE();")  #
    database_name = cursor.fetchone()
    # 데이터베이스 내 모든 테이블 정보 가져오기
    cursor.execute(
        f''' SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE, COLUMN_COMMENT 
             FROM INFORMATION_SCHEMA.COLUMNS 
             WHERE TABLE_SCHEMA = '{database_name[0]}' 
             ORDER BY TABLE_NAME, ORDINAL_POSITION '''
    )
    table_info = cursor.fetchall()

    # 테이블 정보를 문자열로 변환
    table_info_str = "Current Database has following tables and columns: \n"
    current_table = None
    for row in table_info:
        table_name, column_name, data_type, column_comment = row

        if table_name != current_table:
            if current_table:
                table_info_str += "\n"
            table_info_str += f"{table_name} with columns:\n"
            current_table = table_name
        table_info_str += f"{column_name} {data_type} {column_comment}\n"

    # 인덱스 정보 가져오기
    cursor.execute(
        f'''SELECT TABLE_NAME, INDEX_NAME, COLUMN_NAME, NON_UNIQUE, INDEX_COMMENT 
            FROM INFORMATION_SCHEMA.STATISTICS 
            WHERE TABLE_SCHEMA = '{database_name[0]}'
            ORDER BY TABLE_NAME, INDEX_NAME'''
    )
    index_info = cursor.fetchall()

    index_info_str = "\nIndexes:\n"
    current_table = None
    for row in index_info:
        table_name, index_name, column_name, non_unique, index_comment = row
        if table_name != current_table:
            if current_table:
                index_info_str += "\n"
            index_info_str += f"{table_name}:\n"
            current_table = table_name
        index_info_str += f"  {index_name} ({column_name}) {'' if non_unique else 'UNIQUE'} {index_comment}\n"

    # 프라이머리 키 정보 가져오기
    cursor.execute(
        f'''SELECT TABLE_NAME, COLUMN_NAME, CONSTRAINT_NAME 
            FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE 
            WHERE TABLE_SCHEMA = '{database_name[0]}' 
            AND CONSTRAINT_NAME LIKE 'PRIMARY%' 
            ORDER BY TABLE_NAME'''
    )
    primary_key_info = cursor.fetchall()

    primary_key_info_str = "\nPrimary Keys:\n"
    current_table = None
    for row in primary_key_info:
        table_name, column_name, constraint_name = row
        if table_name != current_table:
            if current_table:
                primary_key_info_str += "\n"
            primary_key_info_str += f"{table_name}:\n"
            current_table = table_name
        primary_key_info_str += f"  {constraint_name} ({column_name})\n"

    # 시스템 뷰 정보 가져오기
    cursor.execute(
        f"SELECT TABLE_NAME, VIEW_DEFINITION, CHECK_OPTION, IS_UPDATABLE, DEFINER, SECURITY_TYPE FROM INFORMATION_SCHEMA.VIEWS WHERE TABLE_SCHEMA = '{database_name[0]}' ORDER BY TABLE_NAME"
    )
    system_view_info_str = cursor.fetchall()

    # 퍼포먼스 스키마 뷰 정보 가져오기
    cursor.execute(
        "SELECT TABLE_NAME, TABLE_TYPE, ENGINE, TABLE_COMMENT FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA = 'performance_schema' ORDER BY TABLE_NAME"
    )
    performance_schema_info = cursor.fetchall()

    performance_schema_info_str = "\nPerformance Schema Views:\n"
    for table_name, table_comment in performance_schema_info:
        performance_schema_info_str += f"{table_name}: {table_comment}\n"

    # print("performance_schema_info_str \n")
    # print(performance_schema_info_str)

    # 모든 메타데이터 정보 결합
    metadata_info = (
        table_info_str
        + index_info_str
        + primary_key_info_str
        + system_view_info_str
        + performance_schema_info_str
    )   
    results = metadata_info.split("'")

    print("--------results:", results)
    cursor.close()
    # S3에 데이터베이스 정보 저장
    save_to_s3(secret_name, results)
    return metadata_info


def execute_sql(secret_name, user_query):
    if user_query:

        llm_response = interact_with_llm(secret_name, user_query)
        # Convert multiline llm_response to single line
        # st.write(f"LLM Response: {llm_response}")
        print("-------execute_sql:secret_name:", secret_name)
        print("-------execute_sql:llm_response:", llm_response)
        # Extract SQL command from LLM response
        sql_command_match = re.search(
            r"<begin sql>(.*?)<\s?/end sql>", llm_response, re.DOTALL | re.IGNORECASE
        )
        # sql_command_match = re.sub("\n", "", sql_command_match)
        print("------execute_sql:sql_commands_match:", sql_command_match)

        if sql_command_match:
            sql_command = sql_command_match.group(1).strip()

            query_list = [q.strip() for q in sql_command.split(";") if q.strip()]

            print(
                "------execute_sql:if sql_command_match: ",
                sql_command + f" on database : {secret_name}",
            )
            try:

                connection = connect_to_db(secret_name)
                if connection:
                    print("connect")

                cursor = connection.cursor()

                for i, query in enumerate(query_list):
                    print(f"Executing query {i+1}:-----")
                    cursor.execute(query)
                    if cursor.with_rows:
                        columns = cursor.column_names
                        results = cursor.fetchall()
                        df = pd.DataFrame(results, columns=columns)
                        st.write(f"Results for Query {i+1}:")
                        st.write(df)
                    else:
                        st.write(
                            f"Query {i+1} executed successfully: {cursor.rowcount} rows affected."
                        )

                # 너비를 최대 200자리로 설정
                pd.set_option("display.max_rows", 200)
                # 최대 열 수를 20으로 설정
                pd.set_option("display.max_columns", 20)
                # 전체 너비를 200자리로 설정
                pd.set_option("display.width", 200)

            except Exception as e:
                print(f"Error executing SQL command: {e}")
        else:
            st.warning("No SQL command found in LLM response.")
            print("No SQL command found in LLM response.")


# execute_sql_multiDatabase 에서 호출
def get_secrets_by_keyword(keyword):
    secrets_manager = boto3.client(service_name="secretsmanager")
    response = secrets_manager.list_secrets(
        Filters=[{"Key": "name", "Values": [keyword]}]
    )
    return [secret["Name"] for secret in response["SecretList"]]


def execute_sql_multiDatabase(keyword, user_query):
    secret_lists = get_secrets_by_keyword(keyword)
    for secret_name in secret_lists:
        st.write("On the cluster ", secret_name, ", these workloads will be executed: ")
        execute_sql(secret_name, user_query)


# compare_database_info 에서 호출
def read_file_from_s3(bucket_name, folder_name, file_name):
    s3 = boto3.client("s3")
    try:
        obj = s3.get_object(Bucket=bucket_name, Key=f"{folder_name}/{file_name}")
        file_content = obj["Body"].read().decode("utf-8")
        return file_content
    except Exception as e:
        print(f"Error reading file from S3: {e}")
        st.error(f"Error reading file from S3: {e}")
        return None


# CloudWatch cw Monitoring 데이터 가져오기. 2개를 분리해야한다. 
def get_cw_monitoring(cluster_id, instance_id, start_time, end_time):
    response = cw_client.get_metric_data(
        MetricDataQueries=[
            {
                "Id": "cpu_utilization",
                "MetricStat": {
                    "Metric": {
                        "Namespace": "AWS/RDS",
                        "MetricName": "CPUUtilization",
                        "Dimensions": [
                            {"Name": "DBInstanceIdentifier", "Value": instance_id}
                        ],
                    },
                    "Period": 300,
                    "Stat": "Maximum",
                },
                "ReturnData": True,
            },
            {
                "Id": "memory_usage",
                "MetricStat": {
                    "Metric": {
                        "Namespace": "AWS/RDS",
                        "MetricName": "FreeableMemory",
                        "Dimensions": [
                            {"Name": "DBInstanceIdentifier", "Value": instance_id}
                        ],
                    },
                    "Period": 300,
                    "Stat": "Maximum",
                },
                "ReturnData": True,
            }
        ],
        StartTime=start_time,
        EndTime=end_time,
    )
    #print(response["MetricDataResults"])
    return response["MetricDataResults"]
    
def get_cw_monitoring2(cluster_id, start_time, end_time):
    response = cw_client.get_metric_data(
        MetricDataQueries=[
            {
                "Id": "active_transactions",
                "MetricStat": {
                    "Metric": {
                        "Namespace": "AWS/RDS",
                        "MetricName": "ActiveTransactions",
                        "Dimensions": [
                            {"Name": "DBClusterIdentifier", "Value": cluster_id}
                        ],
                    },
                    "Period": 300,
                    "Stat": "Sum",
                },
                "ReturnData": True,
            },
            {
                "Id": "database_connections",
                "MetricStat": {
                    "Metric": {
                        "Namespace": "AWS/RDS",
                        "MetricName": "DatabaseConnections",
                        "Dimensions": [
                            {"Name": "DBClusterIdentifier", "Value": cluster_id}
                        ],
                    },
                    "Period": 300,
                    "Stat": "Maximum",
                },
                "ReturnData": True,
            },
            {
                "Id": "deadlocks",
                "MetricStat": {
                    "Metric": {
                        "Namespace": "AWS/RDS",
                        "MetricName": "Deadlocks",
                        "Dimensions": [
                            {"Name": "DBClusterIdentifier", "Value": cluster_id}
                        ],
                    },
                    "Period": 300,
                    "Stat": "Sum",
                },
                "ReturnData": True,
            },
            {
                "Id": "select_latency",
                "MetricStat": {
                    "Metric": {
                        "Namespace": "AWS/RDS",
                        "MetricName": "SelectLatency",
                        "Dimensions": [
                            {"Name": "DBClusterIdentifier", "Value": cluster_id}
                        ],
                    },
                    "Period": 300,
                    "Stat": "Average",
                },
                "ReturnData": True,
            },
        
            {
                "Id": "commit_latency",
                "MetricStat": {
                    "Metric": {
                        "Namespace": "AWS/RDS",
                        "MetricName": "CommitLatency",
                        "Dimensions": [
                            {"Name": "DBClusterIdentifier", "Value": cluster_id}
                        ],
                    },
                    "Period": 300,
                    "Stat": "Average",
                },
                "ReturnData": True,
            },
            {
                "Id": "ddl_latency",
                "MetricStat": {
                    "Metric": {
                        "Namespace": "AWS/RDS",
                        "MetricName": "DDLLatency",
                        "Dimensions": [
                            {"Name": "DBClusterIdentifier", "Value": cluster_id}
                        ],
                    },
                    "Period": 300,
                    "Stat": "Average",
                },
                "ReturnData": True,
            },
            {
                "Id": "dml_latency",
                "MetricStat": {
                    "Metric": {
                        "Namespace": "AWS/RDS",
                        "MetricName": "DMLLatency",
                        "Dimensions": [
                            {"Name": "DBClusterIdentifier", "Value": cluster_id}
                        ],
                    },
                    "Period": 300,
                    "Stat": "Average",
                },
                "ReturnData": True,
            },
            {
                "Id": "rollback_segment_history_list_length",
                "MetricStat": {
                    "Metric": {
                        "Namespace": "AWS/RDS",
                        "MetricName": "RollbackSegmentHistoryListLength",
                        "Dimensions": [
                            {"Name": "DBClusterIdentifier", "Value": cluster_id}
                        ],
                    },
                    "Period": 300,
                    "Stat": "Maximum",
                },
                "ReturnData": True,
            },
        ],
        StartTime=start_time,
        EndTime=end_time,
    )
    #print(response["MetricDataResults"])
    return response["MetricDataResults"]


def upload_to_s3_cw(cluster_id, instance_id, data, bucket_name, bucket_path, object_key):
    s3_client = boto3.client("s3")

    # 데이터를 CSV 형식으로 변환
    csv_data = StringIO()
    writer = csv.writer(csv_data)

    # 헤더 작성
    header = ["DBClusterIdentifier","DBInstanceIdentifier","metric", "timestamp", "value"]
    writer.writerow(header)

    for result in data:
        metric_name = result["Label"]
        timestamps = result["Timestamps"]
        values = result["Values"]

        for timestamp, value in zip(timestamps, values):
            row = [
                cluster_id,
                instance_id,
                metric_name,
                timestamp.strftime("%Y-%m-%d %H:%M"),
                value,
            ]
            writer.writerow(row)

    csv_data.seek(0)

    # S3에 업로드
    object_path = f"{bucket_path}/{object_key}"
    s3_client.put_object(Bucket=bucket_name, Key=object_path, Body=csv_data.getvalue())
    print(f"Data {object_key} uploaded to {bucket_name}/{bucket_path}/{object_key}")

def check_table_exists(database_name, table_name):
    try:
        athena_client.get_table_metadata(
            CatalogName="AwsDataCatalog", DatabaseName="sales", TableName=table_name
        )
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] == "EntityNotFoundException":
            athena_client.start_query_execution(
                QueryString=f"CREATE EXTERNAL TABLE  {table_name}",
                ResultConfiguration={"OutputLocation": s3_bucket_meta_path},
            )


def retrieve_perf_metric_multiDatabase(keyword, start_time, end_time, user_query):
    # 시간세팅  start_time, end_time이 비어있으면
    
    print("start time:",start_time)
    print("end time:",end_time)

    # 데이터베이스 생성 (존재하지 않는 경우)
    try:
        athena_client.get_database(
            CatalogName="AwsDataCatalog", DatabaseName=database_name
        )
        print("create database")
    except ClientError as e:
        if e.response["Error"]["Code"] == "EntityNotFoundException":
            athena_client.start_query_execution(
                QueryString=f"CREATE DATABASE {database_name}",
                ResultConfiguration={"OutputLocation": s3_bucket_meta_path},
            )
        st.error(f"Error reading file from S3: {e}")

    # 테이블이 존재하는 경우 삭제
    if check_table_exists(database_name, cw_table_name):
        athena_client.start_query_execution(
            QueryString=f"DROP TABLE {database_name}.{cw_table_name}",
            ResultConfiguration={"OutputLocation": s3_bucket_meta_path},
        )
        print(f"{database_name}.{cw_table_name} dropped!")

    # print('pi table created')
    QueryString_input = f"""
        CREATE EXTERNAL TABLE {database_name}.{cw_table_name} (
            cluster_id string,
            instance_id string,
            metric string,
            timestamp string,
            value double
        )
        ROW FORMAT DELIMITED
        FIELDS TERMINATED BY ','
        LOCATION '{s3_bucket_table_cw_path}/'
        TBLPROPERTIES ('skip.header.line.count'='1')
        """
    print (QueryString_input)
    athena_client.start_query_execution(
        QueryString=QueryString_input,
        ResultConfiguration={"OutputLocation": s3_bucket_meta_path},
    )
    # print('QueryString',QueryString_input)
    secret_lists = get_secrets_by_keyword(keyword)
    for secret_name in secret_lists:
        secret_values = get_secret(secret_name)
        print(secret_values)  # test
        cluster_id = secret_values["dbClusterIdentifier"]
        print("clusterid:", cluster_id)
        response = rds_client.describe_db_clusters(DBClusterIdentifier=cluster_id)
        instances = response["DBClusters"][0]["DBClusterMembers"]
        for instance in instances:
            instance_id = instance["DBInstanceIdentifier"]
            print("instance_id:", instance_id)
            
            cw_data = get_cw_monitoring(
                cluster_id, instance_id, start_time, end_time
            )
            cw_data2 = get_cw_monitoring2(
                cluster_id, start_time, end_time
            )
            
            cw_data += cw_data2
            upload_to_s3_cw(
                cluster_id,
                instance_id,
                cw_data,
                s3_bucket_name,
                f"{database_name}/data/cw_monitoring_data",
                f"{cluster_id}_{cw_table_name}.csv",
            )
           
    user_query += f" 그리고 cw metric data 테이블에서 {start_time} 와 {end_time} 사이의 시간대에 필요할 경우 중첩 쿼리로 특정메트릭값이 얼마 이상인 값만 가져올수도 있습니다. "
    query_athena_table(database_name, user_query)



def query_athena_table(database_name, user_query):
    if user_query:
        print("query_athena_table")
        llm_response = interact_with_llm_athena(database_name, user_query)
        print("llm_response : ", llm_response)
        # Convert multiline llm_response to single line
        # st.write(f"LLM Response: {llm_response}")
        # print(llm_response)
        # Extract SQL command from LLM response
        sql_command_match = re.search(
            r"<begin sql>(.*?)<\s?/end sql>", llm_response, re.DOTALL | re.IGNORECASE
        )
        # sql_command_match = re.sub("\n", "", sql_command_match)
        # print(sql_command_match)
        print("sql_command_match : ", sql_command_match)
        if sql_command_match:
            sql_command = sql_command_match.group(1).strip()
            print(sql_command)
            try:
                # 쿼리 실행
                response = athena_client.start_query_execution(
                    QueryString=sql_command,
                    QueryExecutionContext={"Database": database_name},
                    ResultConfiguration={
                        "OutputLocation": f"s3://{s3_bucket_name}/{database_name}/query_results/"
                    },
                )

                # 쿼리 실행 상태 확인
                query_execution_id = response["QueryExecutionId"]
                while True:
                    status = athena_client.get_query_execution(
                        QueryExecutionId=query_execution_id
                    )
                    state = status["QueryExecution"]["Status"]["State"]
                    if state == "SUCCEEDED":
                        break
                    elif state == "FAILED":
                        raise Exception(
                            f"Query failed: {status['QueryExecution']['Status']['StateChangeReason']}"
                        )
                    time.sleep(1)

                # 쿼리 결과 가져오기
                result = athena_client.get_query_results(
                    QueryExecutionId=query_execution_id
                )
                rows = result["ResultSet"]["Rows"]
                headers = [
                    header["Name"]
                    for header in result["ResultSet"]["ResultSetMetadata"]["ColumnInfo"]
                ]
                data = [
                    [row["VarCharValue"] for row in rec["Data"]] for rec in rows[1:]
                ]
                print(data)
                df = pd.DataFrame(data, columns=headers)

                # DataFrame을 문자열로 변환하여 반환
                st.write(df)
                return df.to_string(index=False)
            except Exception as e:
                print(f"Error querying Athena table: {e}")
                return None
        else:
            st.warning("No SQL command found in LLM response.")
            print("No SQL command found in LLM response.")


def analyze_performance(db_identifier, start_time, end_time):
    fig, axs = plt.subplots(3, 1, figsize=(12, 18))
    all_data = []
    metrics = [
        {'name': 'Database Load', 'metric': 'db.load.max', 'group_by': {'Group': 'db.wait_event'}},
        {'name': 'CPU Utilization', 'metric': 'os.cpuUtilization.total.max'},
        {'name': 'Freeable Memory', 'metric': 'os.memory.free.min'}
    ]
    
    rds_client = boto3.client('rds')
    pi_client = boto3.client('pi')
    
    for instance in instances:
        try:
            response = rds_client.describe_db_instances(DBInstanceIdentifier=instance)
            resource_id = response['DBInstances'][0]['DbiResourceId']
            
            for i, metric in enumerate(metrics):
                metric_query = {
                    'Metric': metric['metric']
                }
                if 'group_by' in metric:
                    metric_query['GroupBy'] = metric['group_by']

                pi_response = pi_client.get_resource_metrics(
                    ServiceType='RDS',
                    Identifier=resource_id,
                    StartTime=start_time,
                    EndTime=end_time,
                    PeriodInSeconds=3600,  # 1시간 간격으로 데이터 가져오기
                    MetricQueries=[metric_query]
                )
                
                data = pi_response['MetricList'][0]['DataPoints']
                df = pd.DataFrame(data)
                if not df.empty:
                    df['Timestamp'] = pd.to_datetime(df['Timestamp'])
                    df.set_index('Timestamp', inplace=True)
                    df.sort_index(inplace=True)
                    df['Instance'] = instance
                    df['MetricName'] = metric['name']
                    
                    axs[i].plot(df.index, df['Value'], label=instance)
                    all_data.append(df)
                
        except Exception as e:
            st.error(f"Error retrieving data for instance {instance}: {str(e)}")
    
    for i, metric in enumerate(metrics):
        axs[i].set_title(f'AWS Aurora MySQL Performance Insights - {metric["name"]}')
        axs[i].set_xlabel('Time')
        axs[i].set_ylabel('Value')
        axs[i].grid(True)
        if axs[i].get_legend_handles_labels()[0]:  # 레전드에 표시할 항목이 있는 경우에만 레전드 표시
            axs[i].legend()
    
    plt.tight_layout()
    st.pyplot(fig)
    
    if all_data:
        combined_df = pd.concat(all_data)
        
        st.subheader('Performance Statistics')
        stats = combined_df.groupby(['Instance', 'MetricName'])['Value'].agg(['mean', 'max', 'min']).reset_index()
        stats.columns = ['Instance', 'Metric', 'Average', 'Maximum', 'Minimum']
        st.dataframe(stats)
        
        #st.subheader('Raw Data')
        #st.dataframe(combined_df)
    else:
        st.warning("No data available for the selected instances.")
    
    analysis_prompt = f"""Analyze the following performance data for the Aurora MySQL database {db_identifier}:
    Performance Insights:
    {combined_df.to_string() if 'combined_df' in locals() else 'No data available'}
    Please provide insights on the database performance, identify any potential issues, and suggest optimizations."""
    llm_response = interact_with_general_llm(analysis_prompt)
    st.write(llm_response)


def explain_plan_query(keyword, user_query):
    secret_name = keyword
    print("explain_plan_query executed!")
    user_query += " when you get query , add explain before query! "
    if user_query:
        llm_response = interact_with_llm(secret_name, user_query)
        sql_command_match = re.search(
            r"<begin sql>(.*?)<\s?/end sql>", llm_response, re.DOTALL | re.IGNORECASE
        )
        prompt2 = ""
        if sql_command_match:
            sql_command = sql_command_match.group(1).strip()
            print(sql_command + f" on {secret_name}")
            try:

                connection = connect_to_db(secret_name)
                cursor = connection.cursor()
                cursor.execute(sql_command)
                result = cursor.fetchall()
                columns = cursor.column_names
                df = pd.DataFrame(result, columns=columns)

                # 너비를 최대 200자리로 설정
                pd.set_option("display.max_rows", 200)
                # 최대 열 수를 20으로 설정
                pd.set_option("display.max_columns", 20)
                # 전체 너비를 200자리로 설정
                pd.set_option("display.width", 200)

                st.write(df)

                prompt2 = "please explain details with this query plan :" + str(result)
                llm_response2 = interact_with_general_llm(prompt2)
                st.write(llm_response2)

            except Exception as e:
                print(f"Error executing SQL command: {e}")
        else:
            st.warning("No SQL command found in LLM response.")
            print("No SQL command found in LLM response.")



def get_top_sql_data(selected_clusters2, start_time, end_time, limit):
    limit=20
    print('selected_clusters: ',selected_clusters)
    print('start_time:',start_time)
    print('end_time:',end_time)
    instances = []
    sql_data = []
    print('limit:',limit)
 
    for cluster in selected_clusters:                
        print('cluster:',cluster)
        response = rds_client.describe_db_instances(Filters=[{'Name': 'db-cluster-id', 'Values': [cluster]}])
        instances = [instance['DBInstanceIdentifier'] for instance in response['DBInstances']]
       
        for instance in instances:
            print('instance:',instance)

            response = rds_client.describe_db_instances(DBInstanceIdentifier=instance)
            resource_id = response['DBInstances'][0]['DbiResourceId']
            print('resource id:', resource_id)
            response2 = pi_client.get_resource_metrics(
                ServiceType='RDS',
                Identifier=resource_id,
                StartTime=start_time,
                EndTime=end_time,
                PeriodInSeconds=3600,
                MetricQueries=[
                    {
                        'Metric': 'db.load.max',
                        'GroupBy': {
                            'Group': 'db.sql',
                            'Limit': limit
                        }
                    }
                ]
            )
        
            for metric in response2.get('MetricList', []):
                key = metric.get('Key', {})
                dimensions = key.get('Dimensions', {})
                data_points = metric.get('DataPoints', [])
                
                total_load = sum(dp.get('Value', 0) for dp in data_points)
                
                sql_info = {
                    'Cluster Identifier': cluster,
                    'Instance Identifier': instance,
                    'SQL Text': dimensions.get('db.sql.statement', 'N/A'),
                    'SQL ID': dimensions.get('db.sql.id', 'N/A'),
                    'DB Load': total_load
                }
                sql_data.append(sql_info)
            
    # DataFrame 생성
    df = pd.DataFrame(sql_data)
    
    # SQL Text 열의 내용을 축약하는 함수
    def shorten_sql(sql, max_length=50):
        return sql[:max_length] + '...' if len(sql) > max_length else sql
    print("sql_data: ",sql_data)
    # SQL Text 열의 내용을 축약
    df['Short SQL Text'] = df['SQL Text'].apply(shorten_sql)
    
    # 정렬: Cluster Identifier와 Instance Identifier는 오름차순, DB Load는 내림차순
    df = df.sort_values(by=['Cluster Identifier', 'Instance Identifier', 'DB Load'], 
                        ascending=[True, True, False])
    
    # 열 순서 재배열
    df = df[['Cluster Identifier', 'Instance Identifier', 'Short SQL Text','SQL ID', 'DB Load', 'SQL Text']]
    
    # DataFrame 표시 (큰 크기로)
    st.dataframe(df.style.format({'DB Load': '{:.2f}'.format}), width=1200, height=400)

    return df


def analyze_innodb_status(keyword): 
    results = '';
    secret_lists = get_secrets_by_keyword(keyword)
    for secret_name in secret_lists:
        st.write("On the cluster ", secret_name, ", these workloads will be executed: ")
       
        sql_command = 'SHOW ENGINE INNODB STATUS;'
        print(sql_command + f" on {secret_name}")
        try:
            connection = connect_to_db(secret_name)
            cursor = connection.cursor()
            cursor.execute(sql_command)
            result = cursor.fetchall()
            columns = cursor.column_names
            #df = pd.DataFrame(result, columns=columns)
            # 너비를 최대 200자리로 설정
            #pd.set_option("display.max_rows", 200)
            # 최대 열 수를 20으로 설정
            #pd.set_option("display.max_columns", 20)
            # 전체 너비를 200자리로 설정
            #pd.set_option("display.width", 400)
            #st.write(df)
            results += secret_name + str(result)

            #st.write(llm_response2)

        except Exception as e:
             print(f"Error executing SQL command: {e}")
       
    prompt = '''평가한 내용에서 트랜잭션, 락, 버퍼풀등의 정보를 보고 현재 디비의 상태를 분석해주세요. 가능하면 의미있는 데드락,버퍼풀 히트율도 계산해주세요!:
                그외에도 Aurora mysql의 의미있는 정보들을 분석해서 알려주세요. 마지막에는 각 디비별로 간략하게 요약해서 분석의 가장 중요한 결과를 알려주세요! 
                다음과 같은 형식으로 분석하고 정리해주세요.
                <format>
                1.Gamedb cluster 1 \n
                  Transactions 
                  LATEST DETECTED DEADLOCK 
                  BUFFER POOL AND MEMORY                 
                  Row operations
                  Disk I/O workloads 
                  INSERT BUFFER AND ADAPTIVE HASH INDEX usage

                  ...

                2.Gamedb cluster 2 \n
                  Transactions 
                  LATEST DETECTED DEADLOCK 
                  BUFFER POOL AND MEMORY
                  Row operations
                  Disk I/O workloads 
                  INSERT BUFFER AND ADAPTIVE HASH INDEX usage

                  ...
                  
                
                
                   (참조) 이와 같이 여러개의 디비가 있으면 위와 같은 형식으로 보여주세요.
                   
                결론 : 
                </format>  
                   
                \n
                ''' + results
            
    llm_response = interact_with_general_llm(prompt)
    st.write(llm_response)    



def get_event_memory_status(keyword):
    results = '';
    secret_lists = get_secrets_by_keyword(keyword)
    for secret_name in secret_lists:
        st.write("On the cluster ", secret_name, ", these workloads will be executed: ")
       
        sql_command = ''' SELECT EVENT_NAME,CURRENT_NUMBER_OF_BYTES_USED/1024/1024 as used_mem_mb 
                          FROM performance_schema.memory_summary_global_by_event_name 
                          ORDER BY 2 desc  
                          limit 20 '''
                          
        sql_command2 =''' SELECT t.THREAD_ID,
                                 t.PROCESSLIST_ID,
                                 t.PROCESSLIST_USER,
                                 t.PROCESSLIST_HOST,
                                 t.PROCESSLIST_DB,
                                 t.PROCESSLIST_COMMAND,
                                 t.PROCESSLIST_TIME,
                                 t.PROCESSLIST_STATE,
                                 es.EVENT_ID,
                                 es.SQL_TEXT,
                                 es.TIMER_WAIT / 1000000000 AS TIMER_WAIT_MS,
                                 es.LOCK_TIME / 1000000000 AS LOCK_TIME_MS,
                                 es.ROWS_EXAMINED,
                                 es.ROWS_SENT
                            FROM performance_schema.threads t
                            LEFT JOIN 
                                performance_schema.events_statements_current es
                            ON  t.THREAD_ID = es.THREAD_ID
                            WHERE 
                                t.PROCESSLIST_ID IS NOT NULL
                                AND es.SQL_TEXT IS NOT NULL
                            ORDER BY  es.TIMER_WAIT DESC '''
                            
        print(sql_command + f" on {secret_name}")
        try:
            connection = connect_to_db(secret_name)
            cursor = connection.cursor()
            cursor.execute(sql_command)
            result = cursor.fetchall()
            columns = cursor.column_names
            df = pd.DataFrame(result, columns=columns)

            # 너비를 최대 200자리로 설정
            pd.set_option("display.max_rows", 200)
            # 최대 열 수를 20으로 설정
            pd.set_option("display.max_columns", 20)
            # 전체 너비를 200자리로 설정
            pd.set_option("display.width", 400)
            
            cursor.execute(sql_command2)
            result2 = cursor.fetchall()
            columns = cursor.column_names
            df2 = pd.DataFrame(result2, columns=columns)

            st.write(df)
            st.write(df2)
            results += secret_name+' has Following information under line --------- \n '
            results += '------------------------------' 
            results += 'memory usage by event :\n' + str(result) +'\n '
            results += 'memory usage by thread : \n' + str(result2) +'\n '

        except Exception as e:
             print(f"Error executing SQL command: {e}")
       
    prompt = '''각 디비클러스터별로 memory 사용현황에 대해서 가장 많이 메모리를 사용하는 이벤트에 대해서 확인해주세요.
                특히 Show full process list에서 나온 어떤 Thread가 메모리를 많이 사용하는지도 알려주세요.
                <format>
                1.Gamedb cluster 1 \n
                 

                2.Gamedb cluster 2 \n
                  
                ...
                
                   
                결론 : (참조) 각 디비별로 어떤 이벤트와, 쓰레드가 메모리를 많이 사용하는지 알려주세요.
                </format>  
                ''' + results
            
    llm_response = interact_with_general_llm(prompt)
    st.write(llm_response)    


def get_buffer_hit_ratio(keyword):
    results = ''
    secret_lists = get_secrets_by_keyword(keyword)
    
    # 모든 결과를 저장할 리스트 생성
    all_results = []

    for secret_name in secret_lists:
        st.write("On the cluster ", secret_name, ", these workloads will be executed: ")
       
        sql_command = '''
        SELECT 
            (1 - (
                SUM(IF(variable_name IN ('Innodb_buffer_pool_reads'), variable_value, 0)) /
                SUM(IF(variable_name IN ('Innodb_buffer_pool_read_requests'), variable_value, 0))
            )) * 100 AS buffer_pool_hit_ratio
        FROM performance_schema.global_status
        WHERE variable_name IN ('Innodb_buffer_pool_reads', 'Innodb_buffer_pool_read_requests');
        '''
                          
        print(sql_command + f" on {secret_name}")
        try:
            connection = connect_to_db(secret_name)
            cursor = connection.cursor()
            cursor.execute(sql_command)
            result = cursor.fetchall()
            
            print(result)
            
            # 결과와 데이터베이스 이름을 리스트에 추가
            all_results.append({
                'Database': secret_name,
                'Buffer Pool Hit Ratio': result[0][0]  # 첫 번째 행의 첫 번째 열 값
            })
           
            results += f"{secret_name} has Following information under line --------- \n"
            results += '------------------------------\n'
            results += f'Buffer cache hit ratio: {result[0][0]:.2f}%\n\n'
        except Exception as e:
             print(f"Error executing SQL command: {e}")
    
    # 모든 결과를 하나의 DataFrame으로 변환
    df = pd.DataFrame(all_results)
    
    # DataFrame 출력 설정
    pd.set_option("display.max_rows", 200)
    pd.set_option("display.max_columns", 20)
    pd.set_option("display.width", 400)
    
    # DataFrame 출력
    st.write(df)
       
    prompt = '''각 디비클러스터의 버퍼캐시 히트율을 알려주시고 버퍼캐시 히트율이 낮은 경우 어떤 방법으로 히트율을 높일수 있을지 가이드도 부탁합니다.
                <format>
                gamedb1 : 99% 버퍼캐시 히트율이 높습니다 또는 낮습니다. \n
                gamedb2 : 95% 버퍼캐시 히트율이 높습니다 또는 낮습니다.\n 
                gamedb3 : 94% 버퍼캐시 히트율이 높습니다 또는 낮습니다.\n 
                ...
                gamedbN : n% 버퍼캐시 히트율이 높습니다 또는 낮습니다. \n
                </format>  
                ''' + results
            
    llm_response = interact_with_general_llm(prompt)
    st.write(llm_response)

    return df  # DataFrame 반환


def ensure_s3_path_exists(s3_client, bucket_name, path):
    # 경로의 각 레벨에 대해 빈 객체 생성
    parts = path.strip('/').split('/')
    for i in range(1, len(parts) + 1):
        prefix = '/'.join(parts[:i]) + '/'
        print('prefix:', prefix)
        try:
            s3_client.head_object(Bucket=bucket_name, Key=prefix)
        except ClientError as e:
            # 객체가 존재하지 않을 때만 생성
            if e.response['Error']['Code'] == '404':
                print(f"Creating prefix: {prefix}")
                s3_client.put_object(Bucket=bucket_name, Key=prefix, Body='')
            else:
                raise  # 다른 종류의 오류면 예외를 다시 발생시킵니다.

def download_and_upload_slow_query_logs(keyword, start_datetime_str, end_datetime_str):
    start_time = datetime.strptime(start_datetime_str, "%Y-%m-%d %H:%M:%S")
    end_time   = datetime.strptime(end_datetime_str, "%Y-%m-%d %H:%M:%S")
    results = []
    s3_client = boto3.client(service_name="s3",region_name=region_name)
    print('start_time : ',start_time)
    print('end_time : ',end_time)
    secret_lists = get_secrets_by_keyword(keyword)
    
    for secret_name in secret_lists:
        response = rds_client.describe_db_instances(Filters=[{'Name': 'db-cluster-id', 'Values': [secret_name]}])
        instances = [instance['DBInstanceIdentifier'] for instance in response['DBInstances']]
       
        for instance in instances:
            header_written = False
            log_content = io.StringIO()  # 각 인스턴스마다 새로운 log_content 객체 생성
            output_file = f"full_slowquery_{instance}_{start_time.strftime('%Y%m%d%H%M')}_to_{end_time.strftime('%Y%m%d%H%M')}.log"
    
            log_file_list = rds_client.describe_db_log_files(
                DBInstanceIdentifier=instance,
                FilenameContains='slowquery'
            )
    
            for log_file_info in log_file_list['DescribeDBLogFiles']:
                log_filename = log_file_info['LogFileName']
                last_written = datetime.fromtimestamp(log_file_info['LastWritten'] / 1000)
                if start_time <= last_written <= end_time:
                    response = rds_client.download_db_log_file_portion(
                        DBInstanceIdentifier=instance,
                        LogFileName=log_filename,
                        Marker='0'
                    )
                    
                    log_data = response.get('LogFileData', '')
                    lines = log_data.splitlines()
                    
                    for line in lines:
                        if line.startswith('/rdsdbbin/oscar/bin/mysqld'):
                            if not header_written:
                                log_content.write(line + '\n')
                                header_written = True
                        elif not line.startswith('Time') and line.strip() != '' and 'END OF LOG' not in line:
                            log_content.write(line + '\n')
        
            # S3에 파일 업로드
            s3_key = f"slowquery/{instance}/{output_file}"
            ensure_s3_path_exists(s3_client, s3_bucket_name, f"slowquery/{instance}/")
            s3_client.put_object(Bucket=s3_bucket_name, Key=s3_key, Body=log_content.getvalue())
            print(f"Log file uploaded to s3://{s3_bucket_name}/{s3_key}")
    
            # S3에서 파일 읽기 및 출력
            response = s3_client.get_object(Bucket=s3_bucket_name, Key=s3_key)
            content = response['Body'].read().decode('utf-8')
            results.append(f"<{instance}>\n{content}\n</{instance}>")
            
    prompt = '''아래 로그는 슬로우 쿼리 로그입니다. 각 instance별로 아래와 같은 형식으로 슬로우쿼리를 리스트업하고 각각에 대해 성능과 문제점을 분석해주세요.
                instance의 슬로우 로그구분은 아래와 같이 <instance명>과 </instance명> 사이에 있는 로그는 해당 인스턴스의 slow log입니다.
                <instance명>
                </instance명>
                ''' + '\n'.join(results)
            
    llm_response = interact_with_general_llm(prompt)
    
    st.markdown(llm_response)

def analyze_aurora_mysql_error_logs(keyword, start_datetime_str, end_datetime_str):
    # 시작 및 종료 시간을 datetime 객체로 변환
    start_time = datetime.strptime(start_datetime_str, "%Y-%m-%d %H:%M:%S")
    end_time = datetime.strptime(end_datetime_str, "%Y-%m-%d %H:%M:%S")
    results = []
    s3_client = boto3.client(service_name="s3", region_name=region_name)
    rds_client = boto3.client('rds', region_name=region_name)
    
    print('시작 시간: ', start_time)
    print('종료 시간: ', end_time)
    
    # 키워드로 시크릿 리스트 가져오기
    secret_lists = get_secrets_by_keyword(keyword)
    
    for secret_name in secret_lists:
        # 각 시크릿에 대한 DB 인스턴스 식별자 가져오기
        response = rds_client.describe_db_instances(Filters=[{'Name': 'db-cluster-id', 'Values': [secret_name]}])
        instances = [instance['DBInstanceIdentifier'] for instance in response['DBInstances']]
        
        for instance in instances:
            log_content = io.StringIO()
            output_file = f"error_log_{instance}_{start_time.strftime('%Y%m%d%H%M')}_to_{end_time.strftime('%Y%m%d%H%M')}.log"
            
            # 에러 로그 파일 목록 가져오기
            log_file_list = rds_client.describe_db_log_files(
                DBInstanceIdentifier=instance,
                FilenameContains='error'
            )
            
            for log_file_info in log_file_list['DescribeDBLogFiles']:
                log_filename = log_file_info['LogFileName']
                last_written = datetime.fromtimestamp(log_file_info['LastWritten'] / 1000)
                if start_time <= last_written <= end_time:
                    # 로그 파일의 내용 다운로드
                    response = rds_client.download_db_log_file_portion(
                        DBInstanceIdentifier=instance,
                        LogFileName=log_filename,
                        Marker='0'
                    )
                    
                    log_data = response.get('LogFileData', '')
                    lines = log_data.splitlines()
                    
                    for line in lines:
                        # Aurora MySQL 3.5의 중요한 에러 로그 항목 필터링
                        if any(keyword in line.lower() for keyword in ['error', 'warning', 'critical', 'failed', 'crash', 'exception']):
                            log_content.write(line + '\n')
            
            # S3에 파일 업로드
            s3_key = f"errorlogs/{instance}/{output_file}"
            ensure_s3_path_exists(s3_client, s3_bucket_name, f"errorlogs/{instance}/")
            s3_client.put_object(Bucket=s3_bucket_name, Key=s3_key, Body=log_content.getvalue())
            print(f"Log file uploaded to s3://{s3_bucket_name}/{s3_key}")
            
            # S3에서 파일을 읽고 결과에 추가
            response = s3_client.get_object(Bucket=s3_bucket_name, Key=s3_key)
            content = response['Body'].read().decode('utf-8')
            results.append(f"<{instance}>\n{content}\n</{instance}>")
    
    prompt = '''아래는 Aurora MySQL 3.5 인스턴스의 에러 로그입니다. 각 인스턴스에 대한 에러로그를 분석하고 다음 사항에 대한 요약을 제공해주세요:
                <instance명>과 </instance명> 사이에 있는 로그는 해당 인스턴스의 error log입니다.
                <instance명>
                </instance명> 태그 사이에 포함되어 있습니다.
                
                어떤 키워드의 에러가 가장 많이 나타났는지, 에러카테고리별로 집계도 부탁합니다.
                아래와 같은 포맷으로 각 인스턴스별로 에러 카테고리별로 집계하고, 분석한 내용을 넣어주세요 
                예를 들어 aborted connection이 몇건있었고, 그것은 어떤 영향을 가지는지 설명해주세요.
                분석할때 어느파일에 있는 어떤 내용을 근거로 했는지 명확하게 하고, 그렇지 않으면 모르겠다고 합니다.
                또한 분석할때 <context></context>에 있는 내용을 참고하여 분석하고 관련에러가 발견되면, 그에 대해 정리부탁합니다.
                
                1.instance1
                
                2.instance2
                
                3.instance3
                ...
                <context>
                심각한 에러 키워드
                1. "Fatal error"
                    영향도: 매우 높음
                    데이터베이스 서버가 중지되거나 재시작될 수 있는 심각한 문제를 나타냅니다.
                2. "Out of memory"
                    영향도: 높음
                    메모리 부족으로 인한 성능 저하 및 쿼리 실패가 발생할 수 있습니다.
                3. "Disk full"
                    영향도: 높음
                    디스크 공간 부족으로 데이터 쓰기 작업이 실패할 수 있습니다.
                4. "Connection refused"
                    영향도: 중간에서 높음
                    클라이언트 연결 문제로 인해 서비스 중단이 발생할 수 있습니다.
                5. "InnoDB: Corruption"
                    영향도: 높음
                    데이터 무결성 문제를 나타내며 데이터 손실 가능성이 있습니다.
                    주의가 필요한 에러 키워드
                6. "Slow query"
                    영향도: 중간
                    성능 저하를 일으키는 쿼리를 식별하는 데 도움이 됩니다.
                7. "Lock wait timeout exceeded"
                    영향도: 중간
                    동시성 문제로 인한 쿼리 지연 또는 실패를 나타냅니다.
                8. "Warning"
                    영향도: 낮음에서 중간
                    잠재적인 문제를 나타내지만 즉각적인 조치가 필요하지 않을 수 있습니다.
                9. "Table is full"
                    영향도: 중간
                    특정 테이블에 더 이상 데이터를 삽입할 수 없음을 나타냅니다.
               10. "Deadlock found"
                    영향도: 중간
                    트랜잭션 충돌로 인한 성능 저하를 나타냅니다.
                이러한 에러 키워드들은 데이터베이스의 안정성, 성능, 데이터 무결성에 영향을 미칠 수 있으므로 주의 깊게 모니터링해야 합니다. 
                특히 "Fatal error", "Out of memory", "Disk full"과 같은 심각한 에러는 즉각적인 조치가 필요할 수 있습니다. 
                정기적으로 로그를 검토하고 이러한 키워드가 발견되면 신속하게 대응하는 것이 중요합니다
                </context>
                ''' + '\n'.join(results)
    
    llm_response = interact_with_general_llm(prompt)
    
    st.markdown(llm_response)
        
    
def chat_with_claude(user_message, tool_config):
    client = boto3.client("bedrock-runtime")
    model_Id = "anthropic.claude-3-sonnet-20240229-v1:0"

    #Query Knowledge Base
    kb_id = "VHVECVPDFE"  # Replace with your actual Knowledge Base ID
    kb_results = query_knowledge_base(kb_id, user_message)

    # Prepare context from Knowledge Base results
    kb_context = ""
    for result in kb_results:
        if "content" in result and isinstance(result["content"], dict):
            if "text" in result["content"]:
                kb_context += result["content"]["text"] + "\n\n"
        elif isinstance(result, dict) and "text" in result:
            kb_context += result["text"] + "\n\n"

    user_message += kb_context
    messages = [{"role": "user", "content": [{"text": user_message}]}]

    tool_functions = {
        "get_database_info": get_database_info,
        "execute_sql": execute_sql,
        "execute_sql_multiDatabase": execute_sql_multiDatabase,
        "retrieve_perf_metric_multiDatabase": retrieve_perf_metric_multiDatabase,
        "query_athena_table": query_athena_table,
        "explain_plan_query": explain_plan_query,
        "analyze_performance": analyze_performance,
        "get_top_sql_data": get_top_sql_data,
        "analyze_innodb_status": analyze_innodb_status,
        "get_event_memory_status": get_event_memory_status,
        "get_buffer_hit_ratio": get_buffer_hit_ratio,
        "download_and_upload_slow_query_logs": download_and_upload_slow_query_logs,
        "analyze_aurora_mysql_error_logs": analyze_aurora_mysql_error_logs,
    }

    def call_tool(tool, messages):
        tool_name = tool["name"]
        tool_input = tool["input"]
        
        if tool_name == "get_price":
            result = tool_functions[tool_name](tool_input["fruit"])
        elif tool_name in ["get_database_info", "compare_database_info", "analyze_innodb_status", "get_event_memory_status", "get_buffer_hit_ratio"]:
            result = tool_functions[tool_name](tool_input["keyword"])
        elif tool_name in ["execute_sql", "query_athena_table", "check_cpu_overload"]:
            result = tool_functions[tool_name](tool_input["secret_name"], tool_input["user_query"])
        elif tool_name in ["execute_sql_multiDatabase", "explain_plan_query"]:
            result = tool_functions[tool_name](tool_input["keyword"], tool_input["user_query"])
        elif tool_name =="retrieve_perf_metric_multiDatabase":
            result = tool_functions[tool_name](tool_input["keyword"], tool_input["start_time"], tool_input["end_time"],tool_input["user_query"])
        elif tool_name in ["analyze_performance", "download_and_upload_slow_query_logs", "analyze_aurora_mysql_error_logs"]:
            result = tool_functions[tool_name](tool_input["keyword"], tool_input["start_time"], tool_input["end_time"])
        elif tool_name == "get_top_sql_data":
            result = tool_functions[tool_name](tool_input["keyword"], tool_input["start_time"], tool_input["end_time"], tool_input["limit"])
        else:
            raise ValueError(f"Unknown tool: {tool_name}")
        
        content = {"result": result}
        tool_result = {
            "toolUseId": tool["toolUseId"],
            "content": [{"json": content}],
        }
        tool_result_message = {
            "role": "user",
            "content": [{"toolResult": tool_result}],
        }
        
        messages.append(tool_result_message)
        
        response = client.converse(
            modelId=model_Id, messages=messages, toolConfig=tool_config
        )
        return response["output"]["message"]

    response = client.converse(
        modelId=model_Id, messages=messages, toolConfig=tool_config
    )

    output_message = response["output"]["message"]
    messages.append(output_message)
    stop_reason = response["stopReason"]

    if stop_reason == "tool_use":
        tool_requests = output_message["content"]
        for tool_request in tool_requests:
            if "toolUse" in tool_request:
                output_message = call_tool(tool_request["toolUse"], messages)
        return output_message["content"][0]["text"]
    else:
        # Handle general questions without tool use
        claude_input = json.dumps(
            {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 4096,
                "messages": [
                    {"role": "user", "content": [{"type": "text", "text": user_message}]}
                ],
                "temperature": 0.5,
                "top_k": 250,
                "top_p": 1,
                "stop_sequences": [],
            }
        )

        response = client.invoke_model(modelId=model_Id, body=claude_input)
        response_body = json.loads(response.get("body").read())

        try:
            message = response_body.get("content", [])
            result = message[0]["text"]
        except (KeyError, IndexError):
            result = "I'm sorry, I couldn't generate a response."
        
        st.write(result)
        return result

tool_config = {
    "tools": [
        {
            "toolSpec": {
                "name": "get_price",
                "description": "Get the price with given parameter fruit",
                "inputSchema": {
                    "json": {
                        "type": "object",
                        "properties": {
                            "fruit": {
                                "type": "string",
                                "description": "input parameter is fruit",
                            }
                        },
                        "required": ["fruit"],
                    }
                },
            }
        },
        {
            "toolSpec": {
                "name": "get_database_info",
                "description": "Get the database schema information such as table_name, column name and so on ,with the given secret name and this function is invoked only when you are asked about get schema information",
                "inputSchema": {
                    "json": {
                        "type": "object",
                        "properties": {
                            "secret_name": {
                                "type": "string",
                                "description": "The secret name for database connection",
                            }
                        },
                        "required": ["secret_name"],
                    }
                },
            }
        },
        {
            "toolSpec": {
                "name": "execute_sql",
                "description": '''여러개의 SQL을 실행하기도 하며, 특정 테이블의 조인이나, Group by같은 형태의 일반 SQL 요청을 처리함 
                                  각 디비별로 Show Global Status같은 명령문이나, performance_schema의 정보를 이용해 실행중인 쿼리를 보기도 하고, 
                                  테이블이나 인덱스 상태를 조회하고, 메모리 사용량을 확인할때도 사용합니다
                                  각 디비별로 디비 상태를 보고 싶다고 요청하건, 각 디비별로 테이블,인덱스 상태를 확인해달라고 하거나 
                                  각 디비별로 메모리 사용현황을 보고 싶다고 할때 사용합니다.''',
                "inputSchema": {
                    "json": {
                        "type": "object",
                        "properties": {
                            "secret_name": {
                                "type": "string",
                                "description": "The secret name for database connection. Cluster, Database or DB may be same meaning as secret name",
                            },
                            "user_query": {
                                "type": "string",
                                "description": "The SQL query to execute",
                            },
                        },
                        "required": ["keyword", "user_query"],
                    }
                },
            }
        },
        {
            "toolSpec": {
                "name": "execute_sql_multiDatabase",
                "description": '''여러개의 Aurora 디비에 대해 자연어로 요청을 받으면,SQL로 작성해서 각 디비들에 실행하게 해주는 함수: 
                                  여러개의 SQL을 실행하기도 하며, 특정 테이블의 조인이나, Group by같은 형태의 일반 SQL 요청을 처리함 
                                  각 디비별로 Show Global Status같은 명령문이나, performance_schema의 정보를 이용해 실행중인 쿼리를 보기도 하고, 
                                  테이블이나 인덱스 상태를 조회하고, 메모리 사용량을 확인할때도 사용합니다
                                  각 디비별로 디비 상태를 보고 싶다고 요청하건, 각 디비별로 테이블,인덱스 상태를 확인해달라고 하거나 
                                  각 디비별로 메모리 사용현황을 보고 싶다고 할때 사용합니다. ''',
                "inputSchema": {
                    "json": {
                        "type": "object",
                        "properties": {
                            "keyword": {
                                "type": "string",
                                "description": "Keyword to identify multiple databases",
                            },
                            "user_query": {
                                "type": "string",
                                "description": "The SQL query to execute",
                            },
                        },
                        "required": ["keyword", "user_query"],
                    }
                },
            }
        },
        {
            "toolSpec": {
                "name": "compare_database_info",
                "description": "Compare database information for the databases identified by the keyword",
                "inputSchema": {
                    "json": {
                        "type": "object",
                        "properties": {
                            "keyword": {
                                "type": "string",
                                "description": "Keyword to identify multiple databases",
                            }
                        },
                        "required": ["keyword"],
                    }
                },
            }
        },
        {
            "toolSpec": {
                "name": "retrieve_perf_metric_multiDatabase",
                "description": "데이터베이스(DB)의성능정보를 알려줘할때 사용, 특히 여러개의 디비의 cpu,latency,HLL외의 다양한 cloudwatch 지표를 보여준다. 예) gamedb로 시작하는 모든 디비의 클라우드워치 성능정보를 알려줘 ",
                "inputSchema": {
                    "json": {
                        "type": "object",
                        "properties": {
                            "keyword": {
                                "type": "string",
                                "description": "Keyword to identify multiple databases",
                            },
                            "start_time": {
                                "type": "string",
                                "description": "Start time for the metrics retrieval ,minimum value start with 01 for example 2024-08-24 00:00:01",
                            },
                            "end_time": {
                                "type": "string",
                                "description": "End time for the metrics retrieval ,minimum value start with 01 for example 2024-08-24 00:00:01",
                            },
                            "user_query": {
                                "type": "string",
                                "description": "성능정보에 대한 요청사항",
                            },
                        },
                        "required": ["keyword", "start_time", "end_time", "user_query"],
                    }
                },
            }
        },
        {
            "toolSpec": {
                "name": "query_athena_table",
                "description": "Execute a query on an Athena table",
                "inputSchema": {
                    "json": {
                        "type": "object",
                        "properties": {
                            "database_name": {
                                "type": "string",
                                "description": "The name of the Athena database",
                            },
                            "user_query": {
                                "type": "string",
                                "description": "The query to execute",
                            },
                        },
                        "required": ["database_name", "user_query"],
                    }
                },
            }
        },
        {
            "toolSpec": {
                "name": "check_cpu_overload",
                "description": "Check CPU overload for a database",
                "inputSchema": {
                    "json": {
                        "type": "object",
                        "properties": {
                            "database_name": {
                                "type": "string",
                                "description": "The name of the database",
                            },
                            "user_query": {
                                "type": "string",
                                "description": "The query to execute for checking CPU overload",
                            },
                        },
                        "required": ["database_name", "user_query"],
                    }
                },
            }
        },
        {
            "toolSpec": {
                "name": "explain_plan_query",
                "description": "Get the execution plan for a SQL query when you are asked about analyzing execution plan of query",
                "inputSchema": {
                    "json": {
                        "type": "object",
                        "properties": {
                            "keyword": {
                                "type": "string",
                                "description": "Keyword to identify the database",
                            },
                            "user_query": {
                                "type": "string",
                                "description": "The SQL query to get the execution plan for",
                            },
                        },
                        "required": ["keyword", "user_query"],
                    }
                },
            }
        },
        {
            "toolSpec": {
                "name": "analyze_performance",
                "description": "데이터베이스(DB)의성능분석을 요청할때, 특히 여러개의 오로라 디비의 DB load 같은 지표를 그래프로 보여주고, 그래프의 raw data를 분석해서 성능분석에 대한 의견을 제시한다.",
                "inputSchema": {
                    "json": {
                        "type": "object",
                        "properties": {
                            "keyword": {
                                "type": "string",
                                "description": "Keyword to identify multiple databases",
                            },
                            "start_time": {
                                "type": "string",
                                "description": "Start time for the metrics retrieval ,minimum value start with 01 for example 2024-08-24 00:00:01",
                            },
                            "end_time": {
                                "type": "string",
                                "description": "End time for the metrics retrieval ,minimum value start with 01 for example 2024-08-24 00:00:01",
                            }
                        },
                        "required": ["keyword", "start_time", "end_time"],
                    }
                },
            }
        },
        {
            "toolSpec": {
                "name": "get_top_sql_data",
                "description": "데이터베이스(DB)의 TOP 쿼리를 뽑아달라고 할때, 특히 여러개의 오로라 디비의 부하를 일으킨 문제쿼리들을 보여주고 분석할때 이 함수를 호출한다.",
                "inputSchema": {
                    "json": {
                        "type": "object",
                        "properties": {
                            "keyword": {                                
                                "type": "string",
                                "description": "Keyword to identify multiple databases 예)gamedb로 시작하는 모든 디비 또는 gamedb1-cluster,gamedb2-cluster 와 같이 지정 ",
                            },
                            "start_time": {
                                "type": "string",
                                "description": "Start time for the metrics retrieval ",
                            },
                            "end_time": {
                                "type": "string",
                                "description": "End time for the metrics retrieval ",
                            },
                            "limit": {
                                "type": "string",
                                "description": "top 쿼리를 보여줄 갯수를 말하며 숫자 10,12..와 같이 말하거나 열개,스무개와 같은 한글도 받아서 숫자로 처리한다. 없으면 20 ",
                            }
                        },
                        "required": ["keyword", "start_time", "end_time","limit"],
                    }
                },
            }
        },
        {
            "toolSpec": {
                "name": "analyze_innodb_status",
                "description": "innodb status를 확인하고 분석할때 사용합니다. 보통 각 디비의 상태를 분석해줘. 또는 이노디비상태를 분석해줘 할때 이 함수",
                "inputSchema": {
                    "json": {
                        "type": "object",
                        "properties": {
                            "keyword": {
                                "type": "string",
                                "description": "Aurora cluster의 이름이면서 Secret 정보에도 등록된 이름입니다. ",
                            }
                        },
                        "required": ["keyword"],
                    }
                },
            }
        },
        {
            "toolSpec": {
                "name": "get_event_memory_status",
                "description": "각 오로라디비내부의 event 별 메모리 사용량을 확인할때 사용한다. 보통 각 디비안의 이벤트별 메모리 사용량을 알려줘 할때 사용 ",
                "inputSchema": {
                    "json": {
                        "type": "object",
                        "properties": {
                            "keyword": {
                                "type": "string",
                                "description": "Aurora cluster의 이름이면서 Secret 정보에도 등록된 이름입니다. ",
                            }
                        },
                        "required": ["keyword"],
                    }
                },
            }
        },
        {
            "toolSpec": {
                "name": "get_buffer_hit_ratio",
                "description": "각 오로라디비의 버퍼캐시히트율(또는 버퍼히트율 또는 Buffer hit ratio) 을 알려달라고 할때 이 함수를 사용 ",
                "inputSchema": {
                    "json": {
                        "type": "object",
                        "properties": {
                            "keyword": {
                                "type": "string",
                                "description": "Aurora cluster의 이름이면서 Secret 정보에도 등록된 이름입니다. ",
                            }
                        },
                        "required": ["keyword"],
                    }
                },
            }
        },
        {
            "toolSpec": {
                "name": "download_and_upload_slow_query_logs",
                "description": "각 오로라디비의 slow query 로그를 분석해달라고 할때 사용: 예시) 슬로우 쿼리로그 분석해줘, 슬로우 쿼리를 보여줘, 슬로워쿼리! ",
                "inputSchema": {
                    "json": {
                        "type": "object",
                        "properties": {
                            "keyword": {
                                "type": "string",
                                "description": "Keyword to identify multiple databases 예)gamedb로 시작하는 모든 디비 또는 gamedb1-cluster,gamedb2-cluster 와 같이 지정 ",
                            },
                            "start_time": {
                                "type": "string",
                                "description": "Start time for the metrics retrieval ",
                            },
                            "end_time": {
                                "type": "string",
                                "description": "End time for the metrics retrieval ",
                            }
                        },
                        "required": ["keyword", "start_time", "end_time"],
                    }
                },
            }
        },
        {
            "toolSpec": {
                "name": "analyze_aurora_mysql_error_logs",
                "description": "각 오로라디비의 Error 로그를 분석해달라고 할때 사용: 예시) 에러로그 분석해줘, 에러로그를 보여줘, 에러로그! ",
                "inputSchema": {
                    "json": {
                        "type": "object",
                        "properties": {
                            "keyword": {
                                "type": "string",
                                "description": "Keyword to identify multiple databases 예)gamedb로 시작하는 모든 디비 또는 gamedb1-cluster,gamedb2-cluster 와 같이 지정 ",
                            },
                            "start_time": {
                                "type": "string",
                                "description": "Start time for the metrics retrieval ",
                            },
                            "end_time": {
                                "type": "string",
                                "description": "End time for the metrics retrieval ",
                            }
                        },
                        "required": ["keyword", "start_time", "end_time"],
                    }
                },
            }
        },
        
        
    ]
}


def main():
    # 날짜 선택
    start_date = st.sidebar.date_input("Start Date", datetime.now().date() - timedelta(days=7))
    end_date = st.sidebar.date_input("End Date", datetime.now().date())
    
    # 시간 선택
    start_time = st.sidebar.time_input("Start Time", datetime.min.time())
    end_time = st.sidebar.time_input("End Time", datetime.max.time())
    
    selected_clusters = st.session_state.get('selected_clusters', [])
    
    #print('selected_clusters2: ', selected_clusters2)
    
    start_datetime = datetime.combine(start_date, start_time)
    end_datetime = datetime.combine(end_date, end_time)
    # 분석 버튼
    if st.sidebar.button("Analyze Performance"):
        analyze_performance(selected_clusters, start_datetime, end_datetime)
        
    if st.sidebar.button("Get Top Queries"):
        get_top_sql_data(selected_clusters, start_datetime, end_datetime,20)

    # 채팅 입력
    prompt = st.chat_input("What would you like to ask about Aurora MySQL management?")

    # 사이드바 하단에 파일 업로더 배치
    st.sidebar.markdown("---")  # 구분선 추가
    st.sidebar.subheader("SQL File Upload")
    uploaded_file = st.sidebar.file_uploader("Choose a SQL file", type=["sql"])

    query = ""
    displayed_query = ""
    if uploaded_file is not None:
        query = str(uploaded_file.read(), "utf-8")
        st.sidebar.success("File successfully uploaded!")
        # 메인 영역에 쿼리 표시 영역 생성
        query_area = st.container()
        with query_area:
            displayed_query = st.text_area("SQL Query", value=query, height=200)
        #
        print("uploaded query:-----  ", query)

    if prompt is not None:
        now = datetime.now()

        print("현재시간:", now)  

        end_time = now.strftime("%Y-%m-%d %H:%M")

        print("if prompt:")
        if displayed_query:
            combined_prompt = f"{prompt}\n\nSQL Query:\n{displayed_query}"
        else:
            combined_prompt = prompt
            
        print("prompt:-----", combined_prompt)
            
        st.session_state.messages.append({"role": "user", "content": combined_prompt})
        with st.chat_message("user"):
            st.markdown(combined_prompt)

        combined_prompt += f"(참고사항: 현재시간은 {end_time}입니다. start_time은 {start_datetime}, end_time은 {end_datetime} 입니다.시간을 물어보는게 아니면 대답할때 이 부분은 건너뜁니다.)\n"
        
        for message in st.session_state.messages:
            combined_prompt += message['content'] + ' '
        
        print("combined_prompt: ",combined_prompt)
        chat_with_claude(combined_prompt, tool_config)
        

if __name__ == "__main__":
    if runtime.exists():
        main()
    else:
        sys.argv = ["streamlit", "run", sys.argv[0]]
        sys.exit(stcli.main())
