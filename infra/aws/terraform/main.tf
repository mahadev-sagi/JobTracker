# =============================================================================
# JobTracker — Terraform Main Configuration
#
# Provisions the complete AWS infrastructure:
#   - VPC with public/private subnets
#   - RDS PostgreSQL instance
#   - Lambda functions (email webhook + scraper cron)
#   - API Gateway v2 (HTTP) for the webhook endpoint
#   - EventBridge rule for scheduled scraping
#   - S3 bucket for Lambda deployment packages
#   - IAM roles and policies
# =============================================================================

terraform {
  required_version = ">= 1.5"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = merge(
      {
        Project     = var.project_name
        Environment = var.environment
        ManagedBy   = "terraform"
      },
      var.tags
    )
  }
}

# ---------------------------------------------------------------------------
# Data sources
# ---------------------------------------------------------------------------

data "aws_caller_identity" "current" {}
data "aws_availability_zones" "available" { state = "available" }

locals {
  name_prefix = "${var.project_name}-${var.environment}"
  account_id  = data.aws_caller_identity.current.account_id
  azs         = slice(data.aws_availability_zones.available.names, 0, 2)
}

# =============================================================================
# Networking — VPC, Subnets, Internet Gateway
# =============================================================================

resource "aws_vpc" "main" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = { Name = "${local.name_prefix}-vpc" }
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id
  tags   = { Name = "${local.name_prefix}-igw" }
}

# --- Public subnets ---

resource "aws_subnet" "public" {
  count                   = length(var.public_subnet_cidrs)
  vpc_id                  = aws_vpc.main.id
  cidr_block              = var.public_subnet_cidrs[count.index]
  availability_zone       = local.azs[count.index]
  map_public_ip_on_launch = true

  tags = { Name = "${local.name_prefix}-public-${local.azs[count.index]}" }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id
  tags   = { Name = "${local.name_prefix}-public-rt" }
}

resource "aws_route" "public_internet" {
  route_table_id         = aws_route_table.public.id
  destination_cidr_block = "0.0.0.0/0"
  gateway_id             = aws_internet_gateway.main.id
}

resource "aws_route_table_association" "public" {
  count          = length(aws_subnet.public)
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

# --- Private subnets ---

resource "aws_subnet" "private" {
  count             = length(var.private_subnet_cidrs)
  vpc_id            = aws_vpc.main.id
  cidr_block        = var.private_subnet_cidrs[count.index]
  availability_zone = local.azs[count.index]

  tags = { Name = "${local.name_prefix}-private-${local.azs[count.index]}" }
}

# =============================================================================
# Security Groups
# =============================================================================

# --- Lambda security group ---

resource "aws_security_group" "lambda" {
  name_prefix = "${local.name_prefix}-lambda-"
  description = "Security group for Lambda functions"
  vpc_id      = aws_vpc.main.id

  egress {
    description = "Allow all outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${local.name_prefix}-lambda-sg" }

  lifecycle { create_before_destroy = true }
}

# --- RDS security group ---

resource "aws_security_group" "rds" {
  name_prefix = "${local.name_prefix}-rds-"
  description = "Allow PostgreSQL access from Lambda and allowed IPs"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "PostgreSQL from Lambda"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.lambda.id]
  }

  dynamic "ingress" {
    for_each = var.allowed_ips
    content {
      description = "PostgreSQL from allowed IP"
      from_port   = 5432
      to_port     = 5432
      protocol    = "tcp"
      cidr_blocks = [ingress.value]
    }
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${local.name_prefix}-rds-sg" }

  lifecycle { create_before_destroy = true }
}

# =============================================================================
# RDS PostgreSQL
# =============================================================================

resource "aws_db_subnet_group" "main" {
  name       = "${local.name_prefix}-db-subnet"
  subnet_ids = aws_subnet.private[*].id

  tags = { Name = "${local.name_prefix}-db-subnet-group" }
}

resource "aws_db_instance" "postgres" {
  identifier = "${local.name_prefix}-postgres"

  engine         = "postgres"
  engine_version = var.db_engine_version
  instance_class = var.db_instance_class

  allocated_storage     = var.db_allocated_storage
  max_allocated_storage = var.db_allocated_storage * 2
  storage_type          = "gp3"
  storage_encrypted     = true

  db_name  = var.db_name
  username = var.db_username
  password = var.db_password

  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.rds.id]

  multi_az            = var.environment == "production"
  publicly_accessible = false
  skip_final_snapshot = var.environment != "production"

  final_snapshot_identifier = var.environment == "production" ? "${local.name_prefix}-final-snapshot" : null

  backup_retention_period = var.environment == "production" ? 7 : 1
  backup_window           = "03:00-04:00"
  maintenance_window      = "Mon:04:00-Mon:05:00"

  performance_insights_enabled = var.environment == "production"

  tags = { Name = "${local.name_prefix}-postgres" }
}

# =============================================================================
# S3 — Lambda Deployment Packages
# =============================================================================

resource "aws_s3_bucket" "lambda_deployments" {
  bucket = "${local.name_prefix}-lambda-deployments-${local.account_id}"

  tags = { Name = "${local.name_prefix}-lambda-deployments" }
}

resource "aws_s3_bucket_versioning" "lambda_deployments" {
  bucket = aws_s3_bucket.lambda_deployments.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "lambda_deployments" {
  bucket = aws_s3_bucket.lambda_deployments.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
  }
}

# =============================================================================
# IAM — Lambda Execution Roles
# =============================================================================

data "aws_iam_policy_document" "lambda_assume_role" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "email_webhook" {
  name               = "${local.name_prefix}-email-webhook-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json

  tags = { Name = "${local.name_prefix}-email-webhook-role" }
}

