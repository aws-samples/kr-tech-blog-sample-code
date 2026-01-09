#!/bin/bash
#
# UBI-LTR Pipeline - Destruction Script
# Safely destroy all AWS infrastructure and cleanup orphaned resources
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Default values
ENV_PREFIX="dev"
REGION="us-east-1"
SKIP_CONFIRM=false
CLEANUP_ONLY=false
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# AWS CLI common options to disable pager
export AWS_PAGER=""

# Functions
print_banner() {
    echo -e "${RED}"
    echo "╔══════════════════════════════════════════════════════════════════╗"
    echo "║           UBI-LTR Pipeline - AWS Resource Destruction            ║"
    echo "╚══════════════════════════════════════════════════════════════════╝"
    echo -e "${NC}"
}

print_step() {
    echo -e "\n${BLUE}▶ $1${NC}"
}

print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠ $1${NC}"
}

print_error() {
    echo -e "${RED}✗ $1${NC}"
}

usage() {
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  -e, --env-prefix PREFIX   Environment prefix (default: dev)"
    echo "  -r, --region REGION       AWS region (default: us-east-1)"
    echo "  -y, --yes                 Skip confirmation prompt"
    echo "  --cleanup-only            Only cleanup orphaned resources (skip CDK destroy)"
    echo "  -h, --help                Show this help message"
    echo ""
    echo "Examples:"
    echo "  $0                        # Destroy with defaults (dev, us-east-1)"
    echo "  $0 -e prod -r us-west-2   # Destroy production in us-west-2"
    echo "  $0 -y                     # Destroy without confirmation"
    echo "  $0 --cleanup-only         # Only cleanup orphaned resources"
    exit 0
}

# Stack names follow pattern: ${ENV_PREFIX}-ubi-ltr-{component}
get_stack_names() {
    echo "${ENV_PREFIX}-ubi-ltr-setup"
    echo "${ENV_PREFIX}-ubi-ltr-webapp"
    echo "${ENV_PREFIX}-ubi-ltr-processing"
    echo "${ENV_PREFIX}-ubi-ltr-osi"
    echo "${ENV_PREFIX}-ubi-ltr-opensearch"
    echo "${ENV_PREFIX}-ubi-ltr-iam"
    echo "${ENV_PREFIX}-ubi-ltr-storage"
}

list_stacks() {
    print_step "Stacks to be destroyed:"
    echo ""
    echo "  1. ${ENV_PREFIX}-ubi-ltr-setup"
    echo "  2. ${ENV_PREFIX}-ubi-ltr-webapp"
    echo "  3. ${ENV_PREFIX}-ubi-ltr-processing"
    echo "  4. ${ENV_PREFIX}-ubi-ltr-osi"
    echo "  5. ${ENV_PREFIX}-ubi-ltr-opensearch"
    echo "  6. ${ENV_PREFIX}-ubi-ltr-iam"
    echo "  7. ${ENV_PREFIX}-ubi-ltr-storage"
    echo ""
}

check_existing_stacks() {
    aws cloudformation list-stacks \
        --stack-status-filter CREATE_COMPLETE UPDATE_COMPLETE UPDATE_ROLLBACK_COMPLETE ROLLBACK_COMPLETE \
        --query "StackSummaries[?starts_with(StackName, '${ENV_PREFIX}-ubi-ltr')].StackName" \
        --output text --region "$REGION" 2>/dev/null || echo ""
}

destroy_stacks() {
    print_step "Destroying CDK stacks..."
    cd "$SCRIPT_DIR"

    # Check if any stacks exist
    EXISTING_STACKS=$(check_existing_stacks)

    if [ -z "$EXISTING_STACKS" ]; then
        print_warning "No stacks found for environment: $ENV_PREFIX"
        return 0
    fi

    echo "Found stacks: $EXISTING_STACKS"
    echo ""

    # Try CDK destroy first
    echo "Attempting CDK destroy..."
    npx cdk destroy --all \
        --force \
        --require-approval never \
        -c envPrefix="$ENV_PREFIX" \
        -c region="$REGION" 2>&1 || true

    # Wait a moment for AWS to process
    sleep 5

    # Check if stacks still exist after CDK destroy
    REMAINING_STACKS=$(check_existing_stacks)

    if [ -n "$REMAINING_STACKS" ]; then
        print_warning "Stacks still exist after CDK destroy: $REMAINING_STACKS"
        print_step "Deleting stacks directly via CloudFormation..."
        delete_stacks_directly
    else
        print_success "CDK destroy completed successfully"
    fi
}

