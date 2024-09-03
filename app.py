from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from flask_socketio import SocketIO, emit, join_room, leave_room
import json
import os
from datetime import datetime
import sqlite3

app = Flask(__name__)
app.secret_key = 'votre_clé_secrète'
socketio = SocketIO(app)

USERS_FILE = 'users.json'
ANSWERS_FILE = 'answers.json'
FRIENDS_FILE = 'friends.json'
FRIEND_REQUESTS_FILE = 'friend_requests.json'

def load_json(file_path):
    if os.path.exists(file_path):
        with open(file_path, 'r') as f:
            return json.load(f)
    return {}

def save_json(file_path, data):
    with open(file_path, 'w') as f:
        json.dump(data, f)

def create_messages_table():
    conn = sqlite3.connect('messages.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS messages
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  room TEXT,
                  username TEXT,
                  message TEXT,
                  timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
    conn.commit()
    conn.close()

create_messages_table()

def calculate_similarity_percentage(user1_answers, user2_answers):
    common_questions = set(user1_answers.keys()) & set(user2_answers.keys())
    if not common_questions:
        return 0
    matching_answers = sum(user1_answers[q] == user2_answers[q] for q in common_questions)
    return (matching_answers / len(common_questions)) * 100

def find_similar_users(username, answers):
    user_answers = answers.get(username, {})
    similar_users = []
    
    for other_user, other_answers in answers.items():
        if other_user != username:
            similarity = calculate_similarity_percentage(user_answers, other_answers)
            if similarity >= 50:
                similar_users.append((other_user, similarity))
    
    return sorted(similar_users, key=lambda x: x[1], reverse=True)

@app.route('/')
def home():
    if 'username' in session:
        return redirect(url_for('main'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        users = load_json(USERS_FILE)
        if username in users and users[username] == password:
            session['username'] = username
            return redirect(url_for('main'))
        return "Identifiants incorrects"
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        users = load_json(USERS_FILE)
        if username not in users:
            users[username] = password
            save_json(USERS_FILE, users)
            return redirect(url_for('login'))
        return "Nom d'utilisateur déjà pris"
    return render_template('register.html')

@app.route('/main')
def main():
    if 'username' not in session:
        return redirect(url_for('login'))
    return render_template('index.html')

@app.route('/save_answer', methods=['POST'])
def save_answer():
    if 'username' not in session:
        return jsonify({"error": "Non connecté"}), 401
    
    data = request.json
    username = session['username']
    answers = load_json(ANSWERS_FILE)
    
    if username not in answers:
        answers[username] = {}
    
    answers[username][data['question']] = data['answer']
    save_json(ANSWERS_FILE, answers)
    
    print(f"Réponse sauvegardée pour {username}: {data['question']} = {data['answer']}")
    
    return jsonify({"success": True})

@app.route('/profile')
def profile():
    if 'username' not in session:
        return redirect(url_for('login'))
    
    username = session['username']
    answers = load_json(ANSWERS_FILE)
    user_answers = answers.get(username, {})
    
    similar_users = find_similar_users(username, answers)
    
    friend_requests = load_json(FRIEND_REQUESTS_FILE).get(username, [])
    friends = load_json(FRIENDS_FILE).get(username, [])
    
    return render_template('profile.html', answers=user_answers, similar_users=similar_users, friend_requests=friend_requests, friends=friends)

@app.route('/update_answers', methods=['POST'])
def update_answers():
    if 'username' not in session:
        return redirect(url_for('login'))
    
    username = session['username']
    new_answers = request.form.to_dict()
    answers = load_json(ANSWERS_FILE)
    
    if username in answers:
        answers[username].update(new_answers)
        save_json(ANSWERS_FILE, answers)
    
    return redirect(url_for('profile'))

@app.route('/logout', methods=['POST'])
def logout():
    session.pop('username', None)
    return redirect(url_for('login'))

@app.route('/send_friend_request/<username>')
def send_friend_request(username):
    if 'username' not in session:
        return redirect(url_for('login'))
    
    sender = session['username']
    requests = load_json(FRIEND_REQUESTS_FILE)
    
    if username not in requests:
        requests[username] = []
    
    if sender not in requests[username]:
        requests[username].append(sender)
        save_json(FRIEND_REQUESTS_FILE, requests)
    
    return redirect(url_for('profile'))

@app.route('/accept_friend_request/<username>')
def accept_friend_request(username):
    if 'username' not in session:
        return redirect(url_for('login'))
    
    current_user = session['username']
    requests = load_json(FRIEND_REQUESTS_FILE)
    friends = load_json(FRIENDS_FILE)
    
    if current_user in requests and username in requests[current_user]:
        requests[current_user].remove(username)
        
        if current_user not in friends:
            friends[current_user] = []
        if username not in friends:
            friends[username] = []
        
        if username not in friends[current_user]:
            friends[current_user].append(username)
        if current_user not in friends[username]:
            friends[username].append(current_user)
        
        save_json(FRIEND_REQUESTS_FILE, requests)
        save_json(FRIENDS_FILE, friends)
    
    return redirect(url_for('profile'))

@app.route('/chat/<username>')
def chat(username):
    if 'username' not in session:
        return redirect(url_for('login'))
    
    current_user = session['username']
    friends = load_json(FRIENDS_FILE)
    
    if current_user in friends and username in friends[current_user]:
        return render_template('chat.html', friend=username)
    
    return redirect(url_for('profile'))

@app.route('/chat')
def chat_list():
    if 'username' not in session:
        return redirect(url_for('login'))
    
    username = session['username']
    friends = load_json(FRIENDS_FILE).get(username, [])
    return render_template('chat_list.html', friends=friends)

@app.route('/get_messages/<room>')
def get_messages(room):
    conn = sqlite3.connect('messages.db')
    c = conn.cursor()
    c.execute("SELECT username, message, timestamp FROM messages WHERE room = ? ORDER BY timestamp", (room,))
    messages = [{'username': m[0], 'msg': m[1], 'time': m[2]} for m in c.fetchall()]
    conn.close()
    return jsonify(messages)

@socketio.on('join')
def on_join(data):
    username = data['username']
    room = data['room']
    join_room(room)
    emit('status', {'msg': f'{username} has entered the room.'}, room=room)

@socketio.on('leave')
def on_leave(data):
    username = data['username']
    room = data['room']
    leave_room(room)
    emit('status', {'msg': f'{username} has left the room.'}, room=room)

@socketio.on('message')
def handle_message(data):
    room = data['room']
    username = data['username']
    msg = data['msg']
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    conn = sqlite3.connect('messages.db')
    c = conn.cursor()
    c.execute("INSERT INTO messages (room, username, message, timestamp) VALUES (?, ?, ?, ?)",
              (room, username, msg, timestamp))
    conn.commit()
    conn.close()
    
    emit('message', {'username': username, 'msg': msg, 'time': timestamp}, room=room)

if __name__ == '__main__':
    socketio.run(app, debug=True)