resource "aws_iam_role_policy_attachment" "email_webhook_basic" {
  role       = aws_iam_role.email_webhook.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy_attachment" "email_webhook_vpc" {
  role       = aws_iam_role.email_webhook.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}

resource "aws_iam_role" "scraper_cron" {
  name               = "${local.name_prefix}-scraper-cron-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json

  tags = { Name = "${local.name_prefix}-scraper-cron-role" }
}

resource "aws_iam_role_policy_attachment" "scraper_cron_basic" {
  role       = aws_iam_role.scraper_cron.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy_attachment" "scraper_cron_vpc" {
  role       = aws_iam_role.scraper_cron.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}

# =============================================================================
# Lambda Functions
# =============================================================================

data "archive_file" "email_webhook" {
  type        = "zip"
  source_dir  = "${path.module}/../lambda/email_webhook"
  output_path = "${path.module}/.build/email_webhook.zip"
}

data "archive_file" "scraper_cron" {
  type        = "zip"
  source_dir  = "${path.module}/../lambda/scraper_cron"
  output_path = "${path.module}/.build/scraper_cron.zip"
}

resource "aws_lambda_function" "email_webhook" {
  function_name = "${local.name_prefix}-email-webhook"
  description   = "Processes Gmail Pub/Sub push notifications"

  role    = aws_iam_role.email_webhook.arn
  handler = "handler.handler"
  runtime = var.lambda_runtime

  filename         = data.archive_file.email_webhook.output_path
  source_code_hash = data.archive_file.email_webhook.output_base64sha256

  timeout     = 30
  memory_size = 128

  vpc_config {
    subnet_ids         = aws_subnet.private[*].id
    security_group_ids = [aws_security_group.lambda.id]
  }

  environment {
    variables = {
      BACKEND_API_URL = var.backend_api_url
      API_SECRET_KEY  = var.api_secret_key
      LOG_LEVEL       = var.environment == "production" ? "INFO" : "DEBUG"
    }
  }

  tags = { Name = "${local.name_prefix}-email-webhook" }

  depends_on = [
    aws_iam_role_policy_attachment.email_webhook_basic,
    aws_iam_role_policy_attachment.email_webhook_vpc,
  ]
}

resource "aws_lambda_function" "scraper_cron" {
  function_name = "${local.name_prefix}-scraper-cron"
  description   = "Scheduled job-listing scraper"

  role    = aws_iam_role.scraper_cron.arn
  handler = "handler.handler"
  runtime = var.lambda_runtime

  filename         = data.archive_file.scraper_cron.output_path
  source_code_hash = data.archive_file.scraper_cron.output_base64sha256

  timeout     = var.lambda_timeout
  memory_size = var.lambda_memory_size

  vpc_config {
    subnet_ids         = aws_subnet.private[*].id
    security_group_ids = [aws_security_group.lambda.id]
  }

  environment {
    variables = {
      BACKEND_API_URL = var.backend_api_url
      API_SECRET_KEY  = var.api_secret_key
      SCRAPER_MODE    = "api"
      LISTINGS_URL    = var.listings_url
      OPENAI_API_KEY  = var.openai_api_key
      LOG_LEVEL       = var.environment == "production" ? "INFO" : "DEBUG"
    }
  }

  tags = { Name = "${local.name_prefix}-scraper-cron" }

  depends_on = [
    aws_iam_role_policy_attachment.scraper_cron_basic,
    aws_iam_role_policy_attachment.scraper_cron_vpc,
  ]
}

# =============================================================================
# API Gateway v2 (HTTP API) — Webhook Endpoint
# =============================================================================

resource "aws_apigatewayv2_api" "webhook" {
  name          = "${local.name_prefix}-webhook-api"
  protocol_type = "HTTP"
  description   = "HTTP API for JobTracker webhook endpoints"

  cors_configuration {
    allow_origins = ["*"]
    allow_methods = ["POST", "OPTIONS"]
    allow_headers = ["Content-Type", "X-Webhook-Secret"]
    max_age       = 3600
  }

  tags = { Name = "${local.name_prefix}-webhook-api" }
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.webhook.id
  name        = "$default"
  auto_deploy = true

  tags = { Name = "${local.name_prefix}-webhook-stage" }
}

resource "aws_apigatewayv2_integration" "email_webhook" {
  api_id             = aws_apigatewayv2_api.webhook.id
  integration_type   = "AWS_PROXY"
  integration_uri    = aws_lambda_function.email_webhook.invoke_arn
  integration_method = "POST"
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "email_webhook" {
  api_id    = aws_apigatewayv2_api.webhook.id
  route_key = "POST /webhook/gmail"
  target    = "integrations/${aws_apigatewayv2_integration.email_webhook.id}"
}

resource "aws_lambda_permission" "api_gateway_email_webhook" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.email_webhook.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.webhook.execution_arn}/*/*"
}

# =============================================================================
# EventBridge — Scraper Cron Schedule
# =============================================================================

resource "aws_cloudwatch_event_rule" "scraper_cron" {
  name                = "${local.name_prefix}-scraper-cron"
  description         = "Triggers the job-listing scraper on a schedule"
  schedule_expression = var.scraper_schedule
  state               = "ENABLED"

  tags = { Name = "${local.name_prefix}-scraper-cron-rule" }
}

resource "aws_cloudwatch_event_target" "scraper_cron" {
  rule = aws_cloudwatch_event_rule.scraper_cron.name
  arn  = aws_lambda_function.scraper_cron.arn

  input = jsonencode({
    source      = "eventbridge"
    detail_type = "Scheduled Scraper Run"
  })
}

resource "aws_lambda_permission" "eventbridge_scraper_cron" {
  statement_id  = "AllowEventBridgeInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.scraper_cron.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.scraper_cron.arn
}
