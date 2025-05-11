from flask import Flask, render_template, jsonify, request, session
from flask_cors import CORS
import sqlite3
from datetime import datetime, timedelta
from collections import Counter
import google.generativeai as genai
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os
from dotenv import load_dotenv
from flask import send_from_directory

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)
app.secret_key = 'your_secret_key_here'  # 🔐 Needed for session support
CORS(app)

# Gemini API Setup
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
gemini_model = genai.GenerativeModel('gemini-flash')

# Email Config
SENDER_EMAIL = os.getenv("EMAIL_USER")
SENDER_PASSWORD = os.getenv("EMAIL_PASS")

DATABASE = 'mood_tracker.db'

def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        conn.execute('''
        CREATE TABLE IF NOT EXISTS moods (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mood TEXT NOT NULL,
            rating INTEGER NOT NULL,
            note TEXT,
            tags TEXT,
            date TEXT NOT NULL
        )
        ''')
        conn.commit()

init_db()

@app.route('/')
def index():
    return render_template('moodTracker.html')


@app.route('/api/mood', methods=['POST'])
def submit_mood():
    mood_data = request.get_json()
    
    if not mood_data or 'mood' not in mood_data or 'rating' not in mood_data:
        return jsonify({"error": "Missing required fields"}), 400
    
    with get_db() as conn:
        conn.execute('''
            INSERT INTO moods (mood, rating, note, tags, date)
            VALUES (?, ?, ?, ?, ?)
        ''', (
            mood_data.get('mood'),
            int(mood_data.get('rating')),
            mood_data.get('moodNote', ''),
            mood_data.get('tags', ''),
            datetime.now().strftime('%Y-%m-%d')
        ))
        conn.commit()
    
    # Generate encouraging message if needed
    mood_is_urgent = mood_data['mood'] in ['sad', 'angry']
    encouragement = generate_support_message(mood_data['mood']) if mood_is_urgent else ""

    # Get support email from session or use default
    recipient_email = session.get('support_email', 'akitoayemi47@gmail.com')

    # Send email alert if needed
    if mood_is_urgent:
        send_email_alert(
            email_to=recipient_email,
            subject=f"Urgent: {mood_data['mood'].capitalize()} Mood Logged Today",
            body=f"""
            Hello,

            The user logged a "{mood_data['mood']}" mood today. They may need emotional support.

            Best regards,
            Serenity App
            """
        )

    return jsonify({
        "message": "Mood submitted successfully!",
        "suggest_popup": mood_is_urgent,
        "encouragement": encouragement
    }), 200


def generate_support_message(mood):
    prompt = f"The user is feeling {mood}. Write a short, supportive message that helps them feel better."
    try:
        response = gemini_model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        return "We're here for you. Take a deep breath and remember things will get better."


def send_email_alert(email_to, subject, body):
    msg = MIMEMultipart()
    msg['From'] = SENDER_EMAIL
    msg['To'] = email_to
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'plain'))

    try:
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        server.sendmail(SENDER_EMAIL, email_to, msg.as_string())
        server.quit()
        print("✅ Email sent!")
    except Exception as e:
        print("❌ Failed to send email:", str(e))


@app.route('/api/save-support-email', methods=['POST'])
def save_support_email():
    data = request.get_json()
    email = data.get('email', '').strip()

    if email and '@' in email:
        session['support_email'] = email
        print(f"✅ Support email set to: {email}")
        return jsonify({"message": "Email saved"}), 200
    else:
        session.pop('support_email', None)
        print("✅ Support email cleared")
        return jsonify({"message": "Invalid email format"}), 400


@app.route('/get-mood-data', methods=['GET'])
def get_mood_data():
    thirty_days_ago = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
    
    with get_db() as conn:
        moods = conn.execute('''
            SELECT mood, rating, note, tags, date 
            FROM moods 
            WHERE date >= ?
            ORDER BY date
        ''', (thirty_days_ago,)).fetchall()
        mood_list = [dict(mood) for mood in moods]
    
    mood_colors = {
        'happy': '#4CAF50',
        'calm': '#FFEB3B',
        'neutral': '#FF9800',
        'sad': '#F44336',
        'angry': '#9C27B0'
    }

    calendar_data = []
    chart_data = []

    for i in range(30):
        date = (datetime.now() - timedelta(days=29-i)).strftime('%Y-%m-%d')
        entries = [m for m in mood_list if m['date'] == date]

        if entries:
            entry = entries[-1]
            chart_data.append({'date': date, 'rating': entry['rating'], 'mood': entry['mood']})
            calendar_data.append({
                'date': date,
                'color': mood_colors.get(entry['mood'], '#9E9E9E'),
                'intensity': min(0.3 + (entry['rating'] / 20), 0.9),
                'mood': entry['mood']
            })
        else:
            chart_data.append({'date': date, 'rating': 5, 'mood': 'neutral'})
            calendar_data.append({
                'date': date,
                'color': '#9E9E9E',
                'intensity': 0.3,
                'mood': 'none'
            })

    stats = calculate_mood_stats(mood_list)

    return jsonify({
        'chartData': chart_data,
        'calendarData': calendar_data,
        'moodStats': stats
    })

def calculate_mood_stats(mood_list):
    if not mood_list:
        return {}

    avg_rating = sum(m['rating'] for m in mood_list) / len(mood_list)
    mood_counts = {}
    for mood in ['happy', 'calm', 'neutral', 'sad', 'angry']:
        mood_counts[mood] = sum(1 for m in mood_list if m['mood'] == mood)

    all_tags = []
    for m in mood_list:
        if m.get('tags'):
            all_tags.extend(tag.strip() for tag in m['tags'].split(',') if tag.strip())

    common_tags = dict(Counter(all_tags).most_common(3)) if all_tags else {}

    return {
        'avgRating': round(avg_rating, 1),
        'moodCounts': mood_counts,
        'commonTags': common_tags
    }
    


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5002)