delete_stacks_directly() {
    # Delete order (reverse dependency)
    STACK_ORDER=(
        "${ENV_PREFIX}-ubi-ltr-setup"
        "${ENV_PREFIX}-ubi-ltr-webapp"
        "${ENV_PREFIX}-ubi-ltr-processing"
        "${ENV_PREFIX}-ubi-ltr-osi"
        "${ENV_PREFIX}-ubi-ltr-opensearch"
        "${ENV_PREFIX}-ubi-ltr-iam"
        "${ENV_PREFIX}-ubi-ltr-storage"
    )

    for STACK_NAME in "${STACK_ORDER[@]}"; do
        # Check if stack exists
        STACK_STATUS=$(aws cloudformation describe-stacks \
            --stack-name "$STACK_NAME" \
            --query 'Stacks[0].StackStatus' \
            --output text --region "$REGION" 2>/dev/null || echo "NOT_FOUND")

        if [ "$STACK_STATUS" != "NOT_FOUND" ] && [ "$STACK_STATUS" != "DELETE_IN_PROGRESS" ]; then
            echo "Deleting stack: $STACK_NAME (status: $STACK_STATUS)"

            aws cloudformation delete-stack \
                --stack-name "$STACK_NAME" \
                --region "$REGION" 2>/dev/null || true

            # Wait for deletion (max 15 minutes per stack)
            echo "  Waiting for stack deletion..."
            if aws cloudformation wait stack-delete-complete \
                --stack-name "$STACK_NAME" \
                --region "$REGION" 2>/dev/null; then
                print_success "  Stack $STACK_NAME deleted"
            else
                print_warning "  Stack $STACK_NAME deletion timed out or failed"
            fi
        elif [ "$STACK_STATUS" = "DELETE_IN_PROGRESS" ]; then
            echo "Stack $STACK_NAME is already being deleted, waiting..."
            aws cloudformation wait stack-delete-complete \
                --stack-name "$STACK_NAME" \
                --region "$REGION" 2>/dev/null || true
        else
            echo "Stack $STACK_NAME not found, skipping"
        fi
    done
}

cleanup_opensearch_domain() {
    print_step "Cleaning up OpenSearch domain..."

    DOMAIN_NAME="${ENV_PREFIX}-ubi-ltr"

    # Check if domain exists
    DOMAIN_EXISTS=$(aws opensearch describe-domain \
        --domain-name "$DOMAIN_NAME" \
        --region "$REGION" 2>/dev/null || echo "")

    if [ -z "$DOMAIN_EXISTS" ]; then
        print_success "No OpenSearch domain found"
        return 0
    fi

    echo "Deleting OpenSearch domain: $DOMAIN_NAME"
    aws opensearch delete-domain \
        --domain-name "$DOMAIN_NAME" \
        --region "$REGION" 2>/dev/null || true

    print_success "OpenSearch domain deletion initiated (takes ~10-15 minutes)"
}

cleanup_osi_pipeline() {
    print_step "Cleaning up OSI pipeline..."

    PIPELINE_NAME="${ENV_PREFIX}-ubi-pipeline"

    # Check if pipeline exists
    PIPELINE_EXISTS=$(aws osis get-pipeline \
        --pipeline-name "$PIPELINE_NAME" \
        --region "$REGION" 2>/dev/null || echo "")

    if [ -z "$PIPELINE_EXISTS" ]; then
        print_success "No OSI pipeline found"
        return 0
    fi

    echo "Deleting OSI pipeline: $PIPELINE_NAME"
    aws osis delete-pipeline \
        --pipeline-name "$PIPELINE_NAME" \
        --region "$REGION" 2>/dev/null || true

    print_success "OSI pipeline deletion initiated"
}

cleanup_log_groups() {
    print_step "Cleaning up CloudWatch Log Groups..."

    # Patterns to search
    LOG_PATTERNS=(
        "/aws/lambda/${ENV_PREFIX}-ubi"
        "/aws/vendedlogs/osis-${ENV_PREFIX}"
        "/aws/opensearch-service/${ENV_PREFIX}"
    )

    FOUND_ANY=false

    for PATTERN in "${LOG_PATTERNS[@]}"; do
        LOG_GROUPS=$(aws logs describe-log-groups \
            --log-group-name-prefix "$PATTERN" \
            --query 'logGroups[].logGroupName' \
            --output text --region "$REGION" 2>/dev/null || echo "")

        if [ -n "$LOG_GROUPS" ]; then
            FOUND_ANY=true
            for LOG_GROUP in $LOG_GROUPS; do
                echo "Deleting log group: $LOG_GROUP"
                aws logs delete-log-group \
                    --log-group-name "$LOG_GROUP" \
                    --region "$REGION" 2>/dev/null || true
            done
        fi
    done

    if [ "$FOUND_ANY" = false ]; then
        print_success "No orphaned log groups found"
    else
        print_success "Log groups cleanup completed"
    fi
}

