# UBI-LTR Pipeline - AWS CDK Infrastructure

This CDK project provisions the complete AWS infrastructure for the User Behavior Insights (UBI) to Learning to Rank (LTR) pipeline. (This is a demo sample for reference purposes.)

## Architecture Overview

```
                         +------------------+
                         |   Web Browser    |
                         +--------+---------+
                                  |
                         +--------v---------+
                         |   CloudFront     |
                         | (Static Assets)  |
                         +--------+---------+
                                  |
              +-------------------+-------------------+
              |                                       |
    +---------v---------+                   +---------v---------+
    |   API Gateway     |                   |   React Frontend  |
    |   (REST API)      |                   |   (Search UI)     |
    +---------+---------+                   +-------------------+
              |
    +---------v---------+
    |   Lambda          |
    |   (FastAPI)       |
    +---------+---------+
              |
    +---------v---------+      +-----------------------+
    |   OSI Pipeline    | <--> |   S3 Bucket          |
    |   (Unified)       |      |   (Data Archival)    |
    +----+--------+-----+      +-----------------------+
         |        |
    +----v----+   +----v----+
    |ubi_events|  |ubi_queries|
    +---------+   +---------+
              \     /
          +----v---v----+
          |  OpenSearch |
          |   Domain    |
          +------+------+
                 |
          +------v------+      +------------------+
          |Step Functions| --> |   Bedrock        |
          |(LTR Pipeline)|     |   (Claude 4.5)   |
          +-------------+      +------------------+
```

## Quick Start

### One-Command Deployment

```bash
# Deploy with defaults (dev environment, us-east-1)
./deploy.sh

# Deploy with custom settings
./deploy.sh -e prod -r us-west-2

# Deploy without confirmation
./deploy.sh -y
```

The deployment script automatically:
1. Checks prerequisites (AWS CLI, Node.js 18+, npm)
2. Installs CDK and frontend dependencies
3. Builds the React frontend application
4. Bootstraps CDK if needed
5. Deploys all 7 stacks (~30-40 minutes)
6. Displays deployment outputs (URLs, credentials)

### One-Command Destruction

```bash
# Destroy all resources (requires "DELETE" confirmation)
./destroy.sh

# Destroy without confirmation (dangerous!)
./destroy.sh -y

# Only cleanup orphaned resources
./destroy.sh --cleanup-only
```

## CDK Stacks

| Stack | Description | Est. Time |
|-------|-------------|-----------|
| **StorageStack** | S3 buckets for UBI data and LTR models | ~1 min |
| **IamStack** | IAM roles for Lambda, Step Functions, OSI | ~1 min |
| **OpenSearchStack** | OpenSearch domain with UBI configuration | ~25 min |
| **OsiStack** | Unified OSI pipeline with type-based routing | ~3 min |
| **ProcessingStack** | Step Functions LTR training pipeline | ~2 min |
| **SetupStack** | OpenSearch index and mapping initialization | ~2 min |
| **WebappStack** | API Gateway + Lambda + CloudFront | ~5 min |

### Stack Details

#### 1. StorageStack (`storage-stack.ts`)
- **Data Bucket**: S3 bucket for UBI exports, judgments, and LTR training data
- **DLQ Bucket**: Dead-letter queue for failed OSI ingestion events
- Lifecycle policies for cost optimization

#### 2. IamStack (`iam-stack.ts`)
- **OSI Pipeline Role**: Permissions for OpenSearch Ingestion
- **Lambda Execution Role**: Permissions for Lambda functions (OpenSearch, Bedrock, S3)
- **Step Functions Role**: Permissions for state machine orchestration

#### 3. OpenSearchStack (`opensearch-stack.ts`)
- OpenSearch Service domain (t3.small.search for demo)
- Fine-grained access control with Secrets Manager
- Encryption at rest and in transit
- CloudWatch logging enabled

#### 4. OsiStack (`osi-stack.ts`)
- Unified OSI pipeline with routing by `type` field
- Routes `type: "event"` → `ubi_events` index
- Routes `type: "query"` → `ubi_queries` index
- Single pipeline is more cost-effective than separate pipelines

#### 5. ProcessingStack (`processing-stack.ts`)
- **Extract UBI Data Lambda**: Extracts queries and events from OpenSearch
- **Generate Judgments Lambda**: Uses Claude Sonnet 4.5 for relevance judgments
- **Prepare LTR Data Lambda**: Formats data for LTR training
- **Train LTR Model Lambda**: Creates and uploads LTR model
- **Step Functions State Machine**: Orchestrates the complete pipeline

#### 6. SetupStack (`setup-stack.ts`)
- Custom resource for automatic index creation
- Creates `ubi_queries` and `ubi_events` indexes with proper mappings
- Creates `ecommerce_products` sample data index

#### 7. WebappStack (`webapp-stack.ts`)
- **Lambda (FastAPI)**: Search API with UBI event logging
- **API Gateway**: REST API with CORS support
- **CloudFront**: CDN for React frontend and API
- **S3 Bucket**: Static website hosting

