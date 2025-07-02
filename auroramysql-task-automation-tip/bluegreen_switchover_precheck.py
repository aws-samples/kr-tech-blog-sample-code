import boto3
import json
from datetime import datetime, timezone, timedelta
import getpass
import mysql.connector
from mysql.connector import Error

def get_connection_info():
    print("Please enter your Aurora MySQL cluster connection information")
    host = input("Enter the blue cluster Endpoint: ")
    region = input("Enter the region: ")
    user = input("Enter the username: ")
    password = getpass.getpass("Enter the password: ")
    return host, user, region, password

def create_connection(host, user, password):
    connection = None
    try:
        connection = mysql.connector.connect(
            host=host,
            user=user,
            password=password
        )
        if connection.is_connected():
            print("Successfully connected to the database.")
        return connection
    except Error as e:
        print(f"Error connecting to the database: {e}")
        return None
    
def create_boto3_client(service, region):
    return boto3.client(service, region_name=region)

def get_cluster_arn_from_endpoint(cluster_endpoint, rds_client):
    try:
        response = rds_client.describe_db_clusters()
        for cluster in response['DBClusters']:
            if cluster['Endpoint'] == cluster_endpoint:
                return cluster['DBClusterArn']
        print(f"No cluster found with endpoint: {cluster_endpoint}")
        return None
    except Exception as e:
        print(f"An error occurred: {str(e)}")
        return None

def find_green_cluster_arn(cluster_arn, rds_client):
    try:
        response = rds_client.describe_blue_green_deployments(
            Filters = [
                {
                    'Name': 'source',
                    'Values': [cluster_arn]
                }
            ]
        )
        if 'BlueGreenDeployments' in response and len(response['BlueGreenDeployments']) > 0:
            deployment = response['BlueGreenDeployments'][0]
            return deployment['Target'], deployment['BlueGreenDeploymentName']
        else:
            print(f"No BlueGreenDeployment found for source cluster: {cluster_arn}")
            return None, None
    except Exception as e:
        print(f"Error finding BlueGreenDeployment: {e}")
        return None, None

# 다른 함수들도 비슷한 방식으로 rds_client를 인자로 받도록 수정합니다.

def check_aurora_instances_status(blue_cluster_arn, green_cluster_arn, rds_client):
    
    def check_cluster_instances(cluster_arn):
        response = rds_client.describe_db_clusters(DBClusterIdentifier=cluster_arn)
        instances = response['DBClusters'][0]['DBClusterMembers']
        
        cluster_id = response['DBClusters'][0]['DBClusterIdentifier']
        
        all_available = True
        
        for instance in instances:
            instance_id = instance['DBInstanceIdentifier']
            instance_response = rds_client.describe_db_instances(DBInstanceIdentifier=instance_id)
            status = instance_response['DBInstances'][0]['DBInstanceStatus']
            
            print(f"> Cluster Name: {cluster_id}, Instance: {instance_id}, Status: {status}")
            
            if status != 'available':
                all_available = False
        
        return all_available
    
    blue_available = check_cluster_instances(blue_cluster_arn)
    green_available = check_cluster_instances(green_cluster_arn)
    
    return blue_available and green_available

def check_running_ddl(connection):
    cursor = None
    try:
        cursor = connection.cursor(dictionary=True)
        
        cursor.execute("SHOW PROCESSLIST")
        processes = cursor.fetchall()
            
        ddl_operations = ['CREATE', 'ALTER', 'DROP', 'TRUNCATE', 'RENAME']
        running_ddl = [process for process in processes if process['Info'] and any(op in process['Info'].upper() for op in ddl_operations)]
            
        if running_ddl:
            print("> Running DDL detected. Check failed.")
            for process in running_ddl:
                print(f"> ID: {process['Id']}, Command: {process['Command']}, Time: {process['Time']}, State: {process['State']}, Info: {process['Info']}")
        else:
            print("> Not running DDL. Check passed")
                    
    except Error as e:
        print(f"> Database Connection Error: {e}")
        
    except Exception as e:
        print(f"> An error occurred: {e}")
        return False
    finally:
        if cursor:
            cursor.close()