cleanup_ssm_parameters() {
    print_step "Cleaning up SSM Parameters..."

    # Find SSM parameters matching the pattern
    SSM_PARAMS=$(aws ssm describe-parameters \
        --parameter-filters "Key=Name,Values=/${ENV_PREFIX}/ubi-ltr,Option=BeginsWith" \
        --query 'Parameters[].Name' \
        --output text --region "$REGION" 2>/dev/null || echo "")

    if [ -z "$SSM_PARAMS" ]; then
        print_success "No orphaned SSM parameters found"
        return 0
    fi

    for PARAM in $SSM_PARAMS; do
        echo "Deleting SSM parameter: $PARAM"
        aws ssm delete-parameter \
            --name "$PARAM" \
            --region "$REGION" 2>/dev/null || true
    done

    print_success "SSM parameters cleanup completed"
}

cleanup_secrets() {
    print_step "Cleaning up Secrets Manager secrets..."

    # Find secrets matching the pattern
    SECRETS=$(aws secretsmanager list-secrets \
        --filters Key=name,Values="${ENV_PREFIX}-ubi" \
        --query 'SecretList[].ARN' \
        --output text --region "$REGION" 2>/dev/null || echo "")

    if [ -z "$SECRETS" ]; then
        print_success "No orphaned secrets found"
        return 0
    fi

    for SECRET in $SECRETS; do
        echo "Deleting secret: $SECRET"
        aws secretsmanager delete-secret \
            --secret-id "$SECRET" \
            --force-delete-without-recovery \
            --region "$REGION" 2>/dev/null || true
    done

    print_success "Secrets cleanup completed"
}

cleanup_s3_buckets() {
    print_step "Cleaning up S3 buckets..."

    # Find buckets matching the pattern
    BUCKETS=$(aws s3api list-buckets \
        --query "Buckets[?contains(Name, '${ENV_PREFIX}-ubi') || contains(Name, 'ubiltr-${ENV_PREFIX}')].Name" \
        --output text 2>/dev/null || echo "")

    if [ -z "$BUCKETS" ]; then
        print_success "No orphaned S3 buckets found"
        return 0
    fi

    for BUCKET in $BUCKETS; do
        echo "Processing bucket: $BUCKET"

        # Check if bucket exists and is accessible
        if aws s3api head-bucket --bucket "$BUCKET" 2>/dev/null; then
            # Empty the bucket (including versioned objects)
            echo "  Emptying bucket..."
            aws s3 rm "s3://$BUCKET" --recursive 2>/dev/null || true

            # Delete versioned objects if bucket has versioning
            echo "  Checking for versioned objects..."
            VERSIONS=$(aws s3api list-object-versions \
                --bucket "$BUCKET" \
                --query '{Objects: Versions[].{Key:Key,VersionId:VersionId}}' \
                --output json 2>/dev/null || echo '{"Objects": null}')

            if [ "$(echo "$VERSIONS" | jq '.Objects')" != "null" ] && [ "$(echo "$VERSIONS" | jq '.Objects | length')" != "0" ]; then
                echo "  Deleting versioned objects..."
                echo "$VERSIONS" | jq -c '.Objects[]?' | while read -r obj; do
                    KEY=$(echo "$obj" | jq -r '.Key')
                    VERSION=$(echo "$obj" | jq -r '.VersionId')
                    aws s3api delete-object \
                        --bucket "$BUCKET" \
                        --key "$KEY" \
                        --version-id "$VERSION" 2>/dev/null || true
                done
            fi

            # Delete delete markers
            DELETE_MARKERS=$(aws s3api list-object-versions \
                --bucket "$BUCKET" \
                --query '{Objects: DeleteMarkers[].{Key:Key,VersionId:VersionId}}' \
                --output json 2>/dev/null || echo '{"Objects": null}')

            if [ "$(echo "$DELETE_MARKERS" | jq '.Objects')" != "null" ] && [ "$(echo "$DELETE_MARKERS" | jq '.Objects | length')" != "0" ]; then
                echo "  Deleting delete markers..."
                echo "$DELETE_MARKERS" | jq -c '.Objects[]?' | while read -r obj; do
                    KEY=$(echo "$obj" | jq -r '.Key')
                    VERSION=$(echo "$obj" | jq -r '.VersionId')
                    aws s3api delete-object \
                        --bucket "$BUCKET" \
                        --key "$KEY" \
                        --version-id "$VERSION" 2>/dev/null || true
                done
            fi

            # Delete the bucket
            echo "  Deleting bucket..."
            if aws s3api delete-bucket --bucket "$BUCKET" --region "$REGION" 2>/dev/null; then
                print_success "  Bucket $BUCKET deleted"
            else
                print_warning "  Failed to delete bucket $BUCKET - may have remaining objects"
            fi
        fi
    done

    print_success "S3 buckets cleanup completed"
}

