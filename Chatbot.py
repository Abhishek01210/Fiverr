from flask import Flask, request, jsonify, Response
import requests
from dotenv import load_dotenv
from flask_cors import CORS
from datetime import datetime, timedelta
import json

# Load environment variables
load_dotenv()

DEEPSEEK_API_KEY = "sk-802fe5996aa441199db50ff2c951a261"
DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"

# Separate storage for query history and chat titles for each section
query_history = {
    'main': [],
    'for_against': [],
    'bare_acts': []
}

chat_titles = {
    'main': {},
    'for_against': {},
    'bare_acts': {}
}

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"})

def generate_chat_title(queries):
    try:
        prompt = f"Create a short, descriptive title (max 5 words) for a chat session based on these queries:\n1. {queries[0]}\n2. {queries[1]}"
        
        payload = {
            "messages": [
                {"role": "system", "content": "You are a helpful assistant that creates concise chat titles."},
                {"role": "user", "content": prompt}
            ],
            "model": "deepseek-chat",
            "max_tokens": 20,
            "temperature": 0.7,
            "stream": False
        }
        
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'Authorization': f'Bearer {DEEPSEEK_API_KEY}'
        }
        
        response = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload)
        response_data = response.json()
        return response_data['choices'][0]['message']['content'].strip()
    except Exception as e:
        print(f"Error generating title: {e}")
        return "New Chat"

def get_chat_id():
    return datetime.now().strftime("%Y%m%d%H%M%S")

def stream_deepseek_response(user_query, section):
    system_messages = {
        'main': "You are a helpful legal assistant, providing clear and accurate information about legal matters.",
        'for_against': "You are a legal analyst specializing in presenting balanced arguments for and against legal positions.",
        'bare_acts': "You are a legal expert focusing on explaining sections of legal acts and statutes in simple terms."
    }
    
    payload = {
        "messages": [
            {"role": "system", "content": system_messages[section]},
            {"role": "user", "content": user_query}
        ],
        "model": "deepseek-chat",
        "max_tokens": 2048,
        "temperature": 0.7,
        "stream": True
    }
    
    headers = {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'Authorization': f'Bearer {DEEPSEEK_API_KEY}'
    }
    
    response = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload, stream=True)
    
    if response.status_code != 200:
        raise Exception("Failed to get response from DeepSeek API")
        
    for line in response.iter_lines():
        if line:
            line = line.decode('utf-8')
            if line.startswith('data: '):
                try:
                    data = json.loads(line[6:])  # Skip 'data: ' prefix
                    if data['choices'][0]['finish_reason'] is not None:
                        continue
                    content = data['choices'][0]['delta'].get('content', '')
                    if content:
                        yield content
                except json.JSONDecodeError:
                    continue

@app.route('/chat', methods=['POST'])
def chat():
    data = request.json
    user_query = data.get('query')
    section = data.get('section', 'main')
    chat_id = data.get('chat_id')
    
    if not user_query:
        return jsonify({'error': 'No query provided'}), 400

    # Create new chat entry if needed
    if not chat_id:
        chat_id = get_chat_id()
        chat_titles[section][chat_id] = {
            'queries': [],
            'title': None,
            'timestamp': datetime.now().isoformat()
        }

    # Store query
    chat_titles[section][chat_id]['queries'].append(user_query)
    
    # Generate title after second query
    if len(chat_titles[section][chat_id]['queries']) == 2:
        title = generate_chat_title(chat_titles[section][chat_id]['queries'])
        chat_titles[section][chat_id]['title'] = title

    try:
        def generate():
            full_response = ""
            for content in stream_deepseek_response(user_query, section):
                full_response += content
                yield f"data: {json.dumps({'content': content})}\n\n"
            
            # Store in history after complete response
            query_history[section].append({
                'chat_id': chat_id,
                'query': user_query,
                'response': full_response,
                'timestamp': datetime.now().isoformat()
            })
            
            # Send the chat_id in the final message
            yield f"data: {json.dumps({'chat_id': chat_id})}\n\n"

        return Response(generate(), mimetype='text/event-stream')

    except Exception as e:
        print(f"Error: {e}")
        return jsonify({'error': 'Unable to process the request'}), 500

@app.route('/history/<section>', methods=['GET'])
def get_history(section):
    if section not in query_history:
        return jsonify([])

    # Group chats by date
    now = datetime.now()
    today = now.date()
    yesterday = today - timedelta(days=1)
    seven_days_ago = today - timedelta(days=7)
    thirty_days_ago = today - timedelta(days=30)

    grouped_history = {
        'today': [],
        'yesterday': [],
        'seven_days': [],
        'thirty_days': []
    }

    # Group chats by their first message
    chat_groups = {}
    for entry in query_history[section]:
        chat_id = entry['chat_id']
        if chat_id not in chat_groups:
            chat_groups[chat_id] = {
                'title': chat_titles[section][chat_id]['title'] or "New Chat",
                'timestamp': datetime.fromisoformat(entry['timestamp']),
                'messages': []
            }
        chat_groups[chat_id]['messages'].append(entry)

    # Sort chats into time periods
    for chat_id, chat in chat_groups.items():
        chat_date = chat['timestamp'].date()
        if chat_date == today:
            grouped_history['today'].append(chat)
        elif chat_date == yesterday:
            grouped_history['yesterday'].append(chat)
        elif chat_date > seven_days_ago:
            grouped_history['seven_days'].append(chat)
        elif chat_date > thirty_days_ago:
            grouped_history['thirty_days'].append(chat)

    return jsonify(grouped_history)

@app.route('/history/<section>/clear', methods=['POST'])
def clear_history(section):
    if section in query_history:
        query_history[section].clear()
        chat_titles[section].clear()
        return jsonify({'message': f'History cleared for {section}'}), 200
    return jsonify({'error': 'Invalid section'}), 400

@app.route("/")
def home():
    return "Hello, this is the chatbot!"

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
