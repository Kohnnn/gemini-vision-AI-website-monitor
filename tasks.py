import os
from datetime import datetime
import logging # Import logging
from rq import get_current_job
from config import get_redis_connection, logger
import json # Import json
import requests

# No need to configure logging here since we're importing from config
# Use the logger from config

# Simple test task to verify RQ worker is processing jobs
def test_rq_task(message="Test job"):
    """Simple test job to verify RQ worker."""
    logger.info(f"RQ TEST TASK EXECUTED: {message}")
    print(f"RQ TEST TASK EXECUTED: {message}")  # Also print to stdout for visibility
    return f"RQ test job executed: {message}"

# Helper function to get a Redis connection and handle errors
def get_redis():
    """Get a Redis connection and handle any errors."""
    try:
        conn = get_redis_connection()
        if not conn:
            logger.error("Failed to get Redis connection in task")
            return None
        return conn
    except Exception as e:
        logger.error(f"Error getting Redis connection in task: {e}")
        return None

# Function to safely add to the Redis queue
def add_to_summary_queue(user_id, notification_payload):
    """Safely add a notification to the summary queue."""
    try:
        redis_conn = get_redis()
        if not redis_conn:
            logger.error(f"Cannot queue summary for user {user_id}: Redis connection failed")
            return False
            
        redis_key = f"summary_queue:{user_id}"
        payload_json = json.dumps(notification_payload)
        redis_conn.rpush(redis_key, payload_json)
        redis_conn.expire(redis_key, 172800)  # 48 hours expiry
        logger.info(f"Queued summary for user {user_id}, notification ID: {notification_payload.get('notification_id', 'unknown')}")
        return True
    except Exception as e:
        logger.error(f"Failed to queue summary for user {user_id}: {e}")
        return False

