import os
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, get_flashed_messages, send_from_directory, Response
from flask_sqlalchemy import SQLAlchemy
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime, timedelta
from dotenv import load_dotenv
import asyncio
import random
import requests as ext_requests
from sqlalchemy.orm import Session
import re
from rq import Queue
from redis import Redis
import threading
from config import redis_url, get_redis_connection  # Import redis_url and the connection function
import time # Import the time module
import logging # Import logging
import atexit # Import atexit for shutdown hook
import ssl
import socket
from flask_migrate import Migrate  # Add Flask-Migrate
import glob
import json

# Add caching library
from functools import lru_cache
import io
from PIL import Image

# Load environment variables
load_dotenv()

# Initialize Flask app and configuration
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///ai_website_monitor.db'
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'devsecret')
app.config['DATA_DIR'] = os.path.join(os.path.dirname(__file__), 'data')  # Add DATA_DIR config
db = SQLAlchemy(app)
migrate = Migrate(app, db)  # Setup Flask-Migrate

# Global variable for queue - will be initialized in create_app
queue = None

# Cache configuration
CACHE_TIMEOUT = 3600  # Cache timeout in seconds (1 hour)
IMAGE_QUALITY = 85  # JPEG quality for optimized images
MAX_WIDTH = 1600  # Maximum image width
ENABLE_IMAGE_OPTIMIZATION = True  # Toggle for image optimization

# LRU cache for optimized images (stores most recently used items)
@lru_cache(maxsize=50)
def get_optimized_image(path, max_width=MAX_WIDTH, quality=IMAGE_QUALITY):
    """Cache and optimize images for faster loading."""
    try:
        img = Image.open(path)
        # Check if optimization needed
        width, height = img.size
        if width > max_width:
            # Calculate new height while maintaining aspect ratio
            new_height = int(height * (max_width / width))
            img = img.resize((max_width, new_height), Image.LANCZOS)
        
        # Save to memory buffer
        output = io.BytesIO()
        format = img.format if img.format else 'JPEG'
        # Save as JPEG with compression if it's a color image
        if img.mode in ('RGB', 'RGBA'):
            if format == 'PNG' and 'transparency' in img.info:
                # Preserve PNG transparency
                img.save(output, format='PNG', optimize=True)
            else:
                img = img.convert('RGB')
                img.save(output, format='JPEG', quality=quality, optimize=True)
        else:
            img.save(output, format=format)
        output.seek(0)
        return output.getvalue(), f"image/{format.lower()}"
    except Exception as e:
        app.logger.error(f"Image optimization error: {e}")
        # Return None if optimization fails, will fall back to original
        return None, None

# Create scheduler instance but don't start it yet
scheduler = BackgroundScheduler()

# Register scheduler shutdown hook
atexit.register(lambda: scheduler.shutdown())

# Configure logging
logging.basicConfig(level=logging.INFO) # Set base level to INFO
handler = logging.FileHandler('backend_error.log') # Log to file
handler.setLevel(logging.DEBUG) # Log DEBUG and above to file
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
app.logger.addHandler(handler) # Add file handler to Flask logger
app.logger.setLevel(logging.DEBUG) # Ensure Flask logger captures DEBUG

# --- Add Route to Serve Data Files ---
DATA_FOLDER = os.path.join(os.path.dirname(__file__), 'data')

# --- Custom RQ Worker for Windows ---
from rq import SimpleWorker
from rq.timeouts import TimerDeathPenalty

class WindowsSimpleWorker(SimpleWorker):
    death_penalty_class = TimerDeathPenalty

@app.route('/data/<path:filename>')
def data(filename):
    """Serve files from the data directory with proper security checks.
    Alternative route to handle '/data/' path format."""
    return serve_data_file(filename)

@app.route('/serve_data_file/<path:filename>')
def serve_data_file(filename):
    """Serve files from the data directory with proper security checks."""
    app.logger.debug(f"Requested data file: {filename}")
    
    # Remove 'data/' or 'data\' prefix if present in the filename
    if filename.startswith('data/') or filename.startswith('data\\'):
        filename = filename[5:]  # Remove 'data/' or 'data\' prefix
    
    # Basic security check: Ensure filename doesn't try to escape the DATA_FOLDER
    # os.path.normpath helps prevent some path traversal issues
    safe_path = os.path.normpath(os.path.join(DATA_FOLDER, filename))
    if not safe_path.startswith(DATA_FOLDER):
        app.logger.warning(f"Attempted path traversal detected: {filename}")
        return "Forbidden", 403 # Or flash an error and redirect

    # Handle both formats: full path with 'data/' prefix and just the filename
    if not os.path.exists(safe_path) and ('/' in filename or '\\' in filename):
        # Try with just the last component of the path
        filename = os.path.basename(filename)
        safe_path = os.path.join(DATA_FOLDER, filename)

    # Check if file exists before sending
    if not os.path.exists(safe_path):
        app.logger.warning(f"Data file not found: {filename} (resolved to {safe_path})")
        # Try to find matching old screenshots by pattern
        import glob
        filename_base = os.path.basename(filename)
        # Extract the URL part of the filename (before timestamp)
        if '_' in filename_base:
            url_part = '_'.join(filename_base.split('_')[:-1])  # Everything before the last underscore
            # Look for files with similar pattern
            pattern = os.path.join(DATA_FOLDER, f"{url_part}_*.png")
            matches = glob.glob(pattern)
            if matches:
                # Sort by modification time (newest first) and pick the most recent
                matches.sort(key=os.path.getmtime, reverse=True)
                safe_path = matches[0]
                filename = os.path.basename(safe_path)
        
        # If no matching file found, return placeholder
        if not os.path.exists(safe_path):
            placeholder_path = os.path.join(os.path.dirname(__file__), 'static', 'stub_screenshot.png')
            if os.path.exists(placeholder_path):
                return send_from_directory(os.path.dirname(placeholder_path), os.path.basename(placeholder_path))
            return "File not found", 404

    # Optimization for image files (screenshots)
    if ENABLE_IMAGE_OPTIMIZATION and filename.endswith(('.png', '.jpg', '.jpeg')):
        # Check if optimization parameter was passed
        optimize = request.args.get('optimize', 'true').lower() != 'false'
        
        if optimize:
            try:
                # Try to get optimized image from cache
                image_data, mime_type = get_optimized_image(safe_path)
                
                if image_data:
                    app.logger.debug(f"Serving optimized image: {filename}")
                    # Add caching headers to improve performance
                    response = Response(image_data, mimetype=mime_type)
                    response.headers['Cache-Control'] = f'max-age={CACHE_TIMEOUT}, public'
                    return response
            except Exception as e:
                app.logger.error(f"Error optimizing image {filename}: {e}")
                # Fall through to standard delivery if optimization fails
    
    app.logger.debug(f"Serving data file: {filename} from {safe_path}")
    # Add caching headers to improve performance for all files
    response = send_from_directory(DATA_FOLDER, filename)
    response.headers['Cache-Control'] = f'max-age={CACHE_TIMEOUT}, public'
    return response

# Models
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(64), unique=True, nullable=False)
    email = db.Column(db.String(120))
    telegram_token = db.Column(db.String(256), default=None) # User-specific Telegram token
    telegram_chat_id = db.Column(db.String(64), default=None) # User-specific Telegram chat ID
    teams_webhook = db.Column(db.String(512), default=None) # User-specific Teams webhook
    created_at = db.Column(db.DateTime, default=datetime.now)
    # New fields for notification preferences
    notification_preference = db.Column(db.String(20), default='immediate') # 'immediate', 'summary', 'both'
    summary_times = db.Column(db.String(100), default='09:00') # Comma-separated HH:MM, e.g., "09:00,17:00"
    # New field for notifications on changes only
    notify_only_changes = db.Column(db.Boolean, default=True) # True = notify only on changes, False = notify on all checks

class Website(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    url = db.Column(db.String(2048), nullable=False)
    user_id = db.Column(db.String(64), db.ForeignKey('user.user_id'))
    frequency_type = db.Column(db.String(32), default='interval')  # 'interval' or 'specific_times'
    frequency_value = db.Column(db.String(128), default='60')  # Interval in minutes or comma-separated times (e.g., '08:00,12:00')
    last_checked = db.Column(db.DateTime)
    status = db.Column(db.String(32), default='active')
    error_message = db.Column(db.String(512))
    ai_focus_area = db.Column(db.String(256), default=None) # Optional text input for AI focus area
    proxy = db.Column(db.String(128), default=None)  # New: proxy/tunnel
    # New fields for monitoring type
    monitoring_type = db.Column(db.String(50), default='general_updates') # 'general_updates', 'specific_elements'
    monitoring_keywords = db.Column(db.Text, default=None) # Optional comma-separated keywords for specific elements

    def get_latest_history(self):
        """Get the latest check history for this website."""
        return CheckHistory.query.filter_by(website_id=self.id).order_by(CheckHistory.checked_at.desc()).first()

class CheckHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    website_id = db.Column(db.Integer, db.ForeignKey('website.id'))
    checked_at = db.Column(db.DateTime, default=datetime.now)
    screenshot_path = db.Column(db.String(256))
    html_path = db.Column(db.String(256))
    diff_path = db.Column(db.String(256))
    ai_description = db.Column(db.Text)
    change_detected = db.Column(db.Boolean, default=False)
    error = db.Column(db.String(512))
    response_time = db.Column(db.Float, default=None)
    ai_significance = db.Column(db.String(256))
    ai_detailed = db.Column(db.Text)
    ai_focus = db.Column(db.String(256))
    ai_error = db.Column(db.String(256))

class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(64), db.ForeignKey('user.user_id'))
    website_id = db.Column(db.Integer, db.ForeignKey('website.id'))
    check_history_id = db.Column(db.Integer, db.ForeignKey('check_history.id'), nullable=True)
    notification_type = db.Column(db.String(20), default='immediate')  # 'immediate' or 'summary'
    content = db.Column(db.Text)  # The notification message content
    screenshot_path = db.Column(db.String(256), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.now)
    sent = db.Column(db.Boolean, default=False)  # Whether the notification has been sent
    included_in_summary = db.Column(db.Boolean, default=False)  # Whether included in a summary notification
    summary_id = db.Column(db.Integer, nullable=True)  # ID of the summary notification that includes this notification

# Utility for safe file naming
def safe_filename(name):
    return re.sub(r'[^a-zA-Z0-9_-]', '_', name)[:40]

# Home / User ID Management
@app.route('/', methods=['GET']) # Only GET needed now for the main page
def index():
    # Simply display the page with existing users
    users = User.query.all()
    return render_template('index.html', users=users)

