## Context
In this challenge, you will act as a Data Engineer in a realistic scenario where data is not readily available in a structured format and must be discovered, integrated, and operationalized.
The goal is not only to build a functional pipeline, but to demonstrate:
- ability to structure open-ended problems
- quality of technical decision-making
- code organization and maintainability
- software engineering practices
- maturity in cloud, APIs, and automation
- effective use of AI as a problem-solving tool

## Objectives
Build a complete data engineering solution that:
1. Integrates multiple data sources
2. Handles inconsistencies and intentional data issues
3. Models the data in a usable structure
4. Exposes the data through an API
5. Runs in a containerized environment
6. Is automated through a CI/CD pipeline
7. Uses AI in a structured and meaningful way

## Scope of the Challenge
## Part 1 — Local Data Integration
You will receive local files (CSV, JSON, or JSONL) containing inconsistent and incomplete data.
Expected:
- data ingestion
- data cleaning and normalization
- handling missing or inconsistent values
- deduplication and consolidation

## Part 2 — Data Enrichment via API
Use a ExchangeRate API to enrich your dataset.
Expected:
- API integration using Python
- proper error handling (timeouts, failures, invalid responses)
- clear enrichment logic

## Part 3 — Handling Inconsistencies
The dataset includes intentionally flawed and ambiguous data.
Expected:
- identification of issues
- explicit decisions on how to handle them
- clear justification of choices

## Part 4 — Data Modeling
Structure the data for analytical consumption.
Expected:
- definition of entities
- coherent structure
- clear relationships
- focus on usability for queries or analysis

## Part 5 — Data Pipeline
Build the end-to-end data pipeline.
Expected:
- separation of concerns
- organized code structure
- ability to reprocess data
- good engineering practices

## Part 6 — API Layer 
Expose the processed data through a FastAPI application.
Minimum endpoints:
GET /customers 
GET /orders 
GET /metrics
Evaluation focus:
- API design
- code organization
- separation of layers
- response structure

## Part 7 — Containerization 
The solution must run using Docker.
Expected:
- functional Dockerfile
- ability to run both pipeline and API
- clear execution instructions

## Part 8 — CI/CD Pipeline 
You must implement a CI/CD pipeline using GitHub Actions. Your pipeline must:
- Build the project
- Run automated tests
- Execute the data pipeline
- Validate that the API can start successfully

Important:
Your solution must be fully reproducible locally, independent of GitHub Actions.
The same commands executed in the pipeline must work locally without modifications.

## Part 9 — Observability
Expected:
- structured logging
- error handling
- clear and meaningful messages

## Execution Environment
Your solution will be executed in:
- Ubuntu VM
- Docker environment
- CI/CD pipeline

You must provide a script to run your solution locally: 
- run_pipeline.sh or 
- Makefile 

This script must: 
- run the pipeline 
- run tests 
- start the API

## Deliverables
You must provide:
- complete source code
- FastAPI application
- Dockerfile
- CI/CD pipeline configuration
- prompts.md
- README.md with full instructions

README must include:
- how to run locally
- how to run with Docker
- how to execute the pipeline
- how to access the API
- explanation of technical decisions

## Evaluation Criteria
Technical
- data engineering quality
- code organization
- technical decisions
- data modeling

Architecture
- separation of responsibilities
- level of decoupling
- project structure

Software Engineering
- code quality
- testing
- robustness

Cloud & Infrastructure
- organization
- execution
- containerization

API
- design
- clarity
- consistency

AI / Prompt Engineering
- structured usage
- quality of prompts
- applied reasoning

Problem Solving
- ability to deal with ambiguity
- clarity of thinking
- justification of decisions