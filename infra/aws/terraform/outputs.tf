# =============================================================================
# JobTracker — Terraform Outputs
# =============================================================================

output "api_gateway_url" {
  description = "Base invoke URL for the API Gateway stage."
  value       = aws_apigatewayv2_stage.default.invoke_url
}

output "webhook_url" {
  description = "Full URL for the Gmail Pub/Sub push endpoint."
  value       = "${aws_apigatewayv2_stage.default.invoke_url}/webhook/gmail"
}

output "rds_endpoint" {
  description = "Connection endpoint for the RDS PostgreSQL instance (host:port)."
  value       = aws_db_instance.postgres.endpoint
}

output "rds_hostname" {
  description = "Hostname of the RDS instance."
  value       = aws_db_instance.postgres.address
}

output "rds_port" {
  description = "Port of the RDS instance."
  value       = aws_db_instance.postgres.port
}

output "rds_database_name" {
  description = "Name of the PostgreSQL database."
  value       = aws_db_instance.postgres.db_name
}

output "lambda_email_webhook_arn" {
  description = "ARN of the email-webhook Lambda function."
  value       = aws_lambda_function.email_webhook.arn
}

output "lambda_scraper_cron_arn" {
  description = "ARN of the scraper-cron Lambda function."
  value       = aws_lambda_function.scraper_cron.arn
}

output "lambda_deployment_bucket" {
  description = "S3 bucket name for Lambda deployment packages."
  value       = aws_s3_bucket.lambda_deployments.id
}

output "vpc_id" {
  description = "ID of the VPC."
  value       = aws_vpc.main.id
}

output "private_subnet_ids" {
  description = "IDs of private subnets."
  value       = aws_subnet.private[*].id
}
