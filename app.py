import os
import fitz  # PyMuPDF
import math
import threading
import time
import json
import random

# New imports for login and 2FA
import io
import base64
import pyotp
import qrcode
from werkzeug.security import generate_password_hash, check_password_hash
from flask import Flask, render_template, send_file, url_for, abort, request, redirect, session, flash
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user

# --- Configuration ---
# IMPORTANT: PDF_FOLDERS MUST point to the ORIGINAL locations
PDF_FOLDERS = [
    '/pdfs/long',  # CHANGE ME - Path for source_0
    '/pdfs/short'  # CHANGE ME - Path for source_1
]
# PDF_FOLDERS validation logic (keep as before)
valid_folders = []
if isinstance(PDF_FOLDERS, list):
    for i, folder_path in enumerate(PDF_FOLDERS):
        if os.path.isdir(folder_path): valid_folders.append(folder_path)
        else: print(f"ERROR: PDF_FOLDER index {i} ('{folder_path}') is not a valid directory.")
else: print("ERROR: PDF_FOLDERS must be a list."); exit(1)
if not valid_folders: print("ERROR: No valid PDF source folders found in PDF_FOLDERS."); exit(1)
PDF_FOLDERS = valid_folders

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
STATIC_FOLDER = os.path.join(BASE_DIR, 'static')
THUMBNAIL_DIR = os.path.join(STATIC_FOLDER, 'thumbnails')
ALLOWED_EXTENSIONS = {'.pdf'}
PER_PAGE = 20
TAG_FILE_PATH = os.path.join(BASE_DIR, 'tags.json')
USER_FILE_PATH = os.path.join(BASE_DIR, 'users.json') # Path to users file

# --- Flask App Initialization ---
app = Flask(__name__)
# SECRET_KEY is required for sessions and flashing messages
app.config['SECRET_KEY'] = 'ola.123#'

# --- Flask-Login and User Management ---
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login' # Redirect to /login if user is not authenticated

class User(UserMixin):
    def __init__(self, username, password_hash, otp_secret=None, otp_enabled=False):
        self.id = username
        self.password_hash = password_hash
        self.otp_secret = otp_secret
        self.otp_enabled = otp_enabled

def load_users():
    if not os.path.exists(USER_FILE_PATH):
        return {}
    with open(USER_FILE_PATH, 'r') as f:
        return json.load(f)

def save_users(users):
    with open(USER_FILE_PATH, 'w') as f:
        json.dump(users, f, indent=4)

def get_user_by_username(username):
    users = load_users()
    user_data = users.get(username)
    if user_data:
        return User(
            username,
            user_data.get('password_hash'),
            user_data.get('otp_secret'),
            user_data.get('otp_enabled', False)
        )
    return None

@login_manager.user_loader
def load_user(user_id):
    return get_user_by_username(user_id)

# --- Helper functions (sync_pdfs, etc.) ---
# Your existing helper functions like `ensure_dirs`, `generate_thumbnail`, `sync_pdfs`,
# `run_background_sync`, `load_tags`, `get_all_unique_tags`, and `scan_existing_pdfs`
# go here. They do not need to be changed from the previous version where PDFs
# were served from their original locations.
# ... PASTE YOUR HELPER FUNCTIONS HERE ...
def ensure_dirs():
    # Only need to ensure thumbnail dir exists now
    os.makedirs(THUMBNAIL_DIR, exist_ok=True)
    # os.makedirs(PDF_SERVE_DIR, exist_ok=True) # Not needed for PDFs

# generate_thumbnail function remains EXACTLY the same as before
def generate_thumbnail(pdf_src_path, thumb_dest_path):
    os.makedirs(os.path.dirname(thumb_dest_path), exist_ok=True)
    try:
        # Check if source exists before trying to open
        if not os.path.isfile(pdf_src_path):
             print(f"Thumbnail generation skipped: Source PDF not found at {pdf_src_path}")
             return False
        doc = fitz.open(pdf_src_path)
        if not doc or doc.page_count == 0:
            if doc: doc.close()
            print(f"Thumbnail generation failed: Empty or invalid PDF at {pdf_src_path}")
            return False
        page = doc.load_page(0)
        zoom = 2
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        pix.save(thumb_dest_path)
        doc.close()
        return True
    except Exception as e:
        print(f"Error generating thumbnail for {os.path.basename(pdf_src_path)} -> {thumb_dest_path}: {e}")
        if os.path.exists(thumb_dest_path):
            try: os.remove(thumb_dest_path)
            except: pass
        return False


