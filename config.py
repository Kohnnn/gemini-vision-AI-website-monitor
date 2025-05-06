import os
from redis import Redis
from dotenv import load_dotenv
import logging

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
handler = logging.FileHandler('backend_error.log')
handler.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
logger = logging.getLogger(__name__)
logger.addHandler(handler)
logger.setLevel(logging.DEBUG)

# --- Redis URL Setup (global, Docker/Windows compatible) ---
redis_url = os.getenv('REDIS_URL')
if not redis_url or not isinstance(redis_url, str) or not redis_url.strip():
    # Docker Redis connection by default
    redis_url = 'redis://redis:6379'
    
    # Fall back to localhost if not in Docker environment
    if os.getenv('DOCKER_ENV') != 'true':
        redis_url = 'redis://localhost:6379'
        
redis_url = redis_url.strip()
logger.debug(f"Using redis_url: '{redis_url}'")

# Define a function to get Redis connection (instead of connecting at import time)
def get_redis_connection():
    """Get a Redis connection using the configured URL."""
    try:
        conn = Redis.from_url(redis_url)
        conn.ping()  # Test connection
        logger.debug(f"Redis connection successful")
        return conn
    except Exception as e:
        logger.error(f"Redis connection failed: {e}")
        return None  # Return None on failure so app can handle this case

# For backward compatibility - this will be None and only initialized when get_redis_connection is called
redis_conn = None 