# --- Background Job: Check Website ---
def check_website(website_id, retry_count=0, max_retries=3):
    logger.debug(f"Starting RQ job check_website for website ID: {website_id}") # Added logging
    from app import db, User, Website, CheckHistory, safe_filename
    from app import compare_html, fetch_website_content, gemini_vision_api_compare, detect_anomaly, send_email_notification, send_telegram_notification, send_teams_notification
    website = db.session.get(Website, website_id)
    if not website:
        logger.error(f"Website with ID {website_id} not found in check_website.") # Added logging
        return
    user = User.query.filter_by(user_id=website.user_id).first()
    if not user:
        logger.error(f"User with user_id {website.user_id} not found for website ID {website_id} in check_website.") # Added logging
        return
    prev_check = CheckHistory.query.filter_by(website_id=website_id).order_by(CheckHistory.checked_at.desc()).first()
    old_html = prev_check.html_path and open(prev_check.html_path).read() if prev_check else ''
    start_time = datetime.now()
    html, _, error = fetch_website_content(website)
    end_time = datetime.now()
    response_time = (end_time - start_time).total_seconds()
    if error:
        logger.error(f"Error fetching content for website ID {website_id}: {error}") # Added logging
        # CAPTCHA detection
        if html and ('captcha' in html.lower() or 'recaptcha' in html.lower() or 'i am not a robot' in html.lower()):
            website.status = 'captcha'
            website.error_message = 'CAPTCHA detected on the website. Manual intervention required.'
            db.session.commit()
            send_email_notification(user, f'Website Monitor CAPTCHA: {website.url}', 'CAPTCHA detected. Please solve it manually.')
            return
        # Retry logic
        if retry_count < max_retries:
            logger.warning(f"Retrying check for website ID {website_id}. Attempt {retry_count + 1}/{max_retries}") # Added logging
            import time
            time.sleep(2 ** retry_count)
            return check_website(website_id, retry_count + 1, max_retries)
        website.status = 'error'
        website.error_message = error
        db.session.commit()
        send_email_notification(user, f'Website Monitor Error: {website.url}', error)
        return
    # If ai_section is set, extract only that part from html for AI diff
    ai_section = website.ai_section
    html_for_ai = html
    if ai_section:
        import re
        m = re.search(ai_section, html, re.IGNORECASE)
        if m:
            html_for_ai = m.group(0)
    diff = compare_html(old_html, html_for_ai) if old_html else ''
    # Screenshot capture
    now = datetime.now()
    name = safe_filename(website.url or getattr(website, 'name', 'website'))
    timestamp = now.strftime('%Y%m%d_%H%M%S')
    screenshot_path = f"data/screenshot_{name}_{timestamp}.png"
    try:
        from app import get_screenshot_playwright
        get_screenshot_playwright(website.url, screenshot_path)
        logger.debug(f"Screenshot captured for website ID {website_id} at {screenshot_path}") # Added logging
    except Exception as e:
        error_msg = str(e)
        screenshot_path = None
        logger.error(f"Screenshot error for website ID {website_id}: {error_msg}") # Added logging
        # Check if the error is due to CAPTCHA detected by the screenshot function
        if "CAPTCHA detected" in error_msg:
            website.status = 'captcha'
            website.error_message = 'CAPTCHA detected during screenshot capture. Manual intervention required.'
            db.session.commit()
            send_email_notification(user, f'Website Monitor CAPTCHA: {website.url}', 'CAPTCHA detected during screenshot capture. Please solve it manually.')
            return # Stop processing if CAPTCHA is detected during screenshot

    ai_description = gemini_vision_api_compare(
        html=None, # Pass None for HTML if only using image
        screenshot_path=screenshot_path, # Pass absolute path to AI func
        monitoring_type=website.monitoring_type,
        monitoring_keywords=website.monitoring_keywords,
        ai_focus_area=website.ai_focus_area
    )
    
    # Determine if changes were detected based on AI description
    change_indicators = ["website changed", "change detected", "difference found", "new content"]
    change_detected = any(indicator in ai_description.lower() for indicator in change_indicators)
    logger.debug(f"Change detection based on AI description for website {website_id}: {'Yes' if change_detected else 'No'}")
    
    # Save HTML and screenshot to files
    html_path = f"data/html_{name}_{timestamp}.html"
    try:
        with open(html_path, 'w', encoding='utf-8') as f:
            f.write(html)
        logger.debug(f"HTML saved for website ID {website_id} at {html_path}") # Added logging
    except Exception as e:
        logger.error(f"Error saving HTML for website ID {website_id}: {e}") # Added logging
        html_path = None # Ensure html_path is None if saving fails

    diff_path = None
    if change_detected:
        diff_path = f"data/diff_{name}_{timestamp}.txt"
        try:
            with open(diff_path, 'w', encoding='utf-8') as f:
                f.write(diff)
            logger.debug(f"Diff saved for website ID {website_id} at {diff_path}") # Added logging
        except Exception as e:
            logger.error(f"Error saving diff for website ID {website_id}: {e}") # Added logging
            diff_path = None # Ensure diff_path is None if saving fails

    anomalies = detect_anomaly(website, prev_check, html, response_time, error)
    check = CheckHistory(
        website_id=website_id,
        screenshot_path=screenshot_path,
        html_path=html_path,
        diff_path=diff_path,
        ai_description=ai_description,
        change_detected=change_detected,
        response_time=response_time,
        error=error
    )
    db.session.add(check)
    if anomalies:
        website.status = 'anomaly'
        website.error_message = '; '.join(anomalies)
        logger.warning(f"Anomalies detected for website ID {website_id}: {website.error_message}") # Added logging
        # Teams notification
        if user.teams_webhook:
            send_teams_notification(user.teams_webhook, f"Anomaly detected for {website.url}: {'; '.join(anomalies)}")
        # Telegram/email notification logic can also be triggered here
    else:
        website.status = 'change' if change_detected else 'no-change'
        website.error_message = None
        logger.debug(f"Status set to '{website.status}' for website {website_id}.")
    website.last_checked = now
    db.session.commit()
    logger.debug(f"Check history saved and website status updated for website ID {website_id}.") # Added logging

    if change_detected:
        notify_msg = f'Change detected on {website.url}:\n{ai_description}'
        logger.info(f"Change detected for website ID {website_id}. Sending notifications.") # Added logging
        
        # Send email notification
        email_success, email_message = send_email_notification(user, f'Change Detected: {website.url}', notify_msg, screenshot_path)
        if not email_success:
            logger.error(f"Email notification failed for website ID {website_id}: {email_message}")

        # Send Telegram notification
        telegram_success, telegram_message = send_telegram_notification(user.user_id, notify_msg)
        if not telegram_success:
            logger.error(f"Telegram notification failed for website ID {website_id}: {telegram_message}")

    # --- Handle Notifications/Summaries --- #
    # Check if we should send notifications based on user preferences and change detection
    should_notify = change_detected or not getattr(user, 'notify_only_changes', True)
    
    if should_notify and user: # Only notify/summarize if appropriate and user exists
        notification_payload = {
            'website_url': website.url,
            'website_id': website.id,
            'user_id': user.user_id, # Store user_id
            'ai_description': ai_description,
            'screenshot_path': screenshot_path, # Relative path
            'timestamp': now.isoformat(), # Use ISO format for timestamp
            'change_detected': change_detected # Add change status to payload
        }
        pref = user.notification_preference

        if pref in ['immediate', 'both']:
            # Set subject based on whether a change was detected
            subject = f"Change Detected: {website.url}" if change_detected else f"Website Check: {website.url}"
            logger.info(f"Sending immediate {'change' if change_detected else 'status'} notification for {website.url} to user {user.user_id}")
            
            # Check if the AI description appears to be an error message
            is_error_desc = "error" in ai_description.lower() or "failed" in ai_description.lower() or "exception" in ai_description.lower()
            
            # Try to generate a better notification message using AI if available
            default_notification_prompt = "You are an AI that summarizes the differences between two website screenshots/html based on user-specified criteria, your purpose is to send notification on the summary of what different. Write me output format to include bullet points with explanation. Summary what user want to compare. Skip what have been cover in the lastest notification, which include in the page. Be analytical and comprehensive."
            notification_prompt = os.getenv('AI_NOTIFICATION_SYSTEM_PROMPT', default_notification_prompt)
            
            try:
                # Check if we have a Gemini API key for AI notification enhancement
                gemini_api_key = os.getenv('GEMINI_API_KEY')
                if gemini_api_key and ai_description and not is_error_desc:
                    # Import here to avoid circular imports
                    import google.generativeai as genai
                    from app import app
                    
                    genai.configure(api_key=gemini_api_key)
                    
                    # Prepare the prompt for the AI
                    ai_prompt = f"{notification_prompt}\n\nWebsite: {website.url}\nTime: {now.strftime('%Y-%m-%d %H:%M:%S')}\nChange description: {ai_description}"
                    
                    # Generate the notification
                    model = genai.GenerativeModel('gemini-1.5-flash-latest')
                    response = model.generate_content(ai_prompt)
                    
                    if response and response.text:
                        # Use the AI-generated notification
                        if change_detected:
                            body = f"Change detected on {website.url} at {now.strftime('%Y-%m-%d %H:%M:%S')}:\n\n{response.text}"
                        else:
                            body = f"Website check completed for {website.url} at {now.strftime('%Y-%m-%d %H:%M:%S')}:\n\nNo changes detected. {response.text}"
                        app.logger.info("Generated enhanced AI notification message")
                    else:
                        # Fallback to basic notification
                        if change_detected:
                            body = f"Change detected on {website.url} at {now.strftime('%Y-%m-%d %H:%M:%S')}:\n\n{ai_description}"
                        else:
                            body = f"Website check completed for {website.url} at {now.strftime('%Y-%m-%d %H:%M:%S')}:\n\nNo changes detected. Status: {website.status}"
                        app.logger.warning("AI notification generation returned empty result, using basic message")
                else:
                    # Use the basic notification if no API key or error in AI description
                    if change_detected:
                        body = f"Change detected on {website.url} at {now.strftime('%Y-%m-%d %H:%M:%S')}:\n\n{ai_description}"
                    else:
                        body = f"Website check completed for {website.url} at {now.strftime('%Y-%m-%d %H:%M:%S')}:\n\nNo changes detected. Status: {website.status}"
            except Exception as e:
                # Fallback to basic notification on any error
                if change_detected:
                    body = f"Change detected on {website.url} at {now.strftime('%Y-%m-%d %H:%M:%S')}:\n\n{ai_description}"
                else:
                    body = f"Website check completed for {website.url} at {now.strftime('%Y-%m-%d %H:%M:%S')}:\n\nNo changes detected. Status: {website.status}"
                app.logger.error(f"Error generating AI notification: {e}, using basic message")
            
            # Store notification in database
            try:
                from app import Notification
                notification = Notification(
                    user_id=user.user_id,
                    website_id=website.id,
                    check_history_id=check.id,
                    notification_type='immediate',
                    content=body,
                    screenshot_path=screenshot_path,
                    sent=True  # Mark as sent since we're sending it immediately
                )
                db.session.add(notification)
                db.session.commit()
                logger.info(f"Stored immediate notification in database for user {user.user_id}, website {website.id}")
            except Exception as e:
                logger.error(f"Failed to store notification in database: {e}")
                # Continue with sending even if storage fails
            
            # Trigger immediate notifications
            send_email_notification(user, subject, body, screenshot_path)
            send_telegram_notification(user.user_id, body)
            send_teams_notification(user.user_id, body)

        if pref in ['summary', 'both']:
            try:
                # Store the notification in the database for summary purposes
                from app import Notification
                notification = Notification(
                    user_id=user.user_id,
                    website_id=website.id,
                    check_history_id=check.id,
                    notification_type='immediate',  # It's still an immediate notification, just for summary use
                    content=ai_description,  # Store the original AI description for summary use
                    screenshot_path=screenshot_path,
                    sent=False,  # Not sent directly, will be included in summary
                    included_in_summary=False  # Not yet included in any summary
                )
                db.session.add(notification)
                db.session.commit()
                
                # Add notification ID to the payload
                notification_payload['notification_id'] = notification.id
                
                # Use the helper function to add to the queue
                add_to_summary_queue(user.user_id, notification_payload)
            except Exception as e:
                logger.error(f"Failed to queue change summary for user {user.user_id}: {e}")

    logger.debug(f"Finished RQ job check_website for website ID: {website_id}") # Added logging