verify_cleanup() {
    print_step "Verifying cleanup..."

    # Check for remaining stacks
    REMAINING_STACKS=$(aws cloudformation list-stacks \
        --stack-status-filter CREATE_COMPLETE UPDATE_COMPLETE ROLLBACK_COMPLETE UPDATE_ROLLBACK_COMPLETE \
        --query "StackSummaries[?starts_with(StackName, '${ENV_PREFIX}-ubi-ltr')].StackName" \
        --output text --region "$REGION" 2>/dev/null || echo "")

    if [ -n "$REMAINING_STACKS" ]; then
        print_warning "Some stacks may still exist: $REMAINING_STACKS"
        echo "These may be in DELETE_IN_PROGRESS state. Check AWS Console."
    else
        print_success "All stacks destroyed"
    fi

    # Check for OpenSearch domain
    DOMAIN_STATUS=$(aws opensearch describe-domain \
        --domain-name "${ENV_PREFIX}-ubi-ltr" \
        --query 'DomainStatus.Processing' \
        --output text --region "$REGION" 2>/dev/null || echo "")

    if [ -n "$DOMAIN_STATUS" ]; then
        print_warning "OpenSearch domain still exists (may be deleting)"
    else
        print_success "OpenSearch domain cleaned up"
    fi

    # Check for remaining log groups
    REMAINING_LOGS=$(aws logs describe-log-groups \
        --log-group-name-prefix "/aws/lambda/${ENV_PREFIX}-ubi" \
        --query 'logGroups[].logGroupName' \
        --output text --region "$REGION" 2>/dev/null || echo "")

    if [ -n "$REMAINING_LOGS" ]; then
        print_warning "Some log groups may still exist"
    else
        print_success "All log groups cleaned up"
    fi
}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -e|--env-prefix)
            ENV_PREFIX="$2"
            shift 2
            ;;
        -r|--region)
            REGION="$2"
            shift 2
            ;;
        -y|--yes)
            SKIP_CONFIRM=true
            shift
            ;;
        --cleanup-only)
            CLEANUP_ONLY=true
            shift
            ;;
        -h|--help)
            usage
            ;;
        *)
            print_error "Unknown option: $1"
            usage
            ;;
    esac
done

# Main execution
print_banner

echo "Configuration:"
echo "  Environment: $ENV_PREFIX"
echo "  Region: $REGION"
echo "  Cleanup Only: $CLEANUP_ONLY"
echo ""

list_stacks

if [ "$SKIP_CONFIRM" = false ]; then
    echo -e "${RED}╔══════════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${RED}║  WARNING: This will PERMANENTLY DELETE all resources!            ║${NC}"
    echo -e "${RED}║  This action cannot be undone.                                   ║${NC}"
    echo -e "${RED}╚══════════════════════════════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "Type ${RED}DELETE${NC} to confirm destruction:"
    read -r CONFIRM

    if [ "$CONFIRM" != "DELETE" ]; then
        echo "Destruction cancelled."
        exit 0
    fi
fi

# Execute destruction steps
if [ "$CLEANUP_ONLY" = false ]; then
    destroy_stacks
fi

# Cleanup resources that might not be deleted by CDK
cleanup_osi_pipeline
cleanup_opensearch_domain
cleanup_log_groups
cleanup_ssm_parameters
cleanup_secrets
cleanup_s3_buckets
verify_cleanup

echo ""
echo -e "${GREEN}═══════════════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}Destruction completed for environment: ${ENV_PREFIX}${NC}"
echo -e "${GREEN}═══════════════════════════════════════════════════════════════════${NC}"
echo ""
echo "Note: Some resources (OpenSearch domain) may take 10-15 minutes to fully delete."
echo "Check AWS Console if you encounter any issues."
