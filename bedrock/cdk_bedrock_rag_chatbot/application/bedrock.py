import os, sys, boto3

region_name = boto3.Session().region_name
ssm = boto3.client('ssm', region_name=region_name)
bedrock_agent_runtime_client = boto3.client("bedrock-agent-runtime", region_name="us-west-2")

def get_knowledge_base_id(key, enc=False):
    if enc: WithDecryption = True
    else: WithDecryption = False
    response = ssm.get_parameters(
        Names=[key,],
        WithDecryption=WithDecryption
    )
    return response['Parameters'][0]['Value']

MODEL_ARN = "anthropic.claude-3-sonnet-20240229-v1:0"
KNOWLEDGE_BASE_ID = get_knowledge_base_id(key="/RAGChatBot/KNOWLEDGE_BASE_ID", enc=False)

def query(question):
    response = bedrock_agent_runtime_client.retrieve_and_generate(
        input={
            'text': question
        },
        retrieveAndGenerateConfiguration={
            'type': 'KNOWLEDGE_BASE',
            'knowledgeBaseConfiguration': {
                'knowledgeBaseId': KNOWLEDGE_BASE_ID,
                'modelArn': MODEL_ARN,
                'retrievalConfiguration': {
                    'vectorSearchConfiguration': {
                        'overrideSearchType': 'HYBRID'
                    }
                }
            }
        },
    )
    return response['output']['text']