# MODIFIED: sync_pdfs - No longer copies PDFs, only generates thumbnails and cleans them up
def sync_pdfs():
    print("Background sync: Starting scan for thumbnail generation/cleanup...")
    ensure_dirs() # Ensures thumbnail dir exists
    processed_files_map = {} # Keep track of existing source PDFs for thumbnail cleanup
    thumbnails_generated_total = 0

    for i, folder_path in enumerate(PDF_FOLDERS): # Iterate through ORIGINAL PDF folders
        folder_id = f"source_{i}"
        print(f"Background sync: Scanning source {i} ({folder_path}) for thumbnails...")
        thumbnails_generated_this_folder = 0
        try:
            # Check if source folder exists before listing directory
            if not os.path.isdir(folder_path):
                 print(f"Background sync: Error - Source folder {i} ('{folder_path}') not found during scan.")
                 continue # Skip to next folder

            for filename in os.listdir(folder_path):
                name, ext = os.path.splitext(filename)
                if ext.lower() not in ALLOWED_EXTENSIONS: continue

                source_pdf_path = os.path.join(folder_path, filename)
                # Check if it's actually a file before proceeding
                if not os.path.isfile(source_pdf_path): continue

                processed_files_map[(folder_id, filename)] = True # Mark source PDF as existing

                # --- Thumbnail Logic (Mostly Unchanged) ---
                thumbnail_subdir = os.path.join(THUMBNAIL_DIR, folder_id)
                thumbnail_filename = name + '.png'
                thumbnail_path = os.path.join(thumbnail_subdir, thumbnail_filename)
                os.makedirs(thumbnail_subdir, exist_ok=True) # Ensure specific thumb subdir exists

                generate_thumb = True
                if os.path.exists(thumbnail_path):
                    try:
                        # Regenerate thumb if source PDF is newer than existing thumbnail
                        if os.path.getmtime(source_pdf_path) <= os.path.getmtime(thumbnail_path):
                            generate_thumb = False
                    except FileNotFoundError:
                        generate_thumb = True # Source or thumb missing, regenerate

                if generate_thumb:
                    if generate_thumbnail(source_pdf_path, thumbnail_path):
                        thumbnails_generated_this_folder += 1
                # --- End Thumbnail Logic ---

            print(f"Background sync: Source {i} finished. Thumbs generated/updated: {thumbnails_generated_this_folder}")
            thumbnails_generated_total += thumbnails_generated_this_folder

        except Exception as e:
            print(f"Background sync: An unexpected error occurred scanning source {i} ('{folder_path}'): {e}")

    # --- Cleanup ONLY Thumbnails ---
    items_removed = 0
    print("Background sync: Starting cleanup of thumbnail folder...")
    if os.path.exists(THUMBNAIL_DIR):
        for folder_id in os.listdir(THUMBNAIL_DIR):
            folder_id_path = os.path.join(THUMBNAIL_DIR, folder_id)
            if not os.path.isdir(folder_id_path): continue

            for item in os.listdir(folder_id_path):
                item_path = os.path.join(folder_id_path, item)
                # Only check .png files in thumbnail directories
                if os.path.splitext(item)[1].lower() == '.png':
                    # Derive the expected original PDF filename
                    original_pdf_filename = os.path.splitext(item)[0] + '.pdf'
                    check_key = (folder_id, original_pdf_filename)

                    # If the original PDF was NOT found in the scan, remove the thumbnail
                    if check_key not in processed_files_map:
                        try:
                            os.remove(item_path)
                            items_removed += 1
                            print(f"Background sync: Removed orphan thumbnail {item_path}")
                        except Exception as e:
                            print(f"Background sync: Error removing thumbnail {item_path}: {e}")

    if items_removed > 0:
        print(f"Background sync: Removed {items_removed} orphan thumbnails.")
    print(f"Background sync: Finished FULL run. Total Thumbs generated/updated: {thumbnails_generated_total}")


# run_background_sync function remains EXACTLY the same as before
def run_background_sync():
    print("Attempting to start background sync process...")
    if is_syncing_lock.acquire(blocking=False):
        print("Acquired sync lock. Starting background sync.")
        try:
            sync_pdfs() # Calls the modified sync function
        except Exception as e:
            print(f"Error during background sync execution: {e}")
        finally:
            is_syncing_lock.release()
            print("Background sync finished and lock released.")
    else:
        print("Sync process already running in another thread.")


