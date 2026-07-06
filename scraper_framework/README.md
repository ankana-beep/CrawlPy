# Scraper Framework

A modular scraping framework scaffolded for Python.

## Structure

- `config/` - Settings for proxies, user agents, keys, and DB credentials
- `core/` - Client and parser layers for network/browser and content extraction
- `services/` - Site-specific orchestration logic
- `db/` - Database connection and models
- `utils/` - Helper utilities and logger

## Usage

```bash
python -m scraper_framework.main --site site_a --target https://example.com/api
```

## Requirements

Install dependencies:

```bash
pip install -r scraper_framework/requirements.txt
```