## Configuration Options

| Context Variable | Default | Description |
|-----------------|---------|-------------|
| `envPrefix` | `dev` | Environment prefix for resource naming |
| `region` | `us-east-1` | AWS region for deployment |
| `opensearchVersion` | `3.3` | OpenSearch version |
| `instanceType` | `t3.small.search` | OpenSearch instance type |
| `instanceCount` | `1` | Number of data nodes |
| `ebsVolumeSize` | `20` | EBS volume size in GB |
| `dedicatedMaster` | `false` | Enable dedicated master nodes |
| `multiAz` | `false` | Enable multi-AZ deployment |
| `bedrockModelId` | `us.anthropic.claude-sonnet-4-5-20250929-v1:0` | Bedrock model ID |
| `enableSchedule` | `false` | Enable scheduled pipeline execution |
| `scheduleExpression` | `rate(1 day)` | Schedule expression |

## Manual CDK Commands

If you prefer to run CDK commands manually instead of using scripts:

```bash
# Install dependencies
npm install

# Build TypeScript
npm run build

# Review changes
cdk diff

# Deploy all stacks
cdk deploy --all -c envPrefix=dev -c region=us-east-1

# Deploy with approval skip
cdk deploy --all --require-approval never

# Destroy all stacks
cdk destroy --all
```

## Cost Estimation

| Resource | Configuration | Est. Monthly Cost |
|----------|--------------|-------------------|
| OpenSearch | t3.small.search, 20GB EBS | ~$30 |
| OSI Pipeline | 1 OCU min/max | ~$15 |
| Lambda | Occasional execution | ~$1 |
| Step Functions | Occasional execution | ~$1 |
| S3 | Standard, <1GB | ~$1 |
| CloudFront | Standard distribution | ~$1 |
| API Gateway | REST API | ~$1 |
| Bedrock (Claude) | Per LTR pipeline run | ~$5-50 |
| **Total** | | **~$55-100/month** |

> **Note:** Costs vary based on usage. The Bedrock cost depends on LTR pipeline execution frequency and data volume.

## Production Recommendations

1. **OpenSearch**:
   - Use `r6g.large.search` or larger instances
   - Enable Multi-AZ deployment
   - Configure dedicated master nodes
   - Increase EBS volume size

2. **Security**:
   - Deploy in private VPC subnets
   - Use VPC endpoints for AWS services
   - Enable encryption at rest with KMS CMK
   - Restrict access policies

3. **Monitoring**:
   - Enable CloudWatch alarms
   - Set up error notifications
   - Monitor Bedrock usage and costs

4. **Scaling**:
   - Adjust OSI pipeline min/max units
   - Configure Lambda concurrency
   - Use reserved capacity for Bedrock

## Troubleshooting

### Deployment Issues

**Problem:** `CDK bootstrap failed`
```bash
# Solution: Bootstrap manually with explicit account/region
aws sts get-caller-identity  # Verify credentials
cdk bootstrap aws://ACCOUNT_ID/REGION
```

**Problem:** `Resource already exists` error
```bash
# Solution: Delete the orphaned resource and redeploy
./destroy.sh --cleanup-only
./deploy.sh -y
```

**Problem:** `OpenSearch domain creation timeout`
- OpenSearch domain creation takes 20-30 minutes. This is normal.
- Check CloudFormation console for progress.

### Runtime Issues

**Problem:** `403 Forbidden` when accessing OpenSearch
- Verify IAM role permissions
- Check OpenSearch access policy
- Verify Secrets Manager credentials

**Problem:** `OSI pipeline not receiving data`
```bash
# Check OSI pipeline status
aws osis get-pipeline --pipeline-name dev-ubi-pipeline --region us-east-1

# Check CloudWatch logs for OSI
aws logs tail /aws/vendedlogs/osis-dev-ubi-pipeline --follow
```

**Problem:** `Bedrock model access denied`
- Request access to Claude Sonnet 4.5 in AWS Bedrock console
- Verify the region supports the model ID

### Cleanup Issues

**Problem:** `Stack deletion failed`
```bash
# Force cleanup orphaned resources
./destroy.sh --cleanup-only -y

# Check for remaining resources
aws cloudformation list-stacks --stack-status-filter DELETE_FAILED
```

## References

- [OpenSearch UBI Documentation](https://opensearch.org/docs/latest/search-plugins/ubi/)
- [UBI AWS Tutorial](https://docs.opensearch.org/latest/search-plugins/ubi/ubi-aws-managed-services-tutorial/)
- [OpenSearch LTR Plugin](https://opensearch.org/docs/latest/search-plugins/ltr/)
- [AWS CDK Documentation](https://docs.aws.amazon.com/cdk/)
- [Amazon Bedrock Claude](https://docs.aws.amazon.com/bedrock/latest/userguide/model-parameters-anthropic-claude-messages.html)
