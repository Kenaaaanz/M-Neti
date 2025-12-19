#!/usr/bin/env bash
# Exit on error
set -o errexit

apt-get update && apt-get install -y \
    python3-dev \
    build-essential \
    libpq-dev \
    libjpeg-dev \
    zlib1g-dev

# Install dependencies
pip install --upgrade pip
pip install --no-cache-dir -r requirements.txt

# Collect static files
python manage.py collectstatic --noinput

# Apply database migrations
python manage.py migrate