def check_binlog_replica_lag(cluster_arn, cloudwatch_client):
    current_time = datetime.utcnow()
    start_time = (current_time - timedelta(minutes=5)).strftime('%Y-%m-%dT%H:%M:%SZ')
    end_time = current_time.strftime('%Y-%m-%dT%H:%M:%SZ')
    
    cluster_identifier = cluster_arn.split(':')[-1]
        
    try:
        response = cloudwatch_client.get_metric_statistics(
        Namespace='AWS/RDS',
        MetricName='AuroraBinlogReplicaLag',
        Dimensions=[
            {
                'Name': 'DBClusterIdentifier',
                'Value': cluster_identifier
            }
        ],
        StartTime=start_time,
        EndTime=end_time,
        Period=60,
        Statistics=['Average']
    )
        if 'Datapoints' in response and len(response['Datapoints']) > 0:
            lag = response['Datapoints'][0]['Average']
            
            if lag==0:
                print("> Replica lag between Blue and Green cluster is 0. Check passed")
            else:
                print(f"> Green Cluster lag: {lag}")
                return lag
        else:
            print("> Failed to retrieve lag information for the Green cluster. Check failed")
            return None
    
    except Exception as e:
        print(f"> Error checking Binlog Replica Lag: {e}. Check failed")
        return None

def check_external_replica(connection):
    try:
        cursor = connection.cursor(dictionary=True)
        sql = """
        SELECT * FROM mysql.rds_replication_status 
        WHERE action = 'set master' 
        ORDER BY action_timestamp DESC 
        LIMIT 1;
        """
        cursor.execute(sql)
        result = cursor.fetchall()
        
        if result:
            print("External Replica detected. Check failed.")
            for row in result:
                print(f"> Action: {row['action']}, Timestamp: {row['action_timestamp']}")
            return False
        else:
            print("> No External Replica detected. Check passed.")
            return True
    except Error as e:
        print(f"> Error checking External Replica: {e}")
        return False
    finally:
        if cursor:
            cursor.close()   

def check_rollback_segment_hll(connection):
    cursor = None
    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute("SELECT COUNT FROM information_schema.INNODB_METRICS WHERE NAME = 'trx_rseg_history_len'")
        result = cursor.fetchone()
        
        if result:
            hll = result['COUNT']
            print(f"> current Rollback Segment HLL: {hll}.", end=" ")
            
            if hll > 1000000:
                print(f"Rollback Segment HLL is greater than 1,000,000. Check failed. HLL Count: {hll}")
            else:
                print("Rollback Segment HLL Check passed.")
        else:
            print("> Unable to retrieve Rollback Segment HLL.")
            return "checked fail", None
        
    except Exception as e:
        print(f"> An error occurred: {e}")
        return None
    
    finally:
        if cursor:
            cursor.close()
                                    
def main():
    host, user, region, password = get_connection_info()
    connection = create_connection(host, user, password)

    
    # boto3 클라이언트 초기화
    rds_client = create_boto3_client('rds', region)
    cloudwatch_client = create_boto3_client('cloudwatch', region)
    
    blue_cluster_arn = get_cluster_arn_from_endpoint(host, rds_client)
    green_cluster_arn, blue_green_deployment_name = find_green_cluster_arn(blue_cluster_arn, rds_client)
    
    if connection:
            print('''
Checklist for successful switchover
====================================''')
            print(f"Blue Cluster ARN: {blue_cluster_arn}")
            print(f"Green Cluster ARN: {green_cluster_arn}")
            print(f"Blue Green Deployment Name: {blue_green_deployment_name}")
            print()

            try:
                instance_status_check = check_aurora_instances_status(blue_cluster_arn, green_cluster_arn, rds_client)
                ddl_check = check_running_ddl(connection)
                replica_lag_check = check_binlog_replica_lag(green_cluster_arn, cloudwatch_client)
                external_replica_check = check_external_replica(connection)
                hll_check = check_rollback_segment_hll(connection)
            finally:
                connection.close()
    else:
        print("Failed to establish database connection.")

if __name__ == "__main__":
    main()
