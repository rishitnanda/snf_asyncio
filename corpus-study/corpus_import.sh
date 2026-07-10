#!/bin/bash

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Define the target directory and ensure it exists
TARGET_DIR="$SCRIPT_DIR/repo_src"
mkdir -p "$TARGET_DIR"

# Move into the target directory
cd "$TARGET_DIR" || { echo "Failed to enter $TARGET_DIR"; exit 1; }

# List of repositories to clone
# Note: Removed duplicate entry for tortoise-orm
repos=(
    "https://github.com/aio-libs/aiohttp"
    "https://github.com/encode/httpx"
    "https://github.com/sonic182/aiosonic"
    "https://github.com/huge-success/sanic"
    "https://github.com/fastapi/fastapi"
    "https://github.com/pallets/quart"
    "https://github.com/MagicStack/asyncpg"
    "https://github.com/aio-libs/aiomysql"
    "https://github.com/aio-libs/aiopg"
    "https://github.com/aio-libs/aioredis"
    "https://github.com/mongodb/motor"
    "https://github.com/encode/databases"
    "https://github.com/python-arq/arq"
    "https://github.com/taskiq-python/taskiq"
    "https://github.com/python-websockets/websockets"
    "https://github.com/pytest-dev/pytest-asyncio"
    "https://github.com/Martiusweb/asynctest"
    "https://github.com/Tinche/aiofiles"
    "https://github.com/alexdelorenzo/aiopath"
    "https://github.com/tomplus/kubernetes_asyncio"
    "https://github.com/aio-libs/aiobotocore"
    "https://github.com/python-trio/trio"
    "https://github.com/mosquito/aio-pika"
    "https://github.com/aio-libs/aiokafka"
    "https://github.com/robinhood/faust"
    "https://github.com/tarsil/asyncz"
    "https://github.com/agronholm/apscheduler"
    "https://github.com/sqlalchemy/sqlalchemy"
    "https://github.com/tortoise/tortoise-orm"
    "https://github.com/aio-libs/aiocache"
    "https://github.com/redis/redis-py"
    "https://github.com/long2ice/asyncmy"
    "https://github.com/elastic/elasticsearch-py"
)

# Clone each repository
for repo in "${repos[@]}"; do
    repo_name=$(basename "$repo")
    if [ ! -d "$repo_name" ]; then
        echo "Cloning $repo..."
        git clone "$repo"
    else
        echo "Skipping $repo_name (already exists)."
    fi
done

# Handle FastAPI examples
# We use SCRIPT_DIR to ensure it creates the folder in the base directory, not inside repo_src
FASTAPI_DEST="$TARGET_DIR/fastapi_examples"
if [ -d "fastapi" ]; then
    mkdir -p "$FASTAPI_DEST"
    cp -r "fastapi/docs_src/"* "$FASTAPI_DEST/"
    echo "FastAPI examples copied to $FASTAPI_DEST"
else
    echo "Error: FastAPI directory not found, skipping example copy."
fi

echo "------------------------------------------"
echo "Corpus preparation complete."
echo "Repositories are located in: $TARGET_DIR"