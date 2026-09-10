# JobTracker

**Automated Job Application Tracking System**

JobTracker is a full-stack application that automatically discovers, tracks, and manages job applications. It combines web scraping, email parsing (via Gmail API + GCP Pub/Sub), and AI-powered classification to give you a single dashboard for your entire job search.

---

## Table of Contents

- [Architecture](#architecture)
- [Tech Stack](#tech-stack)
- [Getting Started](#getting-started)
- [Environment Variables](#environment-variables)
- [API Endpoints](#api-endpoints)
- [Development Workflow](#development-workflow)
- [Deployment](#deployment)
- [License](#license)

---

## Architecture

JobTracker is composed of three main pipelines that feed into a shared PostgreSQL database and are surfaced through a React dashboard.

```
┌─────────────────────────────────────────────────────────────────────┐
│                        JobTracker Architecture                      │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌──────────────────┐    ┌──────────────────┐    ┌───────────────┐  │
│  │  Scraper Pipeline │    │  Email Pipeline  │    │   Dashboard   │  │
│  │                  │    │                  │    │               │  │
│  │  GitHub Listings ─┤    │  Gmail API       │    │  React + Vite │  │
│  │  Periodic Fetch   │    │  GCP Pub/Sub     │    │  Shadcn/UI    │  │
│  │  Deduplication    │    │  OpenAI Parser   │    │  TanStack     │  │
│  └────────┬─────────┘    └────────┬─────────┘    └───────┬───────┘  │
│           │                       │                      │          │
│           ▼                       ▼                      ▼          │
│  ┌─────────────────────────────────────────────────────────────────┐ │
│  │                     FastAPI Backend (REST)                     │ │
│  │                                                                │ │
│  │  • SQLAlchemy (async) ORM         • Pydantic schemas           │ │
│  │  • Alembic migrations             • Structured logging         │ │
│  └────────────────────────────┬──────────────────────────────────┘ │
│                               │                                    │
│                               ▼                                    │
│                    ┌─────────────────────┐                         │
│                    │   PostgreSQL 16     │                         │
│                    │   (Docker volume)   │                         │
│                    └─────────────────────┘                         │
│                                                                     │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │              Infrastructure (Terraform + AWS)                │   │
│  │  Lambda Functions · API Gateway · CloudWatch · IAM           │   │
│  └──────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

### Pipeline Descriptions

| Pipeline | Description |
|---|---|
| **Scraper Pipeline** | Periodically fetches job listings from a GitHub-hosted JSON source, deduplicates entries, and upserts them into the database. Deployed as an AWS Lambda on a schedule. |
| **Email Pipeline** | Listens for Gmail notifications via GCP Pub/Sub push subscriptions. When a new email arrives, it fetches the message, sends the content to OpenAI for structured parsing, and stores the extracted application status update. |
| **Dashboard** | A React SPA that provides search, filtering, status tracking, and analytics for all tracked applications. |

---

## Tech Stack

| Layer | Technology | Purpose |
|---|---|---|
| **Backend** | [FastAPI](https://fastapi.tiangolo.com/) | Async REST API framework |
| **ORM** | [SQLAlchemy 2.0](https://www.sqlalchemy.org/) (async) | Database models & queries |
| **Migrations** | [Alembic](https://alembic.sqlalchemy.org/) | Schema versioning |
| **Database** | [PostgreSQL 16](https://www.postgresql.org/) | Primary data store |
| **Frontend** | [React 18](https://react.dev/) + [Vite](https://vitejs.dev/) | SPA with HMR |
| **UI Library** | [shadcn/ui](https://ui.shadcn.com/) + [Tailwind CSS](https://tailwindcss.com/) | Component library & styling |
| **AI/LLM** | [OpenAI GPT-4o](https://platform.openai.com/) | Email parsing & classification |
| **Email** | [Gmail API](https://developers.google.com/gmail/api) | Email ingestion |
| **Pub/Sub** | [GCP Pub/Sub](https://cloud.google.com/pubsub) | Real-time Gmail push notifications |
| **Serverless** | [AWS Lambda](https://aws.amazon.com/lambda/) | Scraper & webhook deployment |
| **IaC** | [Terraform](https://www.terraform.io/) | Infrastructure provisioning |
| **Containers** | [Docker](https://www.docker.com/) + Docker Compose | Local development environment |

---

## Getting Started

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/) >= 24.0 & Docker Compose >= 2.20
- [Python](https://www.python.org/) >= 3.11 (for local development without Docker)
- [Node.js](https://nodejs.org/) >= 20 LTS & npm >= 10 (for local frontend development)
- [Terraform](https://www.terraform.io/) >= 1.6 (for infrastructure deployment)

### Quick Start

1. **Clone the repository**

   ```bash
   git clone https://github.com/your-username/JobTracker.git
   cd JobTracker
   ```

2. **Create your environment file**

   ```bash
   cp .env.example .env
   # Edit .env with your actual credentials
   ```

3. **Start all services**

   ```bash
   docker compose up -d --build
   ```

4. **Verify the services are running**

   ```bash
   # Backend health check
   curl http://localhost:8000/health

   # Frontend
   open http://localhost:5173
   ```

5. **Run database migrations**

   ```bash
   docker compose exec backend alembic upgrade head
   ```

### Local Development (without Docker)

```bash
# Backend
cd backend
python -m venv .venv
source .venv/bin/activate      # or .venv\Scripts\activate on Windows
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Frontend (in a separate terminal)
cd frontend
npm install
npm run dev
```

---

## Environment Variables

| Variable | Description | Default |
|---|---|---|
| `DATABASE_URL` | PostgreSQL async connection string | `postgresql+asyncpg://user:password@localhost:5432/jobtracker` |
| `POSTGRES_USER` | PostgreSQL username | `jobtracker` |
| `POSTGRES_PASSWORD` | PostgreSQL password | `changeme` |
| `POSTGRES_DB` | PostgreSQL database name | `jobtracker` |
| `OPENAI_API_KEY` | OpenAI API key for email parsing | — |
| `OPENAI_MODEL` | OpenAI model identifier | `gpt-4o-2024-08-06` |
| `GOOGLE_CLOUD_PROJECT_ID` | GCP project for Pub/Sub | — |
| `GOOGLE_PUBSUB_TOPIC` | Pub/Sub topic for Gmail push | `gmail-notifications` |
| `GOOGLE_PUBSUB_SUBSCRIPTION` | Pub/Sub subscription name | `gmail-notifications-sub` |
| `GMAIL_USER_EMAIL` | Gmail address to monitor | — |
| `GOOGLE_CREDENTIALS_JSON` | Path to GCP service account JSON | — |
| `AWS_REGION` | AWS region for Lambda deployment | `us-east-1` |
| `AWS_ACCESS_KEY_ID` | AWS access key | — |
| `AWS_SECRET_ACCESS_KEY` | AWS secret key | — |
| `BACKEND_URL` | Backend base URL | `http://localhost:8000` |
| `FRONTEND_URL` | Frontend base URL | `http://localhost:5173` |
| `ENVIRONMENT` | Runtime environment | `development` |
| `LOG_LEVEL` | Logging verbosity | `INFO` |
| `LISTINGS_URL` | GitHub raw URL for job listings JSON | *(see .env.example)* |

---

## API Endpoints

### Health & Info

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | Health check |
| `GET` | `/info` | App version & environment info |

### Jobs

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/v1/jobs` | List jobs (with pagination, filtering, search) |
| `GET` | `/api/v1/jobs/{id}` | Get a single job by ID |
| `POST` | `/api/v1/jobs` | Create a new job entry |
| `PATCH` | `/api/v1/jobs/{id}` | Update a job (e.g., status change) |
| `DELETE` | `/api/v1/jobs/{id}` | Delete a job |

### Scraper

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/v1/scraper/run` | Trigger a manual scraper run |
| `GET` | `/api/v1/scraper/status` | Last scraper run status |

### Email / Webhooks

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/v1/webhooks/gmail` | GCP Pub/Sub push endpoint |
| `GET` | `/api/v1/emails` | List parsed email events |

### Analytics

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/v1/analytics/summary` | Application stats summary |
| `GET` | `/api/v1/analytics/timeline` | Applications over time |

---

## Development Workflow

### Project Structure

```
JobTracker/
├── backend/               # FastAPI application
│   ├── app/
│   │   ├── api/           # Route handlers
│   │   ├── core/          # Config, security, dependencies
│   │   ├── models/        # SQLAlchemy models
│   │   ├── schemas/       # Pydantic schemas
│   │   ├── services/      # Business logic
│   │   └── main.py        # Application entry point
│   ├── alembic/           # Database migrations
│   ├── tests/             # pytest test suite
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/              # React + Vite SPA
│   ├── src/
│   │   ├── components/    # Reusable UI components
│   │   ├── pages/         # Route-level pages
│   │   ├── hooks/         # Custom React hooks
│   │   ├── lib/           # Utilities & API client
│   │   └── App.tsx
│   ├── Dockerfile
│   └── package.json
├── infrastructure/        # Terraform IaC
│   ├── modules/
│   ├── environments/
│   └── main.tf
├── docker-compose.yml
├── .env.example
├── .gitignore
└── README.md
```

### Running Tests

```bash
# Backend tests
docker compose exec backend pytest -v --cov=app

# Frontend tests
docker compose exec frontend npm test
```

### Database Migrations

```bash
# Create a new migration
docker compose exec backend alembic revision --autogenerate -m "description"

# Apply migrations
docker compose exec backend alembic upgrade head

# Rollback one migration
docker compose exec backend alembic downgrade -1
```

### Code Quality

```bash
# Backend linting & formatting
docker compose exec backend ruff check .
docker compose exec backend ruff format .

# Frontend linting & formatting
docker compose exec frontend npm run lint
docker compose exec frontend npm run format
```

---

## Deployment

### AWS Lambda (Scraper & Webhooks)

The scraper and Gmail webhook handler are deployed as AWS Lambda functions using Terraform.

```bash
cd infrastructure

# Initialize Terraform
terraform init

# Preview changes
terraform plan -var-file="environments/prod.tfvars"

# Deploy
terraform apply -var-file="environments/prod.tfvars"
```

### Docker (Self-Hosted)

For self-hosted deployment, use the production Docker Compose override:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

### Environment Checklist

- [ ] All secrets are set in `.env` (never committed to Git)
- [ ] Database migrations have been applied
- [ ] GCP Pub/Sub subscription is configured with the correct push endpoint
- [ ] Gmail API watch is registered for the target inbox
- [ ] AWS Lambda functions are deployed and scheduled
- [ ] CORS origins are configured for the production frontend URL

---

## License

This project is licensed under the [MIT License](LICENSE).

```
MIT License

Copyright (c) 2025 JobTracker Contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
