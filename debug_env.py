import os
import sys
from dotenv import load_dotenv

def examine_env_file(env_path='.env'):
    """Examine .env file for null bytes and other issues"""
    try:
        print(f"Examining {env_path} for issues...")
        
        # Check if file exists
        if not os.path.exists(env_path):
            print(f"Error: {env_path} does not exist")
            return False
            
        # Read raw content to check for null bytes
        with open(env_path, 'rb') as f:
            content = f.read()
            
        # Check for null bytes
        if b'\x00' in content:
            print(f"Error: Null bytes detected in {env_path}")
            
            # Find and report positions of null bytes
            positions = [i for i, byte in enumerate(content) if byte == 0]
            print(f"Null bytes found at positions: {positions}")
            
            # Create safe version
            safe_content = content.replace(b'\x00', b'')
            with open(f"{env_path}.safe", 'wb') as f:
                f.write(safe_content)
            print(f"Created clean version at {env_path}.safe")
            return False
        
        # Try loading with dotenv
        try:
            load_dotenv(env_path)
            print(f"Successfully loaded {env_path} with dotenv")
            
            # Print loaded environment variables for debugging
            env_vars = {}
            with open(env_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        if '=' in line:
                            key, value = line.split('=', 1)
                            env_vars[key] = value
            
            print("Environment variables found:")
            for key, value in env_vars.items():
                # Show value safely, mask secrets
                if any(secret in key.lower() for secret in ['key', 'password', 'token', 'secret']):
                    masked_value = value[:3] + '****' if len(value) > 3 else '****'
                    print(f"  {key}={masked_value}")
                else:
                    print(f"  {key}={value}")
            
            return True
        except Exception as e:
            print(f"Error loading with dotenv: {e}")
            return False
            
    except Exception as e:
        print(f"Unexpected error examining {env_path}: {e}")
        return False

if __name__ == "__main__":
    # Check default .env file
    if not examine_env_file():
        # If default file has issues, try with .env.new if it exists
        if os.path.exists('.env.new'):
            print("\nTrying with .env.new instead...")
            examine_env_file('.env.new') 