# Dashboard
# Redirect /dashboard and /dashboard/ to index
@app.route('/dashboard')
@app.route('/dashboard/')
def redirect_to_index():
    return redirect(url_for('index'))

@app.route('/dashboard/<user_id>')
def dashboard(user_id):
    user = User.query.filter_by(user_id=user_id).first()
    if not user:
        # If user doesn't exist, create them now
        app.logger.info(f"User '{user_id}' not found, creating new user.")
        user = User(user_id=user_id)
        db.session.add(user)
        try:
            db.session.commit()
            flash(f'New User ID "{user_id}" created.', 'success')
            app.logger.info(f"Successfully created and committed new user '{user_id}'.")
        except Exception as e:
            db.session.rollback()
            app.logger.error(f"Failed to commit new user '{user_id}': {e}")
            flash(f'Error creating user ID "{user_id}". Please try again.', 'danger')
            return redirect(url_for('index')) # Redirect back if creation fails

    # User exists (or was just created), proceed to dashboard
    websites = Website.query.filter_by(user_id=user_id).all()
    # Parse ai_description for each website's latest history
    ai_data_map = {}
    for website in websites:
        latest = website.get_latest_history()
        if latest and latest.ai_description:
            try:
                ai_data_map[website.id] = json.loads(latest.ai_description)
            except Exception:
                ai_data_map[website.id] = None
        else:
            ai_data_map[website.id] = None
    return render_template('dashboard.html', user=user, websites=websites, CheckHistory=CheckHistory, ai_data_map=ai_data_map)

# Add Website
@app.route('/add_website/<user_id>', methods=['GET', 'POST'])
def add_website(user_id):
    user = User.query.filter_by(user_id=user_id).first()
    if not user:
        flash(f"User ID '{user_id}' not found.", 'danger')
        return redirect(url_for('index'))

    if request.method == 'POST':
        app.logger.debug(f'Form data: {request.form}')

        url = request.form.get('url')
        frequency_type = request.form.get('frequency_type', 'interval')
        frequency_value = request.form.get('frequency_value', '60')
        ai_focus_area = request.form.get('ai_focus_area')
        proxy = request.form.get('proxy')
        # NEW: Get monitoring type and keywords
        monitoring_type = request.form.get('monitoring_type', 'general_updates')
        monitoring_keywords = request.form.get('monitoring_keywords') if monitoring_type == 'specific_elements' else None

        if not url:
            flash('URL required!', 'danger')
            return render_template('add_website.html', user_id=user_id) # Re-render form

        # Check if website with this URL already exists for this user
        existing_website = Website.query.filter_by(user_id=user_id, url=url).first()
        if existing_website:
            flash(f'Website "{url}" already exists for this user.', 'warning')
            return redirect(url_for('dashboard', user_id=user_id))

        website = Website(
            url=url,
            user_id=user_id,
            frequency_type=frequency_type,
            frequency_value=frequency_value,
            ai_focus_area=ai_focus_area,
            proxy=proxy,
            monitoring_type=monitoring_type, # NEW
            monitoring_keywords=monitoring_keywords # NEW
        )
        app.logger.debug(f"Attempting to add website to session: {website.url}")
        db.session.add(website)
        try:
            db.session.commit()
            app.logger.info(f"Website {website.id} ({website.url}) committed to database for user {user_id}")
            
            # Set initial status to "checking" to show activity
            website.status = 'checking'
            db.session.commit()
            
            # Queue the initial check in background
            app.logger.info(f"Queuing background initial check for website ID: {website.id}")
            try:
                # Use RQ to queue the job
                job = queue.enqueue('tasks.check_website', website.id)
                flash(f'Website "{website.url}" added. Initial check in progress.', 'success')
            except Exception as e:
                app.logger.error(f"Failed to queue initial check for website ID {website.id}: {e}", exc_info=True)
                flash(f'Website "{website.url}" added. Initial check will be performed soon.', 'success')
            
            # Redirect to dashboard immediately
            return redirect(url_for('dashboard', user_id=user_id))
            
        except Exception as e:
            db.session.rollback()
            app.logger.error(f'Error saving website: {e}', exc_info=True)
            flash('Failed to save website to database.', 'danger')
            return render_template('add_website.html', user_id=user_id) # Re-render form

    # GET request - display the form
    return render_template('add_website.html', user_id=user_id)

# Edit Website
@app.route('/edit_website/<int:website_id>', methods=['GET', 'POST'])
def edit_website(website_id):
    website = db.session.get(Website, website_id)
    if not website:
        return redirect(url_for('index'))
    if request.method == 'POST':
        website.url = request.form.get('url', website.url)
        website.frequency_type = request.form.get('frequency_type', website.frequency_type)
        website.frequency_value = request.form.get('frequency_value', website.frequency_value)
        website.ai_focus_area = request.form.get('ai_focus_area', website.ai_focus_area)
        website.proxy = request.form.get('proxy', website.proxy)
        # NEW: Update monitoring type and keywords
        website.monitoring_type = request.form.get('monitoring_type', website.monitoring_type)
        website.monitoring_keywords = request.form.get('monitoring_keywords') if website.monitoring_type == 'specific_elements' else None

        db.session.commit()
        flash('Website updated!', 'success')
        return redirect(url_for('dashboard', user_id=website.user_id))
    return render_template('edit_website.html', website=website)

# Delete Website
@app.route('/delete_website/<int:website_id>', methods=['POST'])
def delete_website(website_id):
    website = db.session.get(Website, website_id)
    if not website:
        return redirect(url_for('index'))
    user_id = website.user_id
    db.session.delete(website)
    db.session.commit()
    flash('Website deleted!', 'success')
    return redirect(url_for('dashboard', user_id=user_id))

# Delete User
@app.route('/delete_user/<user_id>', methods=['POST'])
def delete_user_post(user_id):
    user = User.query.filter_by(user_id=user_id).first()
    if not user:
        flash('User not found.', 'error')
        return redirect(url_for('index'))
    # Delete all websites and histories for this user
    websites = Website.query.filter_by(user_id=user_id).all()
    for website in websites:
        CheckHistory.query.filter_by(website_id=website.id).delete()
        db.session.delete(website)
    
    # Delete the user itself
    db.session.delete(user)
    
    try:
        db.session.commit()
        flash('User deleted!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting user: {e}', 'danger')
        app.logger.error(f"Error committing user deletion for {user_id}: {e}")
        
    return redirect(url_for('index'))

# Website Check History
@app.route('/history/<int:website_id>')
def history(website_id):
    website = db.session.get(Website, website_id)
    if not website:
        return redirect(url_for('index'))
    checks = CheckHistory.query.filter_by(website_id=website_id).order_by(CheckHistory.checked_at.desc()).all()
    # Parse ai_description for each check
    ai_data_list = []
    for check in checks:
        if check.ai_description:
            try:
                ai_data_list.append(json.loads(check.ai_description))
            except Exception:
                ai_data_list.append(None)
        else:
            ai_data_list.append(None)
    return render_template('check_history.html', website=website, checks=checks, ai_data_list=ai_data_list)

# Visual diff viewer route
@app.route('/visual_diff/<int:website_id>/<int:curr_check_id>')
def visual_diff(website_id, curr_check_id):
    website = db.session.get(Website, website_id)
    if not website:
        return redirect(url_for('index'))
    curr_check = db.session.get(CheckHistory, curr_check_id)
    if not curr_check:
        return redirect(url_for('index'))
    prev_check = CheckHistory.query.filter(CheckHistory.website_id==website_id, CheckHistory.id<curr_check_id).order_by(CheckHistory.id.desc()).first()
    prev_screenshot = prev_check.screenshot_path if prev_check and prev_check.screenshot_path else None
    curr_screenshot = curr_check.screenshot_path if curr_check and curr_check.screenshot_path else None
    diff_path = curr_check.diff_path if curr_check and curr_check.diff_path else None
    # For HTML diff, pass the relative path for Jinja2 include
    diff_include = None
    if diff_path and os.path.exists(diff_path):
        # Copy diff to static so it can be included (jinja can't include from outside templates/static)
        import shutil
        static_diff_path = f'static/diff_{website_id}_{curr_check_id}.txt'
        shutil.copyfile(diff_path, static_diff_path)
        diff_include = static_diff_path.replace('\\', '/')
    return render_template('visual_diff.html', website=website, prev_screenshot=prev_screenshot, curr_screenshot=curr_screenshot, diff_path=diff_include)

# Settings
@app.route('/settings/<user_id>', methods=['GET', 'POST'])
def settings(user_id):
    user = User.query.filter_by(user_id=user_id).first()
    if not user:
        return redirect(url_for('index'))
    if request.method == 'POST':
        # Check which button was pressed
        if 'submit_email' in request.form:
            user.email = request.form.get('email', user.email)
            flash('Email settings updated!', 'success')
        elif 'submit_telegram' in request.form:
            user.telegram_token = request.form.get('telegram_token', user.telegram_token)
            user.telegram_chat_id = request.form.get('telegram_chat_id', user.telegram_chat_id)
            flash('Telegram settings updated!', 'success')
        elif 'submit_teams' in request.form:
            user.teams_webhook = request.form.get('teams_webhook', user.teams_webhook)
            flash('Teams settings updated!', 'success')
        elif 'submit_notification_prefs' in request.form:
            # Process notification preferences
            user.notification_preference = request.form.get('notification_preference', 'immediate')
            
            # Process the notify_only_changes checkbox
            user.notify_only_changes = 'notify_only_changes' in request.form
            
            # Validate summary_times format
            summary_times = request.form.get('summary_times', '09:00')
            # Basic validation: check if it's comma-separated HH:MM format
            time_pattern = re.compile(r'^([0-1]?[0-9]|2[0-3]):[0-5][0-9](,\s*([0-1]?[0-9]|2[0-3]):[0-5][0-9])*$')
            if time_pattern.match(summary_times):
                user.summary_times = summary_times
                flash('Notification preferences updated!', 'success')
            else:
                flash('Invalid time format in summary times. Please use HH:MM format, separated by commas (example: 09:00,17:30).', 'warning')
        db.session.commit()
        return redirect(url_for('settings', user_id=user_id))
    
    # Fetch system prompts for display in the settings
    default_compare_prompt = "Analyze the provided website screenshot compared to a previous state (assume this is a follow-up check)."
    default_notification_prompt = "Create a clear, concise notification about the following website change:"
    default_summary_prompt = "Create a concise summary of website changes detected for the following sites:"
    
    ai_compare_prompt = os.getenv('AI_COMPARE_SYSTEM_PROMPT', default_compare_prompt)
    ai_notification_prompt = os.getenv('AI_NOTIFICATION_SYSTEM_PROMPT', default_notification_prompt)
    ai_summary_prompt = os.getenv('AI_NOTIFICATION_SUMMARY_SYSTEM_PROMPT', default_summary_prompt)
    
    return render_template('settings.html', 
                           user=user,
                           ai_compare_prompt=ai_compare_prompt,
                           ai_notification_prompt=ai_notification_prompt,
                           ai_summary_prompt=ai_summary_prompt)

