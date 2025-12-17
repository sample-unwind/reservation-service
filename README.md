# Reservation Service

## Description
Python/FastAPI microservice for handling reservations with CQRS/ES.

## Setup
- Install Python 3.11
- Run `pip install -r requirements.txt`
- Run `uvicorn main:app --reload`

## API Endpoints
- GET /health/live
- GET /health/ready

## CI/CD
This service uses GitHub Actions for CI/CD.

- **Triggers**: Push to main, PRs, releases.
- **Linting**: black, mypy, isort, flake8.
- **Testing**: pytest (placeholder).
- **Build**: Docker image.
- **Deploy**: Placeholders for ACR push and Helm upgrade on AKS.

See `.github/workflows/ci-cd.yml` for details.