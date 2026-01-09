#!/bin/bash
#
# UBI-LTR Pipeline - Deployment Script
# Deploy all AWS infrastructure for User Behavior Insights to Learning to Rank pipeline
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
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# AWS CLI common options to disable pager
export AWS_PAGER=""

# Functions
print_banner() {
    echo -e "${BLUE}"
    echo "╔══════════════════════════════════════════════════════════════════╗"
    echo "║           UBI-LTR Pipeline - AWS CDK Deployment                  ║"
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
    echo "  -h, --help                Show this help message"
    echo ""
    echo "Examples:"
    echo "  $0                        # Deploy with defaults (dev, us-east-1)"
    echo "  $0 -e prod -r us-west-2   # Deploy to production in us-west-2"
    echo "  $0 -y                     # Deploy without confirmation"
    exit 0
}

check_prerequisites() {
    print_step "Checking prerequisites..."

    local missing=()

    # Check AWS CLI
    if ! command -v aws &> /dev/null; then
        missing+=("aws-cli")
    else
        print_success "AWS CLI: $(aws --version 2>&1 | head -n1)"
    fi

    # Check Node.js
    if ! command -v node &> /dev/null; then
        missing+=("node")
    else
        NODE_VERSION=$(node --version | sed 's/v//' | cut -d. -f1)
        if [ "$NODE_VERSION" -lt 18 ]; then
            print_error "Node.js version must be 18 or higher (found: $(node --version))"
            missing+=("node>=18")
        else
            print_success "Node.js: $(node --version)"
        fi
    fi

    # Check npm
    if ! command -v npm &> /dev/null; then
        missing+=("npm")
    else
        print_success "npm: $(npm --version)"
    fi

    # Check Python (for Lambda dependencies)
    if ! command -v python3 &> /dev/null; then
        missing+=("python3")
    else
        PYTHON_VERSION=$(python3 --version 2>&1 | sed 's/Python //')
        print_success "Python: $PYTHON_VERSION"
    fi

    # Check pip
    if ! command -v pip3 &> /dev/null && ! python3 -m pip --version &> /dev/null; then
        missing+=("pip3")
    else
        PIP_VERSION=$(python3 -m pip --version 2>&1 | head -n1)
        print_success "pip: $PIP_VERSION"
    fi

    # Check AWS credentials
    if ! aws sts get-caller-identity &> /dev/null; then
        print_error "AWS credentials not configured or invalid"
        missing+=("aws-credentials")
    else
        ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
        print_success "AWS Account: $ACCOUNT_ID"
    fi

    if [ ${#missing[@]} -ne 0 ]; then
        print_error "Missing prerequisites: ${missing[*]}"
        echo ""
        echo "Please install missing dependencies:"
        echo "  - AWS CLI: https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html"
        echo "  - Node.js: https://nodejs.org/ (v18 or higher)"
        echo "  - Python 3: https://www.python.org/downloads/ (v3.9 or higher)"
        echo "  - AWS credentials: aws configure"
        exit 1
    fi

    print_success "All prerequisites satisfied"
}

install_dependencies() {
    print_step "Installing CDK dependencies..."
    cd "$SCRIPT_DIR"

    if [ ! -d "node_modules" ]; then
        npm install
    else
        print_success "CDK dependencies already installed"
    fi

    cd "$SCRIPT_DIR"
}

install_python_dependencies() {
    print_step "Installing Python dependencies for Lambda..."

    # Lambda runtime platform options (Amazon Linux 2, x86_64, Python 3.12)
    # This ensures we get Linux-compatible binaries even when running on macOS
    local PIP_PLATFORM_OPTS="--platform manylinux2014_x86_64 --implementation cp --python-version 3.12 --only-binary=:all:"

    # Install webapp-backend dependencies
    local WEBAPP_DIR="$SCRIPT_DIR/lambda/webapp-backend"
    if [ -f "$WEBAPP_DIR/requirements.txt" ]; then
        echo "Installing webapp-backend dependencies for Lambda (Linux x86_64)..."

        # Clean up old packages (keep only main.py and requirements.txt)
        find "$WEBAPP_DIR" -mindepth 1 -maxdepth 1 \
            ! -name "main.py" \
            ! -name "requirements.txt" \
            ! -name ".gitkeep" \
            -exec rm -rf {} + 2>/dev/null || true

        # Install dependencies with Lambda-compatible platform
        python3 -m pip install \
            --quiet \
            --target "$WEBAPP_DIR" \
            $PIP_PLATFORM_OPTS \
            -r "$WEBAPP_DIR/requirements.txt" 2>/dev/null || {
            # Fallback: some packages don't have pre-built wheels
            # Try without --only-binary for pure Python packages
            print_warning "Some packages need source build, retrying..."
            python3 -m pip install \
                --quiet \
                --target "$WEBAPP_DIR" \
                --platform manylinux2014_x86_64 \
                --implementation cp \
                --python-version 3.12 \
                -r "$WEBAPP_DIR/requirements.txt"
        }

        # Count installed packages
        PKG_COUNT=$(find "$WEBAPP_DIR" -maxdepth 1 -type d | wc -l | tr -d ' ')
        print_success "webapp-backend dependencies installed ($PKG_COUNT packages)"
    else
        print_warning "webapp-backend/requirements.txt not found, skipping"
    fi

    # Install layer dependencies
    local LAYER_DIR="$SCRIPT_DIR/lambda/layers/dependencies"
    if [ -f "$LAYER_DIR/requirements.txt" ]; then
        echo "Installing Lambda layer dependencies for Lambda (Linux x86_64)..."

        # Create python directory for layer
        mkdir -p "$LAYER_DIR/python"

        # Clean up old packages
        rm -rf "$LAYER_DIR/python/"* 2>/dev/null || true

        # Install dependencies with Lambda-compatible platform
        python3 -m pip install \
            --quiet \
            --target "$LAYER_DIR/python" \
            $PIP_PLATFORM_OPTS \
            -r "$LAYER_DIR/requirements.txt" 2>/dev/null || {
            # Fallback for pure Python packages
            print_warning "Some packages need source build, retrying..."
            python3 -m pip install \
                --quiet \
                --target "$LAYER_DIR/python" \
                --platform manylinux2014_x86_64 \
                --implementation cp \
                --python-version 3.12 \
                -r "$LAYER_DIR/requirements.txt"
        }

        # Count installed packages
        PKG_COUNT=$(find "$LAYER_DIR/python" -maxdepth 1 -type d | wc -l | tr -d ' ')
        print_success "Lambda layer dependencies installed ($PKG_COUNT packages)"
    else
        print_warning "lambda/layers/dependencies/requirements.txt not found, skipping"
    fi
}

build_frontend() {
    print_step "Building frontend application..."

    # Check if webapp-frontend directory exists
    if [ ! -d "$SCRIPT_DIR/webapp-frontend" ]; then
        print_error "webapp-frontend directory not found"
        exit 1
    fi

    cd "$SCRIPT_DIR/webapp-frontend"

    # Check if package.json exists
    if [ ! -f "package.json" ]; then
        print_error "webapp-frontend/package.json not found"
        exit 1
    fi

    # Install dependencies if needed
    if [ ! -d "node_modules" ]; then
        echo "Installing frontend dependencies..."
        npm install
    fi

    # Always build to ensure latest code is deployed
    echo "Running npm run build..."
    npm run build

    # Verify build output
    if [ ! -d "dist" ]; then
        print_error "Frontend build failed - dist directory not created"
        exit 1
    fi

    print_success "Frontend build completed ($(ls -1 dist | wc -l | tr -d ' ') files)"

    cd "$SCRIPT_DIR"
}

bootstrap_cdk() {
    print_step "Checking CDK bootstrap status..."

    ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

    # Check if bootstrap stack exists
    if ! aws cloudformation describe-stacks --stack-name CDKToolkit --region "$REGION" &> /dev/null; then
        print_warning "CDK not bootstrapped in $REGION. Bootstrapping now..."
        npx cdk bootstrap "aws://$ACCOUNT_ID/$REGION"
        print_success "CDK bootstrap completed"
    else
        print_success "CDK already bootstrapped in $REGION"
    fi
}

deploy_stacks() {
    print_step "Deploying all CDK stacks..."
    echo ""
    echo "Environment: $ENV_PREFIX"
    echo "Region: $REGION"
    echo ""
    echo "Stacks to deploy:"
    echo "  1. ${ENV_PREFIX}-ubi-ltr-storage (S3 buckets)"
    echo "  2. ${ENV_PREFIX}-ubi-ltr-iam (IAM roles)"
    echo "  3. ${ENV_PREFIX}-ubi-ltr-opensearch (OpenSearch domain) ~20-30 min"
    echo "  4. ${ENV_PREFIX}-ubi-ltr-osi (OSI pipeline)"
    echo "  5. ${ENV_PREFIX}-ubi-ltr-processing (Lambda + Step Functions)"
    echo "  6. ${ENV_PREFIX}-ubi-ltr-setup (Index initialization)"
    echo "  7. ${ENV_PREFIX}-ubi-ltr-webapp (API Gateway + CloudFront)"
    echo ""

    cd "$SCRIPT_DIR"
    npx cdk deploy --all \
        --require-approval never \
        -c envPrefix="$ENV_PREFIX" \
        -c region="$REGION"

    print_success "All stacks deployed successfully!"
}

display_outputs() {
    print_step "Deployment Outputs"
    echo ""

    # Stack names follow pattern: ${ENV_PREFIX}-ubi-ltr-{component}
    local OPENSEARCH_STACK="${ENV_PREFIX}-ubi-ltr-opensearch"
    local WEBAPP_STACK="${ENV_PREFIX}-ubi-ltr-webapp"
    local OSI_STACK="${ENV_PREFIX}-ubi-ltr-osi"

    echo -e "${GREEN}═══════════════════════════════════════════════════════════════════${NC}"

    # Website URL
    WEBSITE_URL=$(aws cloudformation describe-stacks \
        --stack-name "$WEBAPP_STACK" \
        --query 'Stacks[0].Outputs[?OutputKey==`WebsiteUrl`].OutputValue' \
        --output text --region "$REGION" 2>/dev/null || echo "N/A")
    echo -e "${BLUE}Website URL:${NC} $WEBSITE_URL"

    # API Endpoint
    API_URL=$(aws cloudformation describe-stacks \
        --stack-name "$WEBAPP_STACK" \
        --query 'Stacks[0].Outputs[?OutputKey==`ApiEndpoint`].OutputValue' \
        --output text --region "$REGION" 2>/dev/null || echo "N/A")
    echo -e "${BLUE}API Endpoint:${NC} $API_URL"

    # OSI Pipeline Endpoint
    OSI_URL=$(aws cloudformation describe-stacks \
        --stack-name "$OSI_STACK" \
        --query 'Stacks[0].Outputs[?OutputKey==`PipelineEndpoint`].OutputValue' \
        --output text --region "$REGION" 2>/dev/null || echo "N/A")
    echo -e "${BLUE}OSI Pipeline:${NC} $OSI_URL"

    # OpenSearch Dashboard
    OPENSEARCH_ENDPOINT=$(aws cloudformation describe-stacks \
        --stack-name "$OPENSEARCH_STACK" \
        --query 'Stacks[0].Outputs[?OutputKey==`DomainEndpoint`].OutputValue' \
        --output text --region "$REGION" 2>/dev/null || echo "N/A")
    echo -e "${BLUE}OpenSearch Dashboard:${NC} https://$OPENSEARCH_ENDPOINT/_dashboards"

    echo -e "${GREEN}═══════════════════════════════════════════════════════════════════${NC}"
    echo ""

    # Credentials command
    SECRET_ARN=$(aws cloudformation describe-stacks \
        --stack-name "$OPENSEARCH_STACK" \
        --query 'Stacks[0].Outputs[?OutputKey==`MasterUserSecretArn`].OutputValue' \
        --output text --region "$REGION" 2>/dev/null || echo "")

    if [ -n "$SECRET_ARN" ] && [ "$SECRET_ARN" != "N/A" ]; then
        echo -e "${YELLOW}To get OpenSearch credentials:${NC}"
        echo "aws secretsmanager get-secret-value --secret-id $SECRET_ARN --query SecretString --output text | jq ."
        echo ""
    fi

    echo -e "${GREEN}Deployment completed successfully!${NC}"
    echo ""
    echo "Next steps:"
    echo "  1. Access the website at: $WEBSITE_URL"
    echo "  2. Access OpenSearch Dashboard: https://$OPENSEARCH_ENDPOINT/_dashboards"
    echo "  3. See README.md for UBI Dashboard setup guide"
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
echo ""

if [ "$SKIP_CONFIRM" = false ]; then
    echo -e "${YELLOW}This will deploy the following AWS resources:${NC}"
    echo "  - OpenSearch Service domain (~\$30/month)"
    echo "  - OpenSearch Ingestion pipeline (~\$15/month)"
    echo "  - Lambda functions, Step Functions"
    echo "  - S3 buckets, CloudFront distribution"
    echo "  - API Gateway, Secrets Manager"
    echo ""
    read -p "Do you want to proceed? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Deployment cancelled."
        exit 0
    fi
fi

# Execute deployment steps
check_prerequisites
install_dependencies
install_python_dependencies
build_frontend
bootstrap_cdk
deploy_stacks
display_outputs