@app.route('/update_ai_prompt/<user_id>', methods=['POST'])
def update_ai_prompt(user_id):
    """Update AI system prompts."""
    user = User.query.filter_by(user_id=user_id).first()
    if not user:
        flash('User not found.', 'danger')
        return redirect(url_for('index'))
    
    # Get and validate the new AI prompts
    ai_compare_prompt = request.form.get('ai_compare_prompt', '').strip()
    ai_notification_prompt = request.form.get('ai_notification_prompt', '').strip()
    ai_summary_prompt = request.form.get('ai_summary_prompt', '').strip()
    
    # Read current .env file
    env_path = '.env'
    try:
        with open(env_path, 'r') as file:
            lines = file.readlines()
    except FileNotFoundError:
        lines = []
    
    # Function to update or add a line in the .env file
    def update_env_var(lines, var_name, new_value):
        var_pattern = re.compile(f'^{var_name}=.*$')
        updated = False
        
        for i, line in enumerate(lines):
            if var_pattern.match(line):
                lines[i] = f'{var_name}={new_value}\n'
                updated = True
                break
        
        if not updated:
            lines.append(f'{var_name}={new_value}\n')
        
        return lines
    
    # Update each prompt variable
    if ai_compare_prompt:
        lines = update_env_var(lines, 'AI_COMPARE_SYSTEM_PROMPT', ai_compare_prompt)
    if ai_notification_prompt:
        lines = update_env_var(lines, 'AI_NOTIFICATION_SYSTEM_PROMPT', ai_notification_prompt)
    if ai_summary_prompt:
        lines = update_env_var(lines, 'AI_NOTIFICATION_SUMMARY_SYSTEM_PROMPT', ai_summary_prompt)
    
    # Write updated content back to .env file
    with open(env_path, 'w') as file:
        file.writelines(lines)
    
    # Update environment variables in current process
    os.environ['AI_COMPARE_SYSTEM_PROMPT'] = ai_compare_prompt
    os.environ['AI_NOTIFICATION_SYSTEM_PROMPT'] = ai_notification_prompt
    os.environ['AI_NOTIFICATION_SUMMARY_SYSTEM_PROMPT'] = ai_summary_prompt
    
    flash('AI system prompts updated successfully!', 'success')
    return redirect(url_for('settings', user_id=user_id))

# --- Website Monitoring and Change Detection Logic ---
import difflib
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
import telebot
import requests as pyrequests

# Ensure app always uses local browser_agent integration
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'browser_agent'))
from browser_agent.screenshot import get_screenshot_playwright

def fetch_website_content(website):
    try:
        proxies = {"http": website.proxy, "https": website.proxy} if website.proxy else None
        response = pyrequests.get(website.url, timeout=15, proxies=proxies)
        response.raise_for_status()
        html = response.text
        screenshot = None  # Placeholder for screenshot logic
        return html, screenshot, None
    except pyrequests.exceptions.RequestException as e:
        app.logger.error(f"Request Exception fetching content for website ID {website.id}: {e}")
        return None, None, str(e)
    except Exception as e:
        app.logger.error(f"Unexpected Exception fetching content for website ID {website.id}: {e}")
        return None, None, str(e)

def compare_html(old_html, new_html):
    diff = difflib.unified_diff(
        old_html.splitlines(),
        new_html.splitlines(),
        lineterm='',
    )
    return '\n'.join(diff)

def send_email_notification(user, subject, body, screenshot_path=None):
    app.logger.debug(f"Attempting to send email to user_id: {user.user_id} (Email: {user.email})")
    if not user.email:
        app.logger.warning(f"No email address configured for user_id: {user.user_id}")
        return False, "No email address configured."

    # --- Retrieve Credentials ---
    smtp_host = os.getenv('SMTP_HOST')
    smtp_port_str = os.getenv('SMTP_PORT', '587') # Default to 587 for TLS
    smtp_user = os.getenv('SMTP_USER')
    smtp_pass = os.getenv('SMTP_PASS')
    email_from = os.getenv('EMAIL_FROM')

    # --- Validate Credentials ---
    if not all([smtp_host, smtp_port_str, smtp_user, smtp_pass, email_from]):
        app.logger.error(f"Email credentials missing in .env for user {user.user_id}")
        return False, "Email server credentials missing in configuration."

    try:
        smtp_port = int(smtp_port_str)
    except ValueError:
        app.logger.error(f"Invalid SMTP_PORT value: {smtp_port_str}")
        return False, "Invalid SMTP port configured."

    # --- Construct Email Message ---
    msg = MIMEMultipart()
    msg['From'] = email_from
    msg['To'] = user.email
    msg['Subject'] = subject

    msg.attach(MIMEText(body, 'plain'))

    # --- Attach Screenshot (if provided and exists) ---
    if screenshot_path and os.path.exists(screenshot_path):
        try:
            with open(screenshot_path, 'rb') as attachment:
                part = MIMEBase('application', 'octet-stream')
                part.set_payload(attachment.read())
            encoders.encode_base64(part)
            part.add_header(
                'Content-Disposition',
                f"attachment; filename= {os.path.basename(screenshot_path)}",
            )
            msg.attach(part)
            app.logger.debug(f"Attached screenshot {screenshot_path} to email for {user.user_id}")
        except Exception as e:
            app.logger.error(f"Error attaching screenshot {screenshot_path} to email for {user.user_id}: {e}", exc_info=True)
            # Continue sending email without attachment

    # --- Send Email ---
    try:
        app.logger.debug(f"Connecting to SMTP server: {smtp_host}:{smtp_port}")
        # Use SSL if port is 465, otherwise use TLS (STARTTLS)
        if smtp_port == 465:
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(smtp_host, smtp_port, context=context) as server:
                app.logger.debug(f"Logging in as {smtp_user}")
                server.login(smtp_user, smtp_pass)
                app.logger.debug(f"Sending email to {user.email}")
                server.sendmail(email_from, user.email, msg.as_string())
                app.logger.info(f"Email sent successfully to {user.email} for user {user.user_id}")
        else: # Assume STARTTLS for other ports like 587
            with smtplib.SMTP(smtp_host, smtp_port) as server:
                server.ehlo() # Can be omitted
                server.starttls()
                server.ehlo() # Can be omitted
                app.logger.debug(f"Logging in as {smtp_user}")
                server.login(smtp_user, smtp_pass)
                app.logger.debug(f"Sending email to {user.email}")
                server.sendmail(email_from, user.email, msg.as_string())
                app.logger.info(f"Email sent successfully to {user.email} for user {user.user_id}")
        return True, "Email sent successfully."
    except smtplib.SMTPAuthenticationError as e:
        app.logger.error(f"SMTP Authentication Error for user {user.user_id} ({smtp_user}): {e}", exc_info=True)
        return False, f"Email authentication failed: {e}"
    except smtplib.SMTPConnectError as e:
        app.logger.error(f"SMTP Connection Error for user {user.user_id} ({smtp_host}:{smtp_port}): {e}", exc_info=True)
        return False, f"Failed to connect to email server: {e}"
    except smtplib.SMTPSenderRefused as e:
         app.logger.error(f"SMTP Sender Refused for user {user.user_id} (From: {email_from}): {e}", exc_info=True)
         return False, f"Email sender refused: {e}"
    except smtplib.SMTPRecipientsRefused as e:
        app.logger.error(f"SMTP Recipient Refused for user {user.user_id} (To: {user.email}): {e}", exc_info=True)
        return False, f"Email recipient refused: {e}"
    except socket.gaierror as e:
        app.logger.error(f"SMTP Hostname Resolution Error for user {user.user_id} (Host: {smtp_host}): {e}", exc_info=True)
        return False, f"Could not resolve email server hostname: {e}"
    except Exception as e:
        app.logger.error(f"Generic error sending email for user {user.user_id}: {e}", exc_info=True)
        return False, f"An unexpected error occurred sending email: {e}"

def send_telegram_notification(user_id, message):
    app.logger.debug(f"Attempting to send Telegram notification to user_id: {user_id}")
    user = User.query.filter_by(user_id=user_id).first()
    if not user:
        app.logger.error(f"User {user_id} not found for Telegram notification.")
        return False, "User not found."

    # --- Retrieve Credentials ---
    # Prioritize user-specific token, fall back to global
    bot_token = user.telegram_token or os.getenv('TELEGRAM_BOT_TOKEN')
    chat_id = user.telegram_chat_id or os.getenv('TELEGRAM_CHAT_ID') # Allow user chat_id override

    # --- Validate Credentials ---
    if not bot_token:
        app.logger.warning(f"Telegram Bot Token missing for user {user_id} and globally.")
        return False, "Telegram Bot Token not configured."
    if not chat_id:
        app.logger.warning(f"Telegram Chat ID missing for user {user_id} and globally.")
        return False, "Telegram Chat ID not configured."

    # --- Send Message ---
    api_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        'chat_id': chat_id,
        'text': message,
        'parse_mode': 'Markdown' # Optional: use Markdown for formatting
    }
    try:
        app.logger.debug(f"Sending Telegram message to chat_id: {chat_id}")
        response = ext_requests.post(api_url, data=payload, timeout=10)
        response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)
        response_data = response.json()
        if response_data.get('ok'):
            app.logger.info(f"Telegram message sent successfully to chat_id {chat_id} for user {user_id}")
            return True, "Telegram message sent successfully."
        else:
            error_description = response_data.get('description', 'Unknown error')
            app.logger.error(f"Telegram API error for user {user_id}: {error_description} (Payload: {payload}, Response: {response.text})")
            return False, f"Telegram API Error: {error_description}"
    except ext_requests.exceptions.RequestException as e:
        app.logger.error(f"Network error sending Telegram message for user {user_id}: {e}", exc_info=True)
        return False, f"Network error sending Telegram message: {e}"
    except Exception as e:
        app.logger.error(f"Generic error sending Telegram message for user {user_id}: {e}", exc_info=True)
        return False, f"An unexpected error occurred sending Telegram message: {e}"

