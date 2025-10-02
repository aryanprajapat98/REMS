import os
import sqlite3
import secrets
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
import base64

template_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'templates')
app = Flask(__name__, template_folder=template_dir, static_folder='static')
app.secret_key = secrets.token_hex(16)

def get_db_connection():
    conn = sqlite3.connect('properties.db')
    conn.row_factory = sqlite3.Row
    return conn

@app.context_processor
def inject_unread_count():
    unread_count = 0
    if 'user_id' in session:
        db = get_db_connection()
        user_id = session['user_id']
        unread = db.execute('''
            SELECT COUNT(*) as count FROM chats
            WHERE receiver_id = ?
        ''', (user_id,)).fetchone()
        unread_count = unread['count'] if unread else 0
        db.close()
    return dict(unread_count=unread_count)

def init_db():
    with app.app_context():
        db = get_db_connection()
        with open('database.sql', 'r') as f:
            db.executescript(f.read())
        db.commit()

# Commented out to prevent reinitialization error
# init_db()

@app.route('/')
def index():
    db = get_db_connection()
    # Check if contact_number column exists in users table
    user_columns = db.execute("PRAGMA table_info(users)").fetchall()
    column_names = [col['name'] for col in user_columns]
    if 'contact_number' in column_names:
        properties = db.execute('SELECT p.*, u.contact_number FROM properties p LEFT JOIN users u ON p.user_id = u.id WHERE p.approved = 1').fetchall()
    else:
        properties = db.execute('SELECT * FROM properties WHERE approved = 1').fetchall()
    db.close()
    return render_template('index.html', properties=properties)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        db = get_db_connection()
        user = db.execute('SELECT * FROM users WHERE email = ?', (email,)).fetchone()
        db.close()
        if user and check_password_hash(user['password'], password):
            session['user_id'] = user['id']
            session['role'] = user['role']
            if user['role'] == 'admin':
                return redirect(url_for('admin'))
            else:
                return redirect(url_for('index'))
        else:
            flash('Invalid credentials')
    return render_template('login.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        password = generate_password_hash(request.form['password'])
        role = request.form['role']
        contact_number = request.form.get('contact_number', '')
        db = get_db_connection()
        try:
            db.execute('INSERT INTO users (name, email, password, role, contact_number) VALUES (?, ?, ?, ?, ?)', (name, email, password, role, contact_number))
            db.commit()
            flash('Account created successfully')
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            flash('Email already exists')
        db.close()
    return render_template('signup.html')

@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form['email']
        db = get_db_connection()
        user = db.execute('SELECT * FROM users WHERE email = ?', (email,)).fetchone()
        if user:
            token = secrets.token_urlsafe(32)
            db.execute('INSERT INTO password_resets (email, token) VALUES (?, ?)', (email, token))
            db.commit()
            flash(f'Reset link: /reset_password/{token}')
        db.close()
    return render_template('forgot_password.html')

@app.route('/reset_password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    db = get_db_connection()
    reset = db.execute('SELECT * FROM password_resets WHERE token = ?', (token,)).fetchone()
    if not reset:
        flash('Invalid token')
        return redirect(url_for('login'))
    if request.method == 'POST':
        password = generate_password_hash(request.form['password'])
        db.execute('UPDATE users SET password = ? WHERE email = ?', (password, reset['email']))
        db.execute('DELETE FROM password_resets WHERE token = ?', (token,))
        db.commit()
        flash('Password reset successfully')
        return redirect(url_for('login'))
    db.close()
    return render_template('reset_password.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

@app.route('/add_property', methods=['GET', 'POST'])
def add_property():
    if 'user_id' not in session or session['role'] != 'admin':
        return redirect(url_for('login'))
    if request.method == 'POST':
        title = request.form['title']
        price = request.form['price']
        location = request.form['location']
        description = request.form['description']
        image = request.form.get('image')
        bedrooms = request.form.get('bedrooms')
        bathrooms = request.form.get('bathrooms')
        area = request.form.get('area')
        amenities = request.form.get('amenities')
        contact_number = request.form.get('contact_number')
        if image:
            image = base64.b64encode(image.encode()).decode()
        db = get_db_connection()
        db.execute('INSERT INTO properties (title, price, location, description, image, user_id, approved, bedrooms, bathrooms, area, amenities) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                   (title, price, location, description, image, session['user_id'], 1, bedrooms, bathrooms, area, amenities))
        # Update user's contact number if provided
        if contact_number:
            db.execute('UPDATE users SET contact_number = ? WHERE id = ?', (contact_number, session['user_id']))
        db.commit()
        db.close()
        return redirect(url_for('index'))
    return render_template('add_property.html')

@app.route('/search', methods=['GET', 'POST'])
def search():
    query = request.args.get('q', '')
    location = request.args.get('location', '')
    min_price = request.args.get('min_price', 0)
    max_price = request.args.get('max_price', 999999999)
    db = get_db_connection()
    properties = db.execute('SELECT p.*, u.contact_number FROM properties p LEFT JOIN users u ON p.user_id = u.id WHERE p.approved = 1 AND p.title LIKE ? AND p.location LIKE ? AND p.price BETWEEN ? AND ?',
                            ('%' + query + '%', '%' + location + '%', min_price, max_price)).fetchall()
    db.close()
    return render_template('search.html', properties=properties)

@app.route('/leads')
def leads():
    if 'user_id' not in session or session['role'] != 'admin':
        return redirect(url_for('login'))
    db = get_db_connection()
    leads = db.execute('SELECT * FROM leads').fetchall()
    db.close()
    return render_template('leads.html', leads=leads)

@app.route('/submit_lead', methods=['POST'])
def submit_lead():
    name = request.form['name']
    email = request.form['email']
    message = request.form['message']
    property_id = request.form['property_id']
    db = get_db_connection()
    db.execute('INSERT INTO leads (name, email, message, property_id) VALUES (?, ?, ?, ?)', (name, email, message, property_id))
    db.commit()
    db.close()
    return jsonify({'status': 'success'})

@app.route('/admin')
def admin():
    if 'user_id' not in session or session['role'] != 'admin':
        return redirect(url_for('login'))
    db = get_db_connection()
    users = db.execute('SELECT * FROM users').fetchall()
    properties = db.execute('SELECT * FROM properties').fetchall()
    leads_count = db.execute('SELECT COUNT(*) as count FROM leads').fetchone()['count']
    properties_count = db.execute('SELECT COUNT(*) as count FROM properties').fetchone()['count']
    users_count = db.execute('SELECT COUNT(*) as count FROM users').fetchone()['count']
    db.close()
    return render_template('admin.html', users=users, properties=properties, leads_count=leads_count, properties_count=properties_count, users_count=users_count)

@app.route('/approve_property/<int:id>')
def approve_property(id):
    if 'user_id' not in session or session['role'] != 'admin':
        return redirect(url_for('login'))
    db = get_db_connection()
    db.execute('UPDATE properties SET approved = 1 WHERE id = ?', (id,))
    db.commit()
    db.close()
    return redirect(url_for('admin'))

@app.route('/delete_property/<int:id>')
def delete_property(id):
    if 'user_id' not in session or session['role'] not in ['agent', 'admin']:
        return redirect(url_for('login'))
    db = get_db_connection()
    db.execute('DELETE FROM properties WHERE id = ? AND (user_id = ? OR ? = "admin")', (id, session['user_id'], session['role']))
    db.commit()
    db.close()
    return redirect(url_for('index'))

@app.route('/chat/<int:property_id>')
def chat(property_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    db = get_db_connection()
    property = db.execute('SELECT * FROM properties WHERE id = ?', (property_id,)).fetchone()
    receiver_id = property['user_id'] if property else None
    db.close()
    return render_template('chat.html', property=property, receiver_id=receiver_id)

@app.route('/send_message', methods=['POST'])
def send_message():
    if 'user_id' not in session:
        return jsonify({'status': 'error'})
    sender_id = session['user_id']
    receiver_id = request.form['receiver_id']
    property_id = request.form['property_id']
    message = request.form['message']
    db = get_db_connection()
    db.execute('INSERT INTO chats (sender_id, receiver_id, property_id, message) VALUES (?, ?, ?, ?)', (sender_id, receiver_id, property_id, message))
    db.commit()
    db.close()
    return jsonify({'status': 'success'})

@app.route('/get_messages/<int:property_id>')
def get_messages(property_id):
    if 'user_id' not in session:
        return jsonify([])
    user_id = session['user_id']
    db = get_db_connection()
    messages = db.execute('SELECT c.*, u.name as sender_name, u.contact_number as sender_contact FROM chats c JOIN users u ON c.sender_id = u.id WHERE c.property_id = ? AND (c.sender_id = ? OR c.receiver_id = ?)', (property_id, user_id, user_id)).fetchall()
    db.close()
    return jsonify([dict(msg) for msg in messages])

if __name__ == '__main__':
    app.run(debug=True)
