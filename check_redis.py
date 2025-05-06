import sys
import os
from redis import Redis, exceptions

# Load environment variables if needed (though URL is passed as arg)
# from dotenv import load_dotenv
# load_dotenv()

def check_redis_connection(url):
    print(f"Attempting to connect to Redis at: {url}")
    try:
        # Attempt to create a connection and ping the server
        redis_conn = Redis.from_url(url, socket_connect_timeout=2) # Short timeout
        redis_conn.ping()
        print("Redis connection successful.")
        return True
    except exceptions.ConnectionError as e:
        print(f"Redis connection failed: {e}")
        return False
    except Exception as e:
        print(f"An unexpected error occurred while checking Redis: {e}")
        return False

if __name__ == "__main__":
    # Default URL if no argument is provided
    redis_url_to_check = "redis://localhost:6379"
    if len(sys.argv) > 1:
        redis_url_to_check = sys.argv[1]
    
    # Fallback to environment variable if argument is empty/invalid? (Optional)
    # if not redis_url_to_check:
    #     redis_url_to_check = os.getenv('REDIS_URL', 'redis://localhost:6379')

    if check_redis_connection(redis_url_to_check):
        sys.exit(0) # Exit code 0 for success
    else:
        sys.exit(1) # Exit code 1 for failure