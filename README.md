# GitHub Issues Gateway Service

**Author:** Byeonggwan Cho  
**Course:** CMPE 272 – Enterprise Software Platforms  

A lightweight, high-performance FastAPI gateway service that wraps the GitHub REST API v3 for single-repository issue management. It features secure real-time GitHub Webhook handling, HMAC SHA-256 signature verification, and full compliance with OpenAPI 3.1 specifications.

---

## 1. Environment Variables & Setup

This service relies on environment variables for configuration. Never commit the actual `.env` file to source control.

1. Copy the provided `.env.example` template to create your local `.env` file:
   ```bash
   cp .env.example .env