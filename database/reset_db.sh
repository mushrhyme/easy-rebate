#!/bin/bash

# Default values
DB_HOST=${DB_HOST:-"localhost"}
DB_PORT=${DB_PORT:-"5432"}
DB_NAME=${DB_NAME:-"rebate_db"}
DB_USER=${DB_USER:-"postgres"}
DB_PASSWORD=${DB_PASSWORD:-""}

# Export password for psql/createdb/dropdb
export PGPASSWORD=$DB_PASSWORD

echo "WARNING: This script will DROP the database '$DB_NAME' and recreate it."
echo "         Host: $DB_HOST:$DB_PORT"
echo "         User: $DB_USER"
echo ""
read -p "Are you sure you want to continue? (y/N) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Aborted."
    exit 1
fi

echo "Dropping database '$DB_NAME'..."
dropdb -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" --if-exists "$DB_NAME"

if [ $? -ne 0 ]; then
    echo "Failed to drop database."
    exit 1
fi

echo "Creating database '$DB_NAME'..."
createdb -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" "$DB_NAME"

if [ $? -ne 0 ]; then
    echo "Failed to create database."
    exit 1
fi

echo "Initializing database schema..."
psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -f database/init_database.sql

if [ $? -ne 0 ]; then
    echo "Failed to initialize database schema."
    exit 1
fi

echo "Database reset complete!"
