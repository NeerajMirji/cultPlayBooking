import os
from dotenv import load_dotenv
from app import update_github_secret, notify

# Load environment variables from .env file
load_dotenv()

print("Attempting to update a test secret in your GitHub repository...")

# A test secret name and value
test_secret_name = "TEST_SECRET"
test_secret_value = "neeraj"

# Call the function from your app
update_github_secret(test_secret_name, test_secret_value)

print("\nTest finished. Check your Telegram and GitHub repository.")