# load_tags function remains EXACTLY the same as before
def load_tags():
    """Loads tag data from tags.json."""
    if not os.path.exists(TAG_FILE_PATH):
        # print(f"Tag file not found: {TAG_FILE_PATH}") # Less verbose
        return {}
    try:
        with open(TAG_FILE_PATH, 'r', encoding='utf-8') as f:
            tags_data = json.load(f)
            if not isinstance(tags_data, dict):
                print(f"Error: {TAG_FILE_PATH} does not contain a valid JSON dictionary.")
                return {}
            return tags_data
    except json.JSONDecodeError as e:
        print(f"Error decoding JSON from {TAG_FILE_PATH}: {e}")
        return {}
    except Exception as e:
        print(f"Error reading tag file {TAG_FILE_PATH}: {e}")
        return {}

# get_all_unique_tags function remains EXACTLY the same as before
def get_all_unique_tags():
    """Reads the tag file and returns a sorted list of unique tags."""
    tags_data = load_tags()
    unique_tags = set()
    for tag_list in tags_data.values():
        if isinstance(tag_list, list):
            for tag in tag_list:
                if isinstance(tag, str) and tag.strip():
                    unique_tags.add(tag.strip())
    return sorted(list(unique_tags))


# MODIFIED: scan_existing_pdfs - Scans ORIGINAL folders, not PDF_SERVE_DIR
def scan_existing_pdfs():
    """
    FAST scan: Checks ORIGINAL PDF folders for files and MERGES tag data.
    """
    ensure_dirs() # Ensures thumbnail dir exists
    pdf_files_info = []
    loaded_tags = load_tags() # Load tags once

    try:
        # Iterate through the configured ORIGINAL PDF folders
        for i, folder_path in enumerate(PDF_FOLDERS):
            folder_id = f"source_{i}"
            # print(f"Scanning folder: {folder_path} (ID: {folder_id})") # Debug print

            # Check if source folder exists before listing directory
            if not os.path.isdir(folder_path):
                 print(f"Scan warning: Source folder '{folder_path}' (ID: {folder_id}) not found.")
                 continue # Skip to next folder

            for filename in os.listdir(folder_path):
                name, ext = os.path.splitext(filename)
                if ext.lower() not in ALLOWED_EXTENSIONS: continue

                original_pdf_path = os.path.join(folder_path, filename)
                # Check if it's a file before adding to list
                if not os.path.isfile(original_pdf_path): continue

                # --- Thumbnail Path Calculation (remains similar) ---
                thumbnail_filename = name + '.png'
                thumbnail_path = os.path.join(THUMBNAIL_DIR, folder_id, thumbnail_filename)
                # Relative path used in HTML templates (points to static thumbnail)
                thumbnail_rel_path = os.path.join('thumbnails', folder_id, thumbnail_filename).replace('\\', '/')
                # --- End Thumbnail Path ---

                # --- Get Tags ---
                pdf_key = f"{folder_id}/{filename}" # Key remains the same structure
                pdf_tags = loaded_tags.get(pdf_key, []) # Get tags or empty list
                # --- End Get Tags ---

                pdf_files_info.append({
                    'filename': filename,
                    'folder_id': folder_id, # Like 'source_0'
                    # Path to the thumbnail in the static dir
                    'thumbnail_rel_path': thumbnail_rel_path if os.path.exists(thumbnail_path) else None,
                    # URL still points to the view_pdf route
                    'view_url': url_for('view_pdf', folder_id=folder_id, filename=filename),
                    'tags': pdf_tags
                })

    except Exception as e:
        print(f"Error scanning original PDF folders: {e}")
        return [] # Return empty list on error

    pdf_files_info.sort(key=lambda x: x['filename'])
    # print(f"Scan complete. Found {len(pdf_files_info)} processable PDFs.") # Debug print
    return pdf_files_info


# --- Authentication Routes ---

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = get_user_by_username(username)

        if user and check_password_hash(user.password_hash, password):
            if user.otp_enabled:
                # If 2FA is enabled, don't log in yet.
                # Store user ID in session and redirect to 2FA verification page.
                session['2fa_user_id'] = user.id
                return redirect(url_for('verify_2fa'))
            else:
                # If 2FA is not enabled, log in directly.
                login_user(user)
                flash('Logged in successfully.', 'success')
                return redirect(url_for('index'))
        else:
            flash('Invalid username or password.', 'danger')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'success')
    return redirect(url_for('login'))

@app.route('/verify-2fa', methods=['GET', 'POST'])
def verify_2fa():
    user_id = session.get('2fa_user_id')
    if not user_id:
        return redirect(url_for('login'))

    if request.method == 'POST':
        user = get_user_by_username(user_id)
        otp = request.form.get('otp')
        totp = pyotp.TOTP(user.otp_secret)

        if totp.verify(otp):
            # OTP is correct, log the user in
            session.pop('2fa_user_id', None) # Clean up session
            login_user(user)
            flash('Logged in successfully.', 'success')
            return redirect(url_for('index'))
        else:
            flash('Invalid 2FA code.', 'danger')

    return render_template('verify_2fa.html')

