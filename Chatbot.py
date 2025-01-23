import os
from flask import Flask, request, jsonify, Response
from flask_cors import CORS
from dotenv import load_dotenv
import requests
import json
from datetime import datetime, timedelta

# Load environment variables
load_dotenv()

# DeepSeek configuration
DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")  # Store in .env file

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
CORS(app, resources={r"/*": {"origins": "*"}})

def generate_chat_title(queries):
    try:
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {DEEPSEEK_API_KEY}'
        }
        payload = {
            "messages": [
                {"role": "system", "content": "You are a helpful assistant that creates concise chat titles."},
                {"role": "user", "content": f"Create a short, descriptive title (max 5 words) for a chat session based on these queries:\n1. {queries[0]}\n2. {queries[1]}"}
            ],
            "model": "deepseek-chat",
            "max_tokens": 20,
            "temperature": 0.7
        }
        
        response = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload)
        return response.json()['choices'][0]['message']['content'].strip()
    except Exception as e:
        print(f"Error generating title: {e}")
        return "New Chat"

def get_chat_id():
    return datetime.now().strftime("%Y%m%d%H%M%S")

def stream_deepseek_response(user_query, section):
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {DEEPSEEK_API_KEY}',
        'Accept': 'application/json'
    }
    
    system_prompt = {
        'main': "You are a helpful AI assistant ready to answer various questions.",
        'for_against': "You are an AI assistant specialized in providing balanced perspectives on legal and policy issues.",
        'bare_acts': "You are an AI assistant expert in explaining legal sections and acts in detail."
    }

    payload = {
        "messages": [
            {"role": "system", "content": system_prompt.get(section, system_prompt['main'])},
            {"role": "user", "content": user_query}
        ],
        "model": "deepseek-chat",
        "stream": True,
        "max_tokens": 2048,
        "temperature": 0.7
    }

    try:
        response = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload, stream=True)
        return response
    except Exception as e:
        print(f"Error streaming response: {e}")
        return None

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

    def generate():
        full_response = ""
        stream_response = stream_deepseek_response(user_query, section)
        
        if not stream_response:
            yield json.dumps({"error": "Failed to connect to DeepSeek"})
            return

        for chunk in stream_response.iter_lines():
            if chunk:
                try:
                    chunk_str = chunk.decode('utf-8')
                    if chunk_str.startswith('data: '):
                        json_chunk = json.loads(chunk_str[6:])
                        if 'choices' in json_chunk and json_chunk['choices']:
                            delta = json_chunk['choices'][0].get('delta', {})
                            content = delta.get('content', '')
                            if content:
                                full_response += content
                                yield json.dumps({"content": content})
                except Exception as e:
                    print(f"Chunk parsing error: {e}")

        # Store complete response in history
        query_history[section].append({
            'chat_id': chat_id,
            'query': user_query,
            'response': full_response,
            'timestamp': datetime.now().isoformat()
        })

        # Final message with chat_id
        yield json.dumps({"chat_id": chat_id, "end": True})

    return Response(generate(), content_type='text/event-stream')

@app.route('/api/history/<section>', methods=['GET'])
def get_history(section):
    if section not in query_history:
        return jsonify([])

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

@app.route('/api/history/<section>/clear', methods=['POST'])
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