def send_teams_notification(user_id, message):
    print(f"[DEBUG] Attempting to send Teams notification to user_id: {user_id}")
    """Send notification to a user via Microsoft Teams"""
    user = User.query.filter_by(user_id=user_id).first()
    if not user or not user.teams_webhook:
        print(f"[ERROR] Cannot send Teams: No webhook URL for user {user_id}")
        return False, "No Teams webhook URL configured for user."

    webhook_url = user.teams_webhook

    try:
        # Format the message as a Teams card
        card = {
            "@type": "MessageCard",
            "@context": "http://schema.org/extensions",
            "summary": "AI Website Monitor Notification",
            "themeColor": "0076D7",
            "title": "AI Website Monitor Notification",
            "sections": [
                {
                    "text": message
                }
            ]
        }

        # Send the message to Teams
        response = ext_requests.post(webhook_url, json=card)

        # Check if the request was successful
        if response.status_code == 200:
            print(f"[DEBUG] Teams notification sent successfully")
            print(f"[DEBUG] Teams notification sent successfully")
            return True, "Teams notification sent successfully."
        else:
            error_msg = f"Failed to send Teams notification. Status code: {response.status_code}, Response: {response.text}"
            print(f"[ERROR] {error_msg}")
            return False, error_msg
    except Exception as e:
        error_msg = f"Exception while sending Teams notification: {e}"
        print(f"[ERROR] {error_msg}")
        return False, error_msg

# Gemini Vision API integration (real)
# Modify function signature to accept monitoring_type and monitoring_keywords
def gemini_vision_api_compare(html, screenshot_path, monitoring_type='general_updates', monitoring_keywords=None, ai_focus_area=None, gemini_model='gemini-2.5-flash-preview-05-20'):
    """Compares website state using Gemini Vision API, adapting prompt based on monitoring type and model."""
    import google.generativeai as genai
    from google.generativeai.types import HarmCategory, HarmBlockThreshold
    from pathlib import Path # Import Path here
    import json
    # Collect potential API keys (existing logic)
    api_keys = []
    base_key = os.getenv('GEMINI_API_KEY')
    if base_key:
        api_keys.append(base_key)
    for i in range(1, 11):
        numbered_key = os.getenv(f'GEMINI_API_KEY_{i}')
        if numbered_key:
            api_keys.append(numbered_key)
    if not api_keys:
        message = 'No Gemini API keys configured in .env (GEMINI_API_KEY or GEMINI_API_KEY_n).'
        app.logger.error(message)
        return json.dumps({"error_message": message, "change_detected": False, "summary_of_changes": "AI error: No API key", "significance_level": "none", "detailed_changes": [], "focus_area_assessment": ""})
    # --- Get system prompt from environment or use default ---
    default_base_instruction = "You are an AI designed to compare screenshots of websites. You will receive two images: the previous and the current. Your purpose is to show the change description. Focus on comparing old/new screenshot/html only, compare what users want you to focus on. Write output as valid JSON with bullet points and explanations. Be analytical and comprehensive."
    custom_base_instruction = os.getenv('AI_COMPARE_SYSTEM_PROMPT', default_base_instruction)
    base_instruction = custom_base_instruction or default_base_instruction
    # --- Prepare the Prompt based on Monitoring Type --- 
    prompt_parts = []
    if monitoring_type == 'specific_elements' and monitoring_keywords:
        prompt_parts.append(f"{base_instruction} Focus ONLY on changes related to these keywords/elements: '{monitoring_keywords}'. If changes related to these specific keywords are found, describe them clearly. If no relevant changes related to these keywords are found, simply state 'No relevant changes detected for monitored keywords.'.")
        app.logger.debug(f"Using specific elements prompt with keywords: {monitoring_keywords}")
    else: # Default to general_updates or if keywords missing for specific
        prompt_parts.append(f"{base_instruction}")
        if ai_focus_area:
            prompt_parts.append(f" Pay special attention to changes related to: '{ai_focus_area}'.")
        app.logger.debug(f"Using general updates prompt (Focus Area: {ai_focus_area or 'None'})")
    # --- Load Image Data (if available) --- 
    image_parts = []
    # Accept a list of screenshot paths for before/after comparison
    if isinstance(screenshot_path, list) and len(screenshot_path) == 2:
        for idx, path in enumerate(screenshot_path):
            if path and os.path.exists(path):
                try:
                    image_parts.append({
                        "mime_type": "image/png",
                        "data": Path(path).read_bytes()
                        # Removed the 'role' field which caused the error
                    })
                    app.logger.debug(f"Added {'previous' if idx == 0 else 'current'} screenshot {path} to Gemini prompt.")
                except Exception as e:
                    app.logger.error(f"Failed to read screenshot {path} for Gemini: {e}")
                    image_parts.append(f"(Screenshot loading failed: {path})")
        # Insert both images after the prompt
        prompt_parts = prompt_parts[:1] + image_parts + prompt_parts[1:]
        
        # Instead of using 'role', add text descriptors before each image
        prompt_parts.insert(1, "Previous screenshot:")
        prompt_parts.insert(3, "Current screenshot:")
    elif screenshot_path and os.path.exists(screenshot_path):
        try:
            image_part = {
                "mime_type": "image/png",
                "data": Path(screenshot_path).read_bytes()
            }
            prompt_parts.insert(1, image_part)
            app.logger.debug(f"Added screenshot {screenshot_path} to Gemini prompt.")
        except Exception as e:
            app.logger.error(f"Failed to read screenshot {screenshot_path} for Gemini: {e}")
            prompt_parts.insert(1, "(Screenshot loading failed)")
    else:
         prompt_parts.insert(1, "(No screenshot provided)")
    # --- Try API call with available keys ---
    last_error = None
    for key in api_keys:
        masked_key = f"...{key[-4:]}" if key and len(key) > 4 else "********"
        app.logger.info(f"Attempting Gemini Vision API call with key ending in {masked_key}")
        try:
            genai.configure(api_key=key)
            # Configure the model to use
            model_name = gemini_model or 'gemini-2.5-flash-preview-05-20'
            gemini_model_obj = genai.GenerativeModel(
                model_name,
                safety_settings={
                    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
                    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
                    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
                    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
                }
            )
            response = gemini_model_obj.generate_content(prompt_parts)
            ai_description = response.text
            # Try to parse as JSON, fallback to text
            try:
                ai_data = json.loads(ai_description)
                # If the model returns a JSON string with the expected fields, return it
                return json.dumps(ai_data)
            except Exception:
                # Fallback: wrap the text in the expected JSON structure
                return json.dumps({
                    "change_detected": any(x in ai_description.lower() for x in ["website changed", "change detected", "difference found", "new content"]),
                    "significance_level": "medium",
                    "summary_of_changes": ai_description,
                    "detailed_changes": [],
                    "focus_area_assessment": ai_focus_area or "",
                    "error_message": ""
                })
        except Exception as e:
            last_error = str(e)
            app.logger.error(f"Gemini API call failed with key {masked_key}: {e}")
    # If all keys failed, return error
    error_message = f"All Gemini API keys failed. Last error: {last_error}"
    app.logger.error(error_message)
    return json.dumps({"error_message": error_message, "change_detected": False, "summary_of_changes": "AI Analysis Error: " + error_message, "significance_level": "none", "detailed_changes": [], "focus_area_assessment": ai_focus_area or ""})

# Anomaly detection (stub)
def detect_anomaly(website, last_check, new_html, response_time, error=None):
    """Stub function for anomaly detection."""
    # In a real implementation, this would compare new_html/screenshot with last_check
    # and use AI to determine if a meaningful change occurred.
    # For now, it just checks for errors or simulates a change.
    change_detected = False
    ai_description = "No significant change detected (stub)."

    if error:
        change_detected = True
        ai_description = f"Error detected during check: {error}"
    elif last_check and new_html != open(last_check.html_path, 'r', encoding='utf-8').read():
         # Simple HTML change detection (can be refined)
         change_detected = True
         ai_description = "HTML content changed (basic detection)."

    return change_detected, ai_description

# Data cleanup
def cleanup_old_data(max_age_days=30):
    """Deletes check history, screenshots, html, and diff files older than max_age_days."""
    app.logger.info(f"Starting data cleanup for data older than {max_age_days} days.")
    cutoff_date = datetime.now() - timedelta(days=max_age_days)

    old_checks = CheckHistory.query.filter(CheckHistory.checked_at < cutoff_date).all()
    deleted_count = 0

    for check in old_checks:
        # Delete associated files
        for file_path in [check.screenshot_path, check.html_path, check.diff_path]:
            if file_path and os.path.exists(file_path):
                try:
                    os.remove(file_path)
                    app.logger.debug(f"Deleted old file: {file_path}")
                    deleted_count += 1
                except OSError as e:
                    app.logger.error(f"Error deleting file {file_path}: {e}")

        # Delete the history record
        db.session.delete(check)

    try:
        db.session.commit()
        app.logger.info(f"Data cleanup complete. Deleted {deleted_count} files and {len(old_checks)} history records.")
    except Exception as e:
        app.logger.error(f"Error during data cleanup commit: {e}")
        db.session.rollback()

@app.route('/admin/cleanup_data', methods=['POST'])
def admin_cleanup_data():
    """Admin route to trigger data cleanup."""
    # Admin Key Check
    submitted_admin_key = request.form.get('admin_key')
    correct_admin_key = os.getenv('ADMIN_KEY')
    if not correct_admin_key or submitted_admin_key != correct_admin_key:
        app.logger.warning(f"Unauthorized attempt to perform data cleanup (invalid/missing Admin Key).")
        flash('Invalid or missing Admin Key. Data cleanup not permitted.', 'danger')
        return redirect(url_for('index'))
    
    app.logger.info(f"Admin-authorized request received to clean up data older than 30 days")
    
    try:
        # Execute the cleanup process
        cleanup_old_data(max_age_days=30)
        flash("Successfully deleted data older than 30 days.", "success")
    except Exception as e:
        app.logger.error(f"Error during data cleanup: {e}", exc_info=True)
        flash(f"Error during data cleanup: {e}", "danger")
    
    # Redirect to the index page
    return redirect(url_for('index'))

