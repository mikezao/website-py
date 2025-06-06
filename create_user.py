import json
import os
from werkzeug.security import generate_password_hash

USER_FILE_PATH = 'users.json'

def create_or_update_user():
    """A command-line utility to add or update a user in users.json."""
    print("--- User Creation/Update Tool ---")
    print("This will add a new user or overwrite an existing user's password and 2FA settings.")

    # Get username and password from user input
    username = input("Enter username: ").strip()
    if not username:
        print("Error: Username cannot be empty.")
        return

    password = input(f"Enter new password for '{username}': ")
    if not password:
        print("Error: Password cannot be empty.")
        return

    # Generate the secure password hash
    password_hash = generate_password_hash(password)
    print(f"\nGenerated new secure hash for the password.")

    # Load existing users or create a new dictionary
    if os.path.exists(USER_FILE_PATH):
        try:
            with open(USER_FILE_PATH, 'r') as f:
                users = json.load(f)
        except json.JSONDecodeError:
            print(f"Warning: '{USER_FILE_PATH}' is corrupted or empty. Starting fresh.")
            users = {}
    else:
        print(f"Creating new user file: '{USER_FILE_PATH}'")
        users = {}

    # Create or update the user data (resets 2FA on password change)
    users[username] = {
        "password_hash": password_hash,
        "otp_secret": None,
        "otp_enabled": False
    }

    # Save the updated user data back to the file
    try:
        with open(USER_FILE_PATH, 'w') as f:
            json.dump(users, f, indent=4)
        print(f"\nSuccessfully created/updated user '{username}' in {USER_FILE_PATH}.")
        print("You can now log in with these credentials in the web app.")
    except Exception as e:
        print(f"\nAn error occurred while writing to the file: {e}")

if __name__ == '__main__':
    create_or_update_user()