@app.route('/setup-2fa', methods=['GET', 'POST'])
@login_required
def setup_2fa():
    if current_user.otp_enabled:
        return render_template('setup_2fa.html')

    if 'otp_secret' not in session:
        session['otp_secret'] = pyotp.random_base32()

    secret = session['otp_secret']
    otp_uri = pyotp.totp.TOTP(secret).provisioning_uri(
        name=current_user.id,
        issuer_name="My PDF App"
    )

    if request.method == 'POST':
        otp = request.form.get('otp')
        totp = pyotp.TOTP(secret)

        if totp.verify(otp):
            # OTP is correct, save the secret to the user file
            users = load_users()
            users[current_user.id]['otp_secret'] = secret
            users[current_user.id]['otp_enabled'] = True
            save_users(users)
            
            session.pop('otp_secret', None) # Clean up session
            flash('2FA enabled successfully!', 'success')
            return redirect(url_for('index'))
        else:
            flash('Invalid verification code.', 'danger')

    # Generate QR code image in memory
    img = qrcode.make(otp_uri)
    buf = io.BytesIO()
    img.save(buf)
    buf.seek(0)
    qr_code_image = base64.b64encode(buf.getvalue()).decode('ascii')

    return render_template('setup_2fa.html', qr_code_image=qr_code_image)


# --- Protected Application Routes ---

# Add the @login_required decorator to every route you want to protect
@app.route('/')
@login_required
def index():
    """Main page: Sidemenu, tags, quick load, pagination, search, background sync."""
    # print("\n--- New Request ---") # Less verbose
    # print(f"Request Arguments: {request.args}") # Less verbose

    # Start background sync for thumbnails (non-blocking)
    sync_thread = threading.Thread(target=run_background_sync, daemon=True)
    sync_thread.start()

    search_query = request.args.get('q', '').strip()
    folder_filter = request.args.get('folder', None)
    tag_filter = request.args.get('tag', None)
    # print(f"Filters - Folder: {folder_filter}, Tag: {tag_filter}, Search: '{search_query}'")

    # Get list by scanning original dirs + merging tags
    available_pdfs = scan_existing_pdfs()
    # print(f"Total available PDFs found by scan: {len(available_pdfs)}")

    filtered_list = available_pdfs

    # Apply Folder Filter
    if folder_filter and folder_filter.startswith('source_'):
        filtered_list = [pdf for pdf in filtered_list if pdf['folder_id'] == folder_filter]

    # Apply Tag Filter
    if tag_filter:
        filtered_list = [pdf for pdf in filtered_list if tag_filter in pdf.get('tags', [])]

    # Apply Search Filter
    if search_query:
        filtered_list = [pdf for pdf in filtered_list if search_query.lower() in pdf['filename'].lower()]

    total_items = len(filtered_list)
    # print(f"Total items AFTER ALL filtering: {total_items}")

    # Pagination Logic
    page = request.args.get('page', 1, type=int)
    total_pages = math.ceil(total_items / PER_PAGE) if total_items > 0 else 1
    page = max(1, min(page, total_pages)) if total_pages > 0 else 1
    start_index = (page - 1) * PER_PAGE
    end_index = start_index + PER_PAGE
    pdfs_for_page = filtered_list[start_index:end_index]
    # print(f"Pagination: Total pages={total_pages}, Current page={page}, Items on this page={len(pdfs_for_page)}")

    return render_template('index.html',
                           pdfs=pdfs_for_page,
                           page=page,
                           total_pages=total_pages,
                           search_query=search_query,
                           folder_filter=folder_filter,
                           tag_filter=tag_filter)


@app.route('/tags')
@login_required
def tags_page():
    """Displays all unique tags as clickable buttons."""
    print("--- Request for /tags page ---")
    all_tags = get_all_unique_tags()
    print(f"Found {len(all_tags)} unique tags.")
    return render_template('tags.html', tags=all_tags)


@app.route('/random')
@login_required
def random_options_page():
    """Displays buttons to choose the pool for random selection."""
    print("--- Request /random ---")
    return render_template('random_options.html')