@app.route('/delete_old_data/<user_id>/<period>', methods=['POST'])
def delete_old_data(user_id, period):
    # Admin Key Check
    submitted_admin_key = request.form.get('admin_key')
    correct_admin_key = os.getenv('ADMIN_KEY')
    if not correct_admin_key or submitted_admin_key != correct_admin_key:
        logger.warning(f"Unauthorized attempt to delete data for user {user_id} (invalid/missing Admin Key).")
        flash('Invalid or missing Admin Key. Data deletion not permitted.', 'danger')
        return redirect(url_for('settings', user_id=user_id))

    logger.info(f"Admin-authorized request received to delete data older than {period} for user {user_id}")

    user = User.query.filter_by(user_id=user_id).first()
    if not user:
        flash('User not found.', 'danger')
        return redirect(url_for('index'))

    if period == 'month':
        days = 30
        cutoff_date = datetime.now() - timedelta(days=days)
        logger.info(f"Deleting data older than {days} days (cutoff: {cutoff_date}) for user {user_id}")
    elif period == 'year':
        days = 365
        cutoff_date = datetime.now() - timedelta(days=days)
        logger.info(f"Deleting data older than {days} days (cutoff: {cutoff_date}) for user {user_id}")
    else:
        flash('Invalid time period specified.', 'danger')
        return redirect(url_for('settings', user_id=user_id))

    # Find websites associated with the user
    websites = Website.query.filter_by(user_id=user_id).all()
    website_ids = [w.id for w in websites]

    if not website_ids:
        flash('No websites found for this user.', 'info')
        return redirect(url_for('settings', user_id=user_id))

    # Find history records older than the cutoff date for these websites
    old_history = CheckHistory.query.filter(
        CheckHistory.website_id.in_(website_ids),
        CheckHistory.checked_at < cutoff_date
    ).all()

    deleted_files_count = 0
    deleted_records_count = 0
    failed_deletions = []

    data_dir = app.config.get('DATA_FOLDER', 'data')

    for history in old_history:
        # Delete associated files first
        for file_path_attr in ['screenshot_path', 'html_path', 'diff_path']:
            file_path = getattr(history, file_path_attr, None)
            if file_path:
                # Construct full path relative to app root
                # full_file_path = os.path.join(data_dir, os.path.basename(file_path))
                # Correction: Assume paths stored are relative to app root (e.g., 'data/file.png')
                full_file_path = os.path.abspath(file_path)
                if os.path.exists(full_file_path):
                    try:
                        os.remove(full_file_path)
                        logger.debug(f"Deleted old data file: {full_file_path}")
                        deleted_files_count += 1
                    except OSError as e:
                        logger.error(f"Error deleting file {full_file_path}: {e}")
                        failed_deletions.append(os.path.basename(full_file_path))
                else:
                    logger.warning(f"File path in history record not found, skipping deletion: {full_file_path}")

        # Delete the history record itself
        try:
            db.session.delete(history)
            deleted_records_count += 1
        except Exception as e:
            logger.error(f"Error deleting history record ID {history.id}: {e}")
            db.session.rollback() # Rollback the specific deletion failure
            # Continue trying to delete other records

    # Commit deletions after processing all records
    try:
        db.session.commit()
        logger.info(f"Committed deletion of {deleted_records_count} history records for user {user_id}.")
    except Exception as e:
        logger.error(f"Error committing final deletions for user {user_id}: {e}")
        db.session.rollback()
        flash('An error occurred during the final commit of data deletion.', 'danger')
        return redirect(url_for('settings', user_id=user_id))

    if failed_deletions:
        flash(f'Deleted {deleted_records_count} history records and {deleted_files_count} associated files. Failed to delete some files: {", ".join(failed_deletions)}', 'warning')
    elif deleted_records_count > 0 or deleted_files_count > 0:
        flash(f'Successfully deleted {deleted_records_count} history records and {deleted_files_count} associated files older than {period}.', 'success')
    else:
        flash(f'No data found older than {period} to delete.', 'info')

    return redirect(url_for('settings', user_id=user_id))


# RQ Queue setup
q = Queue(connection=redis_url)

def enqueue_check_website(website_id):
    """Enqueues a website check job for the given website ID."""
    try:
        # Get a fresh Redis connection for this function
        redis_conn = get_redis_connection()
        if not redis_conn:
            app.logger.error("Redis connection failed. Cannot enqueue website check.")
            return {"status": "error", "message": "Redis connection failed"}, 500
            
        q = Queue(connection=redis_conn)
        
        # First, check if a job for this website_id is already in the queue
        queued_job_ids = q.job_ids  # Get IDs of all jobs in the queue
        for job_id in queued_job_ids:
            job = q.fetch_job(job_id)
            if job and job.args and len(job.args) > 0 and job.args[0] == website_id:
                app.logger.debug(f"Job for website ID {website_id} already in queue. Skipping.")
                return {"status": "skipped", "message": f"Job for website ID {website_id} already queued."}, 200

        # Create a new job for this website
        if website_id:
            app.logger.debug(f"Attempting to enqueue check_website_direct for website ID: {website_id}")
            
            try:
                # Verify Redis connection is working
                redis_ping = redis_conn.ping()
                app.logger.debug(f"Redis connection ping result: {redis_ping}")
            except Exception as redis_err:
                app.logger.error(f"Redis connection failed: {redis_err}")
                return {"status": "error", "message": f"Redis connection failed: {redis_err}"}, 500
            
            # Import tasks module here to avoid circular imports
            from tasks import check_website_direct
            
            try:
                job = q.enqueue(check_website_direct, website_id)
                app.logger.info(f"Job enqueued for website ID {website_id}. Job ID: {job.id}")
                return {"status": "success", "message": "Check job enqueued", "job_id": job.id}, 200
            except Exception as enqueue_err:
                app.logger.error(f"Failed to enqueue job for website ID {website_id}: {enqueue_err}")
                return {"status": "error", "message": f"Failed to enqueue job: {enqueue_err}"}, 500
        else:
            app.logger.error("Invalid request: Missing website ID.")
            return {"status": "error", "message": "Missing website ID"}, 400
            
    except Exception as e:
        app.logger.error(f"Failed to enqueue job: {e}", exc_info=True)
        return {"status": "error", "message": f"Failed to enqueue job: {e}"}, 500


# Scheduled checks
@scheduler.scheduled_job('interval', minutes=10)
def scheduled_checks():
    """Schedule website checks at appropriate intervals and times"""
    app.logger.info("Running scheduled checks. This should appear every 10 minutes.")
    
    # Get a fresh Redis connection
    redis_conn = get_redis_connection()
    if not redis_conn:
        app.logger.error("Redis connection failed. Cannot perform scheduled checks.")
        return
        
    q = Queue(connection=redis_conn)
    
    with app.app_context():
        websites = Website.query.all()
        now_local = datetime.now()
        app.logger.info(f"Scheduled check running at {now_local.strftime('%Y-%m-%d %H:%M:%S')}. Found {len(websites)} websites to evaluate.")
        check_count = 0

        for website in websites:
            should_check = False
            
            # Log the website being evaluated
            app.logger.debug(f"Evaluating website ID {website.id}: {website.url}, Last checked: {website.last_checked}, Frequency: {website.frequency_type}={website.frequency_value}")
            
            if website.frequency_type == 'interval':
                interval_minutes = int(website.frequency_value)
                if website.last_checked is None:
                    should_check = True
                    app.logger.info(f"Website {website.id} ({website.url}) due for FIRST interval check (every {interval_minutes} min)")
                elif (now_local - website.last_checked) >= timedelta(minutes=interval_minutes):
                    time_since_last = now_local - website.last_checked
                    should_check = True
                    app.logger.info(f"Website {website.id} ({website.url}) due for interval check. {time_since_last.total_seconds()/60:.1f} minutes since last check (interval: {interval_minutes} min)")
                else:
                    time_since_last = now_local - website.last_checked
                    minutes_remaining = interval_minutes - (time_since_last.total_seconds() / 60)
                    app.logger.debug(f"Website {website.id} ({website.url}) not due yet. {time_since_last.total_seconds()/60:.1f} minutes since last check, {minutes_remaining:.1f} minutes remaining")
            elif website.frequency_type == 'specific_times':
                try:
                    specific_times = [datetime.strptime(t.strip(), '%H:%M').time() for t in website.frequency_value.split(',')]
                    app.logger.debug(f"Website {website.id} checking specific times: {website.frequency_value}, current time: {now_local.strftime('%H:%M')}")
                    
                    # Check if current time is one of the specific times, considering a small window
                    for check_time in specific_times:
                        check_datetime_today = now_local.replace(hour=check_time.hour, minute=check_time.minute, second=0, microsecond=0)
                        # Check if the current time is within a few minutes after the scheduled time
                        time_diff = now_local - check_datetime_today
                        app.logger.debug(f"  Checking time {check_time.strftime('%H:%M')}, diff: {time_diff.total_seconds()/60:.1f} minutes")
                        
                        if 0 <= time_diff.total_seconds() < 600:  # Within 10 minutes after scheduled time
                            # Only check if we haven't checked recently
                            if website.last_checked is None or website.last_checked < check_datetime_today:
                                should_check = True
                                app.logger.info(f"Website {website.id} ({website.url}) due for specific time check at {check_time}")
                                break  # Check only once per scheduled time per day
                except ValueError as e:
                    app.logger.error(f"Invalid specific_times format for website {website.id}: {website.frequency_value} - {str(e)}")

            if should_check:
                app.logger.info(f"Scheduling check for website ID {website.id}: {website.url}")
                try:
                    # Import tasks here to avoid circular imports
                    from tasks import check_website_direct
                    
                    # Verify Redis connection is working before enqueuing
                    try:
                        redis_ping = redis_conn.ping()
                        app.logger.debug(f"Redis connection ping result: {redis_ping}")
                    except Exception as redis_err:
                        app.logger.error(f"Redis connection failed: {redis_err}")
                        continue  # Skip this website if Redis is not working
                    
                    # Enqueue the job through the Redis queue
                    job = q.enqueue(check_website_direct, website.id)
                    app.logger.info(f"Successfully scheduled check for website ID {website.id}. Job ID: {job.id}")
                    check_count += 1
                except Exception as e:
                    app.logger.error(f"Failed to schedule check for website ID {website.id}: {e}", exc_info=True)
        
        app.logger.info(f"Scheduled checks run completed. Scheduled {check_count} website checks out of {len(websites)} total websites.")


# --- NEW: Daily Summary Notification Job --- #
@scheduler.scheduled_job('interval', minutes=10) # Check every 10 minute
def send_daily_summaries():
    app.logger.debug("Running daily summary check.")
    
    # Get a fresh Redis connection
    redis_conn = get_redis_connection()
    if not redis_conn:
        app.logger.error("Redis connection failed. Cannot perform daily summaries.")
        return
        
    with app.app_context():
        now_local = datetime.now()
        current_time_str = now_local.strftime('%H:%M')

        # Find users who want summaries
        users_for_summary = User.query.filter(
            (User.notification_preference == 'summary') | (User.notification_preference == 'both')
        ).all()

        for user in users_for_summary:
            if not user.summary_times:
                continue

            # Check if current time matches one of the user's summary times
            summary_times_list = [t.strip() for t in user.summary_times.split(',')]
            if current_time_str in summary_times_list:
                app.logger.info(f"Matched summary time {current_time_str} for user {user.user_id}")
                redis_key = f"summary_queue:{user.user_id}"
                try:
                    # Get all queued messages (LPOP until empty or use LRANGE + LTRIM)
                    queued_items_json = redis_conn.lrange(redis_key, 0, -1)
                    if not queued_items_json:
                        app.logger.info(f"No summary items queued for user {user.user_id} at {current_time_str}.")
                        continue # Nothing to summarize

                    # Get notification IDs from the queue
                    notification_ids = []
                    import json
                    for item_json in queued_items_json:
                        try:
                            item = json.loads(item_json)
                            notification_id = item.get('notification_id')
                            if notification_id:
                                notification_ids.append(notification_id)
                        except json.JSONDecodeError as e:
                            app.logger.error(f"Failed to decode JSON summary item for user {user.user_id}: {e}")
                    
                    # Find the last summary notification to prevent duplicates
                    last_summary = Notification.query.filter_by(
                        user_id=user.user_id,
                        notification_type='summary'
                    ).order_by(Notification.created_at.desc()).first()
                    
                    # Set the cutoff time to filter out older notifications that may have already been summarized
                    cutoff_time = last_summary.created_at if last_summary else None
                    
                    # Query database for notifications that haven't been included in a summary yet
                    query = Notification.query.filter(
                        Notification.id.in_(notification_ids),
                        Notification.included_in_summary == False
                    )
                    
                    # Add time filter if we have a last summary
                    if cutoff_time:
                        query = query.filter(Notification.created_at > cutoff_time)
                        
                    notifications = query.all()
                    
                    if not notifications:
                        app.logger.info(f"No new notifications to summarize for user {user.user_id}.")
                        # Clear the processed items from the Redis queue
                        redis_conn.ltrim(redis_key, len(queued_items_json), -1)
                        continue

                    # Process notifications
                    default_summary_prompt = "You are an AI that generates a consolidated summary of website changes from multiple comparison reports, your purpose is to summary all the send out notification. You will have input from all the AI compare description and summarizes. Write me output format to include bullet points with explanation. Summary what user want to compare. Skip what have been cover in the lastest summary notification. Be analytical and comprehensive."
                    summary_prompt = os.getenv('AI_NOTIFICATION_SUMMARY_SYSTEM_PROMPT', default_summary_prompt)
                    
                    summary_body_parts = [f"AI Website Monitor Summary for {current_time_str} UTC:"]
                    processed_count = 0
                    change_details = []
                    
                    for notification in notifications:
                        try:
                            # Get the website info
                            website = Website.query.get(notification.website_id)
                            if not website:
                                continue
                                
                            time_str = notification.created_at.strftime('%H:%M') if notification.created_at else '[time unknown]'
                            
                            # Store the change details for potential AI processing
                            change_details.append({
                                'url': website.url,
                                'time': time_str,
                                'description': notification.content
                            })
                            
                            # Also add to the basic summary format as fallback
                            summary_body_parts.append(f"\n- {website.url} ({time_str}): {notification.content}")
                            processed_count += 1
                        except Exception as e:
                            app.logger.error(f"Error processing notification {notification.id} for user {user.user_id}: {e}")

                    if processed_count > 0:
                        summary_body = ""
                        summary_subject = f"Website Change Summary - {current_time_str} UTC"
                        
                        # If we have the Gemini API key, try to generate a nicer summary
                        gemini_api_key = os.getenv('GEMINI_API_KEY')
                        if gemini_api_key and len(change_details) > 0:
                            try:
                                import google.generativeai as genai
                                genai.configure(api_key=gemini_api_key)
                                
                                # Prepare the prompt for the AI
                                ai_prompt = f"{summary_prompt}\n\n"
                                for i, change in enumerate(change_details, 1):
                                    ai_prompt += f"Site {i}: {change['url']} (at {change['time']})\n"
                                    ai_prompt += f"Change description: {change['description']}\n\n"
                                
                                # Generate the summary
                                model = genai.GenerativeModel('gemini-2.5-flash-preview-05-20')
                                response = model.generate_content(ai_prompt)
                                if response and response.text:
                                    # Use the AI-generated summary
                                    summary_body = f"AI Website Monitor Summary for {current_time_str} UTC:\n\n{response.text}"
                                    app.logger.info(f"Generated AI summary for user {user.user_id}")
                                else:
                                    # Fallback to the basic summary
                                    summary_body = "\n".join(summary_body_parts)
                                    app.logger.warning(f"AI summary generation returned empty result, using basic summary")
                            except Exception as e:
                                # Fallback to the basic summary
                                summary_body = "\n".join(summary_body_parts)
                                app.logger.error(f"Error generating AI summary: {e}, using basic summary")
                        else:
                            # Use the basic summary if no Gemini API key
                            summary_body = "\n".join(summary_body_parts)

                        # Create a summary notification record
                        summary_notification = Notification(
                            user_id=user.user_id,
                            website_id=None,  # Summary isn't specific to one website
                            check_history_id=None,  # Summary doesn't relate to a specific check
                            notification_type='summary',
                            content=summary_body,
                            screenshot_path=None,
                            sent=True
                        )
                        db.session.add(summary_notification)
                        db.session.flush()  # Get the ID without committing
                        
                        # Update all notifications as included in this summary
                        for notification in notifications:
                            notification.included_in_summary = True
                            notification.summary_id = summary_notification.id
                        
                        # Commit all changes to the database
                        db.session.commit()

                        # Send summary notifications
                        app.logger.info(f"Sending summary to user {user.user_id} ({processed_count} items)")
                        send_email_notification(user, summary_subject, summary_body)
                        send_telegram_notification(user.user_id, summary_body)
                        send_teams_notification(user.user_id, summary_body)

                        # Clear the processed items from the queue
                        redis_conn.ltrim(redis_key, len(queued_items_json), -1)
                        app.logger.info(f"Cleared summary queue {redis_key}")
                    else:
                        app.logger.warning(f"Failed to process any summary items for user {user.user_id} despite queue having {len(queued_items_json)} items.")

                except Exception as e:
                    app.logger.error(f"Error processing summary queue {redis_key} for user {user.user_id}: {e}", exc_info=True)


# Manual check route
@app.route('/manual_check/<website_id>')
def manual_check(website_id):
    """Manually trigger a check for a specific website."""
    app.logger.debug(f"Manual check requested for website ID: {website_id}")
    website = Website.query.get_or_404(website_id)
    
    # Get the user for this website to check permissions
    if not website:
        flash('Website not found.', 'danger')
        return redirect(url_for('dashboard', user_id=request.args.get('user_id', '')))
    
    try:
        # Using direct check for immediate feedback
        from tasks import check_website_direct  # Import here to avoid circular imports
        success, message, screenshot_path, ai_description = check_website_direct(website.id)
        
        if success:
            flash(f'Manual check complete: {message}', 'success')
        else:
            flash(f'Check failed: {message}', 'danger')
    except Exception as e:
        app.logger.error(f"Error during manual check for website ID {website_id}: {e}", exc_info=True)
        flash(f'Error during check: {str(e)}', 'danger')
    
    return redirect(url_for('dashboard', user_id=website.user_id))


# Test screenshot route (GET) - for direct testing
@app.route('/test_screenshot', methods=['GET'])
def test_screenshot():
    """Take a screenshot of a given URL and return the image."""
    url = request.args.get('url', 'https://www.example.com')
    output_filename = request.args.get('filename', 'test_screenshot.png')
    output_path = os.path.join('data', output_filename) # Save to data directory

    try:
        # Ensure data directory exists
        os.makedirs('data', exist_ok=True)
        # Call the Playwright screenshot function
        success, message = get_screenshot_playwright(url, output_path)
        if success:
            # Return the path to the saved screenshot
            return f"Screenshot of {url} saved to {output_path}"
        else:
            return f"Failed to capture screenshot of {url}: {message}"
    except Exception as e:
        app.logger.error(f"Exception during test_screenshot (GET): {e}")
        return f"An error occurred: {e}"


# Test screenshot route (POST) - for Add Website page
@app.route('/test_screenshot_add', methods=['POST'])
def test_screenshot_add():
    """Test screenshot from Add Website page."""
    url = request.form.get('url')
    if not url:
        return jsonify({'success': False, 'message': 'URL is required.'}), 400

    try:
        # Ensure data directory exists
        os.makedirs('data', exist_ok=True)
        # Construct output path
        timestamp = int(time.time())
        output_path = os.path.join('data', f'screenshot_test_add_{timestamp}.png')

        # Call the Playwright screenshot function with output_path
        success, message = get_screenshot_playwright(url, output_path)
        if success:
            # Return the path to the saved screenshot
            return jsonify({'success': True, 'message': 'Screenshot taken successfully.', 'screenshot_path': output_path})
        else:
            # Return failure message
            return jsonify({'success': False, 'message': f'Failed to take screenshot: {message}'}), 500
    except Exception as e:
        app.logger.error(f"Exception during test_screenshot_add: {e}")
        return jsonify({'success': False, 'message': f'An error occurred: {e}'}), 500


# Test screenshot route (POST) - for Edit Website page
@app.route('/test_screenshot', methods=['POST'])
def test_screenshot_edit():
    """Test screenshot from Edit Website page (expects JSON)."""
    data = request.get_json()
    url = data.get('url')
    website_id = data.get('website_id') # Assuming website_id is passed for unique filename

    if not url or website_id is None:
        return jsonify({'success': False, 'message': 'Missing URL or website_id'}), 400

    try:
        # Ensure data directory exists
        os.makedirs('data', exist_ok=True)
        # Construct output path
        timestamp = int(time.time())
        output_path = os.path.join('data', f'screenshot_test_edit_{website_id}_{timestamp}.png')

        # Call the Playwright screenshot function with output_path
        success, message = get_screenshot_playwright(url, output_path)
        if success:
            # Return the path to the saved screenshot
            return jsonify({'success': True, 'message': 'Screenshot taken successfully.', 'screenshot_path': output_path})
        else:
            # Return failure message
            return jsonify({'success': False, 'message': f'Failed to take screenshot: {message}'}), 500
    except Exception as e:
        app.logger.error(f"Exception during test_screenshot_edit: {e}")
        return jsonify({'success': False, 'message': f'An error occurred: {e}'}), 500


# Test the Playwright screenshot function directly (for debugging)
@app.route('/test_playwright_screenshot', methods=['GET'])
def test_playwright_screenshot():
    """Test the Playwright screenshot function directly."""
    url = request.args.get('url', 'https://www.example.com')
    output_filename = request.args.get('filename', 'test_playwright_screenshot.png')
    output_path = os.path.join('data', output_filename) # Save to data directory

    try:
        # Ensure data directory exists
        os.makedirs('data', exist_ok=True)
        success, message = get_screenshot_playwright(url, output_path)
        if success:
            return f"Screenshot of {url} saved to {output_path}"
        else:
            return f"Failed to capture screenshot of {url}: {message}"
    except Exception as e:
        return f"An error occurred: {e}"


@app.route('/test_email', methods=['POST'])
def test_email():
    """Test email notification sending."""
    user_id = request.form.get('user_id') # Assuming user_id is passed in form data
    user = User.query.filter_by(user_id=user_id).first()

    if not user:
        flash('User not found.', 'danger')
        return redirect(url_for('settings', user_id=user_id))

    subject = "Test Email from AI Website Monitor"
    body = f"This is a test email sent from your AI Website Monitor application for user {user.user_id}."

    # Call the send email function
    success, message = send_email_notification(user, subject, body)

    if success:
        flash(f'Test email sent successfully to {user.email}.', 'success')
    else:
        flash(f'Failed to send test email: {message}', 'danger')

    return redirect(url_for('settings', user_id=user_id))


@app.route('/test_telegram/<user_id>', methods=['POST'])
def test_telegram(user_id):
    """Test Telegram notification sending."""
    user = User.query.filter_by(user_id=user_id).first()

    if not user:
        flash('User not found.', 'danger')
        return redirect(url_for('settings', user_id=user_id))

    message = f"This is a test message from your AI Website Monitor for user {user.user_id}."

    # Call the send telegram function
    success, message = send_telegram_notification(user.user_id, message)

    if success:
        flash(f'Test Telegram message sent successfully to chat ID {user.telegram_chat_id}.', 'success')
    else:
        flash(f'Failed to send test Telegram message: {message}', 'danger')

    return redirect(url_for('settings', user_id=user_id))

@app.route('/test_gemini_api/<user_id>', methods=['POST'])
def test_gemini_api(user_id):
    # Admin Key Check
    submitted_admin_key = request.form.get('admin_key')
    correct_admin_key = os.getenv('ADMIN_KEY')
    if not correct_admin_key or submitted_admin_key != correct_admin_key:
        logger.warning(f"Unauthorized attempt to test Gemini API for user {user_id} (invalid/missing Admin Key).")
        flash('Invalid or missing Admin Key. API test not permitted.', 'danger')
        return redirect(url_for('settings', user_id=user_id))

    logger.info(f"Admin-authorized request received to test Gemini API for user {user_id}")

    app.logger.info(f"Starting Gemini API key test for user {user_id}.")
    import google.generativeai as genai
    import os

    # Find all Gemini API keys in environment variables
    gemini_keys = {}
    for key, value in os.environ.items():
        if key.startswith('GEMINI_API_KEY') and value:
            gemini_keys[key] = value

    if not gemini_keys:
        flash('No GEMINI_API_KEY environment variables found in .env file.', 'warning')
        app.logger.warning("No Gemini API keys found in environment for testing.")
        return redirect(url_for('settings', user_id=user_id))

    all_valid = True
    for name, key in gemini_keys.items():
        try:
            app.logger.debug(f"Testing Gemini API key: {name}")
            genai.configure(api_key=key)
            # Make a simple, low-cost call, like listing models
            models = genai.list_models()
            # Check if the required vision model ('gemini-2.5-flash-preview-05-20') is available
            vision_model_found = any('gemini-2.5-flash-preview-05-20' in m.name for m in models)
            if vision_model_found:
                 flash(f'API Key "{name}" is VALID and supports gemini-2.5-flash-preview-05-20.', 'success')
                 app.logger.info(f"Gemini API key {name} is valid and supports required model.")
            else:
                flash(f"API Key \"{name}\" is VALID but required model 'gemini-2.5-flash-preview-05-20' not found in list.", 'warning')
                app.logger.warning(f"Gemini API key {name} is valid but required model 'gemini-2.5-flash-preview-05-20' missing.")
                all_valid = False # Consider it not fully valid if the needed model isn't there
        except Exception as e:
            flash(f'API Key "{name}" is INVALID. Error: {e}', 'danger')
            app.logger.error(f"Gemini API key {name} failed validation: {e}")
            all_valid = False

    if all_valid and len(gemini_keys) > 0:
         flash('All configured Gemini API keys tested successfully!', 'success')
    elif len(gemini_keys) > 0:
        flash('One or more Gemini API keys failed validation. See details above.', 'warning')
    
    return redirect(url_for('settings', user_id=user_id))

@app.route('/test_gemini_api_simple', methods=['POST'])
def test_gemini_api_simple():
    """Test Gemini API connection simply, return JSON for index page JS."""
    app.logger.info("Starting simple Gemini API key test (for index page).")
    import google.generativeai as genai
    import os

    # Collect potential API keys
    api_keys = []
    base_key = os.getenv('GEMINI_API_KEY')
    if base_key: api_keys.append(base_key)
    for i in range(1, 11): 
        numbered_key = os.getenv(f'GEMINI_API_KEY_{i}')
        if numbered_key: api_keys.append(numbered_key)

    if not api_keys:
        msg = 'No Gemini API keys found in .env.'
        app.logger.warning(msg)
        return jsonify(success=False, error=msg)

    for key in api_keys:
        masked_key = f"...{key[-4:]}" if key and len(key) > 4 else "********"
        try:
            genai.configure(api_key=key)
            models = genai.list_models()
            # Check if the required vision model is available
            if any('gemini-2.5-flash-preview-05-20' in m.name for m in models):
                msg = f"Connection successful with key ending in {masked_key} (supports gemini-1.5-flash)."
                app.logger.info(msg)
                return jsonify(success=True, ai_result=msg)
            else:
                 app.logger.warning(f"Key ending in {masked_key} is valid but 'gemini-2.5-flash-preview-05-20' not found.")
                 # Continue checking other keys
        except Exception as e:
            app.logger.error(f"Gemini API test failed with key ending in {masked_key}: {e}")
            # Continue checking other keys

    # If loop finishes without finding a suitable key
    msg = "Failed to connect using any key, or no key supports gemini-2.5-flash-preview-05-20."
    app.logger.error(msg)
    return jsonify(success=False, error=msg)

@app.route('/test_email_notification/<user_id>', methods=['POST'])
def test_email_notification_route(user_id):
    user = User.query.filter_by(user_id=user_id).first()
    if not user or not user.email:
        flash('User not found or no email address configured.', 'warning')
        return redirect(url_for('settings', user_id=user_id))
    
    subject = "Test Email Notification from AI Website Monitor"
    body = f"This is a test email notification for user {user.user_id}. If you received this, email notifications are working."
    app.logger.info(f"Attempting to send test email to {user.email} for user {user_id}")
    success, message = send_email_notification(user, subject, body)
    if success:
        flash(f'Test email sent successfully to {user.email}.', 'success')
        app.logger.info(f"Test email successful for user {user_id}.")
    else:
        flash(f'Failed to send test email to {user.email}. Error: {message}', 'danger')
        app.logger.error(f"Test email failed for user {user_id}: {message}")
    return redirect(url_for('settings', user_id=user_id))

@app.route('/test_telegram_notification/<user_id>', methods=['POST'])
def test_telegram_notification_route(user_id):
    user = User.query.filter_by(user_id=user_id).first()
    if not user:
        flash('User not found.', 'warning')
        return redirect(url_for('settings', user_id=user_id))
    
    # Use custom token/chat_id if available, otherwise fallback to global
    if not user.telegram_token and not os.getenv('TELEGRAM_BOT_TOKEN'):
         flash('No Telegram Bot Token configured (User or Global).', 'warning')
         return redirect(url_for('settings', user_id=user_id))
    if not user.telegram_chat_id and not os.getenv('TELEGRAM_CHAT_ID'):
         flash('No Telegram Chat ID configured (User or Global).', 'warning')
         return redirect(url_for('settings', user_id=user_id))

    message = f"This is a test Telegram notification for user {user.user_id}. If you received this, Telegram notifications are working."
    app.logger.info(f"Attempting to send test Telegram message for user {user_id}")
    success, response_msg = send_telegram_notification(user.user_id, message) # Pass user_id, function handles token/chat_id logic
    if success:
        flash('Test Telegram message sent successfully.', 'success')
        app.logger.info(f"Test Telegram successful for user {user_id}.")
    else:
        flash(f'Failed to send test Telegram message. Error: {response_msg}', 'danger')
        app.logger.error(f"Test Telegram failed for user {user_id}: {response_msg}")
    return redirect(url_for('settings', user_id=user_id))

@app.route('/test_teams_notification/<user_id>', methods=['POST'])
def test_teams_notification_route(user_id):
    user = User.query.filter_by(user_id=user_id).first()
    if not user:
        flash('User not found.', 'warning')
        return redirect(url_for('settings', user_id=user_id))

    # Use custom webhook if available, otherwise fallback to global
    webhook_url = user.teams_webhook or os.getenv('TEAMS_WEBHOOK_URL')
    if not webhook_url:
        flash('No Teams Webhook URL configured (User or Global).', 'warning')
        return redirect(url_for('settings', user_id=user_id))

    message = f"This is a test Teams notification for user {user.user_id}. If you received this, Teams notifications are working."
    app.logger.info(f"Attempting to send test Teams message for user {user_id}")
    success, response_msg = send_teams_notification(user.user_id, message) # Pass user_id, function handles webhook logic
    if success:
        flash('Test Teams message sent successfully.', 'success')
        app.logger.info(f"Test Teams successful for user {user_id}.")
    else:
        flash(f'Failed to send test Teams message. Error: {response_msg}', 'danger')
        app.logger.error(f"Test Teams failed for user {user_id}: {response_msg}")
    return redirect(url_for('settings', user_id=user_id))