# --- Direct Execution Function for Manual Checks / Initial Check ---
def check_website_direct(website_id):
    """Direct execution version of check_website.\nTakes screenshot, gets HTML, calls AI for description, saves history.\nReturns tuple: (success_boolean, message_string, screenshot_path, ai_description)\n"""
    logger.debug(f"Starting direct website check for ID: {website_id}") # Added logging
    # Import necessary components locally
    from app import app, db, Website, CheckHistory, User, safe_filename, gemini_vision_api_compare, send_email_notification, send_telegram_notification, send_teams_notification # Import needed functions locally
    from browser_agent.screenshot import get_screenshot_playwright
    import os
    import difflib # Keep difflib for potential future use or logging
    from datetime import datetime
    import requests

    screenshot_path = None
    ai_description = "AI analysis pending."
    error_message = None
    success = False
    check_history_entry = None

    try:
        # Use app_context for database operations
        with app.app_context():
            website = Website.query.filter_by(id=website_id).first()
            if not website:
                error_message = f"Website ID {website_id} not found in database."
                logger.error(error_message)
                return False, error_message, None, None
            
            user = User.query.filter_by(user_id=website.user_id).first()
            if not user:
                error_message = f"User {website.user_id} not found for website ID {website_id}."
                logger.error(error_message)
                return False, error_message, None, None
            
            # Get latest check history to use as baseline
            prev_check = CheckHistory.query.filter_by(website_id=website_id).order_by(CheckHistory.checked_at.desc()).first()
            
            # --- Capture Screenshot --- #
            now = datetime.now()
            datestamp = now.strftime("%Y%m%d_%H%M%S")
            screenshot_filename = f"screenshot_{safe_filename(website.url)}_{datestamp}.png"
            
            # Use DATA_DIR from config if available, otherwise use default 'data' directory
            data_dir = app.config.get('DATA_DIR', 'data')
            os.makedirs(data_dir, exist_ok=True)  # Ensure the directory exists
            screenshot_path = os.path.join(data_dir, screenshot_filename)
            screenshot_path_rel = os.path.join('data', screenshot_filename)

            # Check if a proxy is configured at website level
            website_proxy = website.proxy
            
            # For sites that have anti-bot protection, try alternative techniques
            success = False
            error_message = None
            screenshot_attempt = 1
            max_screenshot_attempts = 3
            proxy_alternatives = []
            
            # Add alternative proxy options if needed
            if os.environ.get('BACKUP_PROXY'):
                proxy_alternatives.append(os.environ.get('BACKUP_PROXY'))
                
            try:
                # Try to get a list of free proxies as last resort
                response = requests.get('https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt', timeout=5)
                if response.status_code == 200:
                    proxy_list = response.text.strip().split('\n')
                    if proxy_list:
                        # Add a few random proxies from the list
                        import random
                        samples = random.sample(proxy_list, min(3, len(proxy_list)))
                        proxy_alternatives.extend([f"http://{p}" for p in samples])
            except Exception as e:
                logger.warning(f"Failed to fetch alternative proxies: {e}")
            
            while screenshot_attempt <= max_screenshot_attempts and not success:
                try:
                    # Use the website's proxy for the first attempt
                    current_proxy = website_proxy if screenshot_attempt == 1 else None
                    
                    # Try an alternative proxy for subsequent attempts if available
                    if screenshot_attempt > 1 and proxy_alternatives:
                        current_proxy = proxy_alternatives[min(screenshot_attempt-2, len(proxy_alternatives)-1)]
                    
                    logger.info(f"Attempt {screenshot_attempt}/{max_screenshot_attempts} to get screenshot of {website.url}")
                    if current_proxy:
                        logger.info(f"Using proxy: {current_proxy}")
                    
                    screenshot_success, screenshot_message = get_screenshot_playwright(
                        website.url, 
                        screenshot_path, 
                        proxy=current_proxy
                    )
                    
                    if screenshot_success:
                        success = True
                        break
                    else:
                        error_message = screenshot_message
                        screenshot_attempt += 1
                        
                except Exception as e:
                    error_message = f"Screenshot error (attempt {screenshot_attempt}): {str(e)}"
                    logger.error(error_message)
                    screenshot_attempt += 1
            
            # If all screenshot attempts failed
            if not success:
                # Record an error in the database
                check_history_entry = CheckHistory(
                    website_id=website.id,
                    error=error_message,
                    checked_at=now
                )
                db.session.add(check_history_entry)
                
                # Update website status
                website.status = 'error'
                website.error_message = error_message[:512]  # Truncate if needed
                website.last_checked = now
                db.session.commit()
                
                return False, error_message, None, None
            
            # Step 2: Get AI description
            ai_description = gemini_vision_api_compare(
                html=None,  # We're using just the screenshot for direct checks
                screenshot_path=screenshot_path,
                monitoring_type=website.monitoring_type,
                monitoring_keywords=website.monitoring_keywords,
                ai_focus_area=website.ai_focus_area
            )
            logger.debug(f"AI description generated: {ai_description[:100]}...")
            
            # Step 3: Determine if there's a change based on AI description
            change_detected = False
            if prev_check:
                # Check AI description for change indicators
                change_indicators = ["website changed", "change detected", "difference found", "new content"]
                if any(indicator in ai_description.lower() for indicator in change_indicators):
                    change_detected = True
                    logger.debug(f"Change detected for website {website_id} based on AI description.")
                else:
                    logger.debug(f"No change detected for website {website_id} based on AI description.")
            else:
                # First check, treat as a change to send initial notification
                change_detected = True
                logger.debug(f"First check for website {website_id}, treating as change detected.")
            
            # Get HTML for completeness (optional)
            html_path = f"data/html_{safe_filename(website.url)}_{now.strftime('%Y%m%d_%H%M%S')}.html"
            html = ""
            try:
                response = requests.get(website.url, timeout=30)
                html = response.text
                with open(html_path, 'w', encoding='utf-8') as f:
                    f.write(html)
            except Exception as e:
                html_path = None
                logger.warning(f"Failed to get HTML for website {website_id}: {e}")
            
            # --- Save Check History --- #
            check_history_entry = CheckHistory(
                website_id=website_id,
                checked_at=now,
                screenshot_path=screenshot_path_rel, # Relative path
                html_path=html_path, # Currently None
                ai_description=ai_description,
                change_detected=change_detected,
                error=error_message,
                response_time=None # Add if needed
            )
            db.session.add(check_history_entry)
            db.session.commit()  # Commit to get the ID
            logger.info(f"Check history saved for website {website_id}")

            # --- Handle Notifications/Summaries --- #
            if change_detected and user: # Only notify/summarize if change detected and user exists
                notification_payload = {
                    'website_url': website.url,
                    'website_id': website.id,
                    'user_id': user.user_id, # Store user_id
                    'ai_description': ai_description,
                    'screenshot_path': screenshot_path_rel, # Relative path
                    'timestamp': now.isoformat() # Use ISO format for timestamp
                }
                pref = user.notification_preference

                if pref in ['immediate', 'both']:
                    logger.info(f"Sending immediate notification for direct check of {website.url} for user {user.user_id}")
                    
                    # Basic notification content
                    subject = f"Change Detected (Manual Check): {website.url}"
                    
                    # Try to generate a better notification message using AI if available
                    default_notification_prompt = "You are an AI that summarizes the differences between two website screenshots/html based on user-specified criteria, your purpose is to send notification on the summary of what different. Write me output format to include bullet points with explanation. Summary what user want to compare. Skip what have been cover in the lastest notification, which include in the page. Be analytical and comprehensive."
                    notification_prompt = os.getenv('AI_NOTIFICATION_SYSTEM_PROMPT', default_notification_prompt)
                    
                    try:
                        # Check if we have a Gemini API key for AI notification enhancement
                        gemini_api_key = os.getenv('GEMINI_API_KEY')
                        
                        # Check if the AI description appears to be an error message
                        is_error_desc = "error" in ai_description.lower() or "failed" in ai_description.lower() or "exception" in ai_description.lower()
                        
                        if gemini_api_key and ai_description and not is_error_desc:
                            # Use Gemini API to generate notification
                            import google.generativeai as genai
                            
                            genai.configure(api_key=gemini_api_key)
                            
                            # Prepare the prompt for the AI
                            ai_prompt = f"{notification_prompt}\n\nWebsite: {website.url}\nTime: {now.strftime('%Y-%m-%d %H:%M:%S')}\nChange description: {ai_description}"
                            
                            # Generate the notification
                            model = genai.GenerativeModel('gemini-1.5-flash-latest')
                            response = model.generate_content(ai_prompt)
                            
                            if response and response.text:
                                # Use the AI-generated notification
                                if change_detected:
                                    body = f"Change detected on {website.url} at {now.strftime('%Y-%m-%d %H:%M:%S')}:\n\n{response.text}"
                                else:
                                    body = f"Website check completed for {website.url} at {now.strftime('%Y-%m-%d %H:%M:%S')}:\n\nNo changes detected. {response.text}"
                                app.logger.info("Generated enhanced AI notification message")
                            else:
                                # Fallback to basic notification
                                if change_detected:
                                    body = f"Change detected on {website.url} at {now.strftime('%Y-%m-%d %H:%M:%S')}:\n\n{ai_description}"
                                else:
                                    body = f"Website check completed for {website.url} at {now.strftime('%Y-%m-%d %H:%M:%S')}:\n\nNo changes detected. Status: {website.status}"
                                app.logger.warning("AI notification generation returned empty result, using basic message")
                        else:
                            # Use the basic notification if no API key or error in AI description
                            if change_detected:
                                body = f"Change detected on {website.url} at {now.strftime('%Y-%m-%d %H:%M:%S')}:\n\n{ai_description}"
                            else:
                                body = f"Website check completed for {website.url} at {now.strftime('%Y-%m-%d %H:%M:%S')}:\n\nNo changes detected. Status: {website.status}"
                    except Exception as e:
                        # Fallback to basic notification on any error
                        if change_detected:
                            body = f"Change detected on {website.url} at {now.strftime('%Y-%m-%d %H:%M:%S')}:\n\n{ai_description}"
                        else:
                            body = f"Website check completed for {website.url} at {now.strftime('%Y-%m-%d %H:%M:%S')}:\n\nNo changes detected. Status: {website.status}"
                        app.logger.error(f"Error generating AI notification: {e}, using basic message")
                    
                    # Store notification in database
                    try:
                        from app import Notification
                        notification = Notification(
                            user_id=user.user_id,
                            website_id=website.id,
                            check_history_id=check_history_entry.id,
                            notification_type='immediate',
                            content=body,
                            screenshot_path=screenshot_path_rel,
                            sent=True  # Mark as sent since we're sending it immediately
                        )
                        db.session.add(notification)
                        db.session.commit()
                        logger.info(f"Stored immediate notification in database for user {user.user_id}, website {website.id}")
                    except Exception as e:
                        logger.error(f"Failed to store notification in database: {e}")
                        # Continue with sending even if storage fails
                    
                    # Trigger immediate notifications
                    send_email_notification(user, subject, body, screenshot_path_rel)
                    send_telegram_notification(user.user_id, body)
                    send_teams_notification(user.user_id, body)

                if pref in ['summary', 'both']:
                    try:
                        # Store the notification in the database for summary purposes
                        from app import Notification
                        notification = Notification(
                            user_id=user.user_id,
                            website_id=website.id,
                            check_history_id=check_history_entry.id,
                            notification_type='immediate',  # It's still an immediate notification, just for summary use
                            content=ai_description,  # Store the original AI description for summary use
                            screenshot_path=screenshot_path_rel,
                            sent=False,  # Not sent directly, will be included in summary
                            included_in_summary=False  # Not yet included in any summary
                        )
                        db.session.add(notification)
                        db.session.commit()
                        
                        # Add notification ID to the payload
                        notification_payload['notification_id'] = notification.id
                        
                        # Use the helper function to add to the queue
                        add_to_summary_queue(user.user_id, notification_payload)
                    except Exception as e:
                        logger.error(f"Failed to queue change summary for user {user.user_id}: {e}")

            # --- Update Website Status --- #
            if error_message:
                if "CAPTCHA detected" in error_message:
                    website.status = 'captcha'
                else:
                    website.status = 'error'
                website.error_message = error_message[:512] # Truncate if needed
            else:
                website.status = 'change' if change_detected else 'no-change'
                website.error_message = None
            website.last_checked = now
            db.session.commit()
            
            # Always assume success if we get here
            success = True
            return True, "Check completed successfully", screenshot_path_rel, ai_description
            
    except Exception as e:
        # Catch-all for app_context errors
        error_message = f"Error in direct check (app context): {str(e)}"
        logger.error(f"App context exception during direct check: {e}", exc_info=True)
        return False, error_message, screenshot_path, ai_description


# --- Screenshot Logic (if needed) ---
# The get_screenshot_playwright function is imported from browser_agent.screenshot
# No need to redefine it here unless there's a specific task-related reason.

# Add any other background job functions here