@app.route('/random/select')
@login_required
def select_random_pdf():
    """Selects a random PDF based on the chosen pool and redirects."""
    print("--- Request /random/select ---")
    pool = request.args.get('pool', 'all')
    print(f"Random pool requested: {pool}")

    available_pdfs = scan_existing_pdfs() # Scans original folders now
    if not available_pdfs:
        print("No PDFs found by scan for random selection.")
        return render_template('message.html', title="No PDFs Available", message="Could not find any source PDFs. Please check configuration or wait for processing.")

    # Filter based on the pool
    if pool == 'source_0':
        pdf_pool = [pdf for pdf in available_pdfs if pdf['folder_id'] == 'source_0']
    elif pool == 'source_1':
        pdf_pool = [pdf for pdf in available_pdfs if pdf['folder_id'] == 'source_1']
    else: # Includes 'all'
        pdf_pool = available_pdfs

    if not pdf_pool:
        print(f"No PDFs found in the selected pool '{pool}'.")
        return render_template('message.html', title="No PDFs Found", message=f"Could not find any PDFs in the '{pool if pool != 'all' else 'selected'}' pool.")

    try:
        chosen_pdf = random.choice(pdf_pool)
        print(f"Randomly selected: {chosen_pdf['folder_id']}/{chosen_pdf['filename']}")
        # Redirect to the view page for the chosen PDF
        return redirect(url_for('view_pdf',
                                folder_id=chosen_pdf['folder_id'],
                                filename=chosen_pdf['filename']))
    except IndexError:
         print("Error: random.choice failed on empty pool (logic error).")
         return render_template('message.html', title="Error", message="An unexpected error occurred while selecting a random PDF.")


@app.route('/view/<folder_id>/<path:filename>')
@login_required
def view_pdf(folder_id, filename):
    # 1. Validate folder_id format
    if not folder_id or not folder_id.startswith('source_'):
        print(f"Invalid folder_id format requested: {folder_id}")
        abort(404)

    # 2. Map folder_id to original source directory path from PDF_FOLDERS list
    try:
        folder_index = int(folder_id.split('_')[-1])
        # Check index bounds against the *currently loaded* PDF_FOLDERS list
        if folder_index < 0 or folder_index >= len(PDF_FOLDERS):
             print(f"Invalid folder index derived from folder_id: {folder_index} (out of bounds for {len(PDF_FOLDERS)} folders)")
             abort(404)
        original_folder_path = PDF_FOLDERS[folder_index]
        # Check if the mapped path actually exists and is a directory
        if not os.path.isdir(original_folder_path):
             print(f"Configuration Error: Source directory for index {folder_index} does not exist or is not a directory: {original_folder_path}")
             abort(500, description="Server configuration error: Source directory not found.") # 500 as it's a server config issue
    except (ValueError, IndexError):
        print(f"Could not derive valid index from folder_id: {folder_id}")
        abort(404)

    # 3. Validate filename extension (check against ALLOWED_EXTENSIONS)
    name, ext = os.path.splitext(filename)
    if ext.lower() not in ALLOWED_EXTENSIONS:
        print(f"Disallowed file extension requested: {ext} for file {filename}")
        abort(404)

    # 4. Construct the FULL path to the ORIGINAL PDF file
    # Security Note: We rely on folder_id mapping and filename validation.
    # Further checks could ensure filename doesn't contain '..' etc., but
    # os.path.join and later os.path.isfile provide good baseline safety here.
    full_original_pdf_path = os.path.join(original_folder_path, filename)

    # 5. IMPORTANT: Check if the constructed path points to an existing FILE
    if not os.path.isfile(full_original_pdf_path):
         print(f"File not found at constructed path: {full_original_pdf_path}")
         abort(404, description="Requested PDF file not found at the source location.")

    # 6. Use send_file to serve the original file
    try:
        print(f"Attempting to serve original file: {full_original_pdf_path}")
        return send_file(
            full_original_pdf_path,
            mimetype='application/pdf',
            as_attachment=False # Try to display inline in the browser
        )
    except FileNotFoundError: # Should be caught by isfile check, but good practice
        print(f"Error: FileNotFoundError during send_file (unexpected): {full_original_pdf_path}")
        abort(404, description="PDF file not found.")
    except Exception as e:
        # Log the actual error for server-side debugging
        print(f"Error serving original file {full_original_pdf_path}: {e}")
        # Provide a generic error to the client
        abort(500, description="Server error while trying to serve the PDF file.")


# --- Run the App ---
if __name__ == '__main__':
    ensure_dirs()
    print("Starting initial background sync for thumbnails...")
    initial_sync_thread = threading.Thread(target=run_background_sync, daemon=True)
    initial_sync_thread.start()
    print(f"Monitoring ORIGINAL PDF folders: {PDF_FOLDERS}")
    app.run(host='0.0.0.0', port=5000, debug=True)