@app.route('/test_url_and_analyze', methods=['POST'])
def test_url_and_analyze():
    """Takes a URL, gets screenshot, gets AI description.
    Used for testing before adding or for dedicated test button.
    Returns JSON response.
    """
    app.logger.debug("Received request for /test_url_and_analyze")
    try:
        data = request.get_json()
        if not data:
            app.logger.warning("Invalid or missing JSON data in request to /test_url_and_analyze")
            return jsonify(success=False, message="Invalid request format: Missing JSON data"), 400
            
        url = data.get('url')
        user_id = data.get('user_id') # Optional: for context/logging
        ai_focus_area = data.get('ai_focus_area') # Optional: pass focus

        if not url:
            app.logger.warning("Missing URL in /test_url_and_analyze request.")
            return jsonify(success=False, message="URL is required."), 400

        app.logger.info(f"Testing URL {url} for user {user_id or 'N/A'} with focus '{ai_focus_area or 'None'}'")

        # Generate paths for temp screenshot
        try:
            name = safe_filename(url)
            timestamp = int(time.time())
            screenshot_filename = f"screenshot_test_{name}_{timestamp}.png"
            screenshot_path_rel = os.path.join('data', screenshot_filename) # Relative path for response
            screenshot_path_abs = os.path.abspath(screenshot_path_rel)
            os.makedirs(os.path.dirname(screenshot_path_abs), exist_ok=True)
            app.logger.debug(f"Absolute screenshot path for test: {screenshot_path_abs}")
        except Exception as e:
            app.logger.error(f"Error creating paths for test screenshot: {e}", exc_info=True)
            return jsonify(success=False, message=f"Error preparing for screenshot: {e}"), 500

        # Import screenshot function here to avoid circular imports
        from browser_agent.screenshot import get_screenshot_playwright

        # Call Screenshot Function with increased timeout
        screenshot_success = False
        screenshot_message = "Screenshot step skipped."
        try:
            screenshot_success, screenshot_message = get_screenshot_playwright(url, screenshot_path_abs)
            if not screenshot_success:
                app.logger.error(f"Screenshot failed during test: {screenshot_message}")
        except Exception as e:
            app.logger.error(f"Exception during get_screenshot_playwright call in test: {e}", exc_info=True)
            screenshot_message = f"Screenshot exception: {e}"

        # Call AI Analysis (only if screenshot exists)
        ai_description = "AI analysis skipped (screenshot failed or not taken)."
        ai_success = False
        if screenshot_success and os.path.exists(screenshot_path_abs):
            app.logger.debug(f"Calling AI analysis for test screenshot: {screenshot_path_abs}")
            try:
                # Add a safety check in case Gemini API is not set up
                if not os.getenv('GEMINI_API_KEY'):
                    app.logger.warning("No Gemini API key found for AI analysis")
                    ai_description = "AI analysis skipped (No Gemini API key configured)"
                else:
                    ai_description = gemini_vision_api_compare(html=None, screenshot_path=screenshot_path_abs, ai_focus_area=ai_focus_area)
                    app.logger.info("AI analysis successful during test.")
                    # Basic check if AI description indicates an error
                    if not ai_description or "error" in ai_description.lower() or "failed" in ai_description.lower() or "exception" in ai_description.lower():
                        app.logger.warning(f"AI analysis for test returned potential error description: {ai_description[:100]}")
                        ai_success = False # Consider it not fully successful if AI reports error
                    else:
                        ai_success = True
            except Exception as e:
                app.logger.error(f"Exception during AI analysis call in test: {e}", exc_info=True)
                ai_description = f"AI analysis exception: {e}"
                ai_success = False
        else:
            app.logger.warning("Skipping AI analysis for test because screenshot failed or path doesn't exist.")

        # Determine overall success and final message
        overall_success = screenshot_success # Consider success if at least screenshot worked
        final_message = f"Screenshot: {screenshot_message}. AI Analysis: {ai_description}"
        if not screenshot_success:
            final_message = f"Screenshot Failed: {screenshot_message}. AI analysis skipped."
        elif not ai_success and screenshot_success:
            final_message = f"Screenshot OK. AI Analysis Issues: {ai_description}"
        elif overall_success:
            final_message = f"Screenshot successful. AI Description: {ai_description}"

        app.logger.debug(f"Test result: success={overall_success}, message={final_message[:100]}...")
        return jsonify(
            success=overall_success,
            message=final_message,
            screenshot_path=screenshot_path_rel if screenshot_success else None,
            ai_description=ai_description
        )
    except Exception as e:
        app.logger.error(f"Unhandled exception in test_url_and_analyze: {e}", exc_info=True)
        return jsonify(success=False, message=f"Internal server error: {str(e)}"), 500

# Initialize database and scheduler
def init_app():
    with app.app_context():
        db.create_all()
        # Check if scheduler is already running before starting
        if not scheduler.running:
            app.logger.info("Starting scheduler...")
            scheduler.start()
            app.logger.info("Scheduler started successfully. Jobs:")
            for job in scheduler.get_jobs():
                app.logger.info(f"- Job: {job.name}, Trigger: {job.trigger}, Next run: {job.next_run_time}")
        else:
            app.logger.info("Scheduler already running.")
            print("[DEBUG] Scheduler already running.")

    return app

# --- Diagnostic Routes --- #
@app.route('/debug/scheduler')
def debug_scheduler():
    """Diagnostic route to check scheduler status and manually trigger scheduled checks."""
    try:
        scheduler_status = {
            'running': scheduler.running,
            'jobs': []
        }
        
        for job in scheduler.get_jobs():
            job_info = {
                'name': job.name,
                'trigger': str(job.trigger),
            }
            # Safely add next_run_time if it exists
            if hasattr(job, 'next_run_time'):
                job_info['next_run'] = str(job.next_run_time)
            else:
                job_info['next_run'] = "Not scheduled"
                
            scheduler_status['jobs'].append(job_info)
        
        return jsonify(scheduler_status)
    except Exception as e:
        app.logger.error(f"Error in debug_scheduler: {e}", exc_info=True)
        return jsonify({
            'status': 'error',
            'message': f'Error getting scheduler status: {str(e)}'
        }), 500

@app.route('/debug/run_scheduled_checks')
def debug_run_scheduled_checks():
    """Manually trigger the scheduled_checks function."""
    # Admin Key Check (optional security)
    # admin_key = request.args.get('key')
    # if admin_key != os.getenv('ADMIN_KEY'):
    #     return "Unauthorized", 401
    
    app.logger.info("Manually triggering scheduled_checks")
    try:
        scheduled_checks()
        return jsonify({
            'status': 'success',
            'message': 'Scheduled checks triggered successfully. Check the logs for details.'
        })
    except Exception as e:
        app.logger.error(f"Error running scheduled checks: {e}", exc_info=True)
        return jsonify({
            'status': 'error',
            'message': f'Error running scheduled checks: {str(e)}'
        }), 500

# Simple test job to verify RQ worker is functioning
def test_rq_job(message="Test job"):
    """Simple test job to verify RQ worker."""
    import logging
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)
    logger.info(f"RQ TEST JOB EXECUTED: {message}")
    return f"RQ test job executed: {message}"

@app.route('/debug/test_rq')
def debug_test_rq():
    """Enqueue a test job to verify RQ worker is functioning."""
    try:
        # Import tasks module to fix the "__main__ module" issue
        from tasks import test_rq_task
        
        # Get a fresh Redis connection for this request
        redis_conn = get_redis_connection()
        if not redis_conn:
            return jsonify({
                'status': 'error',
                'message': 'Could not connect to Redis. Check if Redis is running.'
            }), 500
            
        q = Queue(connection=redis_conn)
        test_message = f"Test at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        job = q.enqueue(test_rq_task, test_message)
        
        return jsonify({
            'status': 'success',
            'message': 'Test job enqueued successfully',
            'job_id': job.id,
            'note': 'Check your logs to see if the worker processes this job'
        })
    except Exception as e:
        app.logger.error(f"Error enqueueing test job: {e}")
        return jsonify({
            'status': 'error',
            'message': f'Error enqueueing test job: {str(e)}'
        }), 500

# Function for use with Waitress and Docker
def create_app():
    """Factory function for creating the Flask application for production use"""
    global queue
    
    # Initialize the app first
    app_instance = init_app()
    
    # Initialize Redis connection and RQ queue after app is created
    try:
        redis_conn = get_redis_connection()
        if redis_conn:
            queue = Queue(connection=redis_conn)
            app.logger.info("RQ Queue initialized successfully")
        else:
            app.logger.warning("Failed to initialize Redis connection. RQ Queue will not work.")
    except Exception as e:
        app.logger.error(f"Error initializing Redis/RQ: {e}")
    
    return app_instance

# Add missing CSS class for warning status badge if not already defined
@app.route('/static/css/styles.css')
def serve_css():
    css_content = """
    /* Existing CSS content */
    
    /* Status badge colors */
    .status-badge.error { background-color: #f44336; }
    .status-badge.success { background-color: #4CAF50; }
    .status-badge.captcha { background-color: #9C27B0; }
    .status-badge.checking { background-color: #2196F3; }
    .status-badge.no-change { background-color: #4CAF50; }
    .status-badge.active { background-color: #3f51b5; }
    .status-badge.warning { background-color: #ff9800; } /* Warning status for change detection */
    """
    return Response(css_content, mimetype='text/css')

@app.route('/test-notification/<user_id>', methods=['POST'])
def test_notification(user_id):
    """Test both Gmail and Telegram notification sending for a user."""
    user = User.query.filter_by(user_id=user_id).first()
    if not user:
        flash('User not found.', 'danger')
        return redirect(url_for('settings', user_id=user_id))
    test_subject = "Test Notification from AI Website Monitor"
    test_body = f"This is a test notification for user {user.user_id}. If you receive this, notifications are working."
    email_success, email_message = send_email_notification(user, test_subject, test_body)
    telegram_success, telegram_message = send_telegram_notification(user.user_id, test_body)
    if email_success and telegram_success:
        flash('Test Gmail and Telegram notifications sent successfully.', 'success')
    else:
        flash(f'Gmail success: {email_success}, Telegram success: {telegram_success}. Email message: {email_message}, Telegram message: {telegram_message}', 'danger')
    return redirect(url_for('settings', user_id=user_id))

if __name__ == '__main__':
    # Check if running in debug mode (reloader active)
    # The reloader runs the main script twice, which can cause issues
    # with scheduler starting twice or port conflicts.
    if not os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        app_instance = init_app()
    # Use waitress for running the app instead of Flask dev server
    # Note: waitress doesn't have auto-reload. Use flask run for development if needed.
    # from waitress import serve
    # serve(app_instance, host='0.0.0.0', port=5000)

    # Keeping Flask dev server for now, waitress integration will be in run_all.bat
    app.run(debug=True, host='0.0.0.0', port=5000, use_reloader=False) # Disable reloader for stability with scheduler
