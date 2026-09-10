# =============================================================================
# JobTracker — Terraform Variables
#
# All configurable inputs for the JobTracker AWS infrastructure.
# =============================================================================

variable "aws_region" {
  description = "AWS region to deploy all resources into."
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Deployment environment name (e.g. dev, staging, production)."
  type        = string
  default     = "production"

  validation {
    condition     = contains(["dev", "staging", "production"], var.environment)
    error_message = "environment must be one of: dev, staging, production."
  }
}

variable "project_name" {
  description = "Name used as a prefix for all resource names and tags."
  type        = string
  default     = "jobtracker"
}

variable "tags" {
  description = "Additional tags to apply to every resource."
  type        = map(string)
  default     = {}
}

variable "vpc_cidr" {
  description = "CIDR block for the VPC."
  type        = string
  default     = "10.0.0.0/16"
}

variable "private_subnet_cidrs" {
  description = "CIDR blocks for private subnets (need at least 2 for RDS subnet group)."
  type        = list(string)
  default     = ["10.0.1.0/24", "10.0.2.0/24"]
}

variable "public_subnet_cidrs" {
  description = "CIDR blocks for public subnets."
  type        = list(string)
  default     = ["10.0.101.0/24", "10.0.102.0/24"]
}

variable "allowed_ips" {
  description = "List of CIDR blocks allowed to connect to the RDS instance."
  type        = list(string)
  default     = []
}

variable "db_name" {
  description = "Name of the PostgreSQL database."
  type        = string
  default     = "jobtracker"
}

variable "db_username" {
  description = "Master username for the RDS instance."
  type        = string
  default     = "jobtracker_admin"
}

variable "db_password" {
  description = "Master password for the RDS instance. Must be >= 8 characters."
  type        = string
  sensitive   = true

  validation {
    condition     = length(var.db_password) >= 8
    error_message = "db_password must be at least 8 characters."
  }
}

variable "db_instance_class" {
  description = "RDS instance class."
  type        = string
  default     = "db.t3.micro"
}

variable "db_allocated_storage" {
  description = "Allocated storage for RDS in GB."
  type        = number
  default     = 20
}

variable "db_engine_version" {
  description = "PostgreSQL engine version."
  type        = string
  default     = "16.3"
}

variable "lambda_runtime" {
  description = "Lambda runtime identifier."
  type        = string
  default     = "python3.12"
}

variable "lambda_timeout" {
  description = "Default Lambda timeout in seconds."
  type        = number
  default     = 120
}

variable "lambda_memory_size" {
  description = "Default Lambda memory allocation in MB."
  type        = number
  default     = 256
}

variable "backend_api_url" {
  description = "Base URL of the JobTracker backend API."
  type        = string
  default     = "http://localhost:8000"
}

variable "api_secret_key" {
  description = "Shared secret for authenticating Lambda -> Backend webhook calls."
  type        = string
  sensitive   = true
  default     = ""
}

variable "listings_url" {
  description = "URL of the job-listings page for the scraper to crawl."
  type        = string
  default     = ""
}

variable "openai_api_key" {
  description = "OpenAI API key for AI-powered classification features."
  type        = string
  sensitive   = true
  default     = ""
}

variable "scraper_schedule" {
  description = "EventBridge cron/rate expression for the scraper (UTC)."
  type        = string
  default     = "cron(0 8 * * ? *)"
}
