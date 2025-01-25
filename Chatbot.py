from flask import Flask, request, jsonify, Response
import requests
from dotenv import load_dotenv
from flask_cors import CORS
from datetime import datetime, timedelta
from openai import OpenAI 

# Load environment variables
load_dotenv()

client = OpenAI(
    api_key="sk-802fe5996aa441199db50ff2c951a261",
    base_url="https://api.deepseek.com"
)

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

# Allow specific origins (replace with your frontend URL)
CORS(
    app,
    resources={
        r"/chat": {"origins": "http://localhost:5173"},
        r"/history/*": {"origins": "*"}
    },
    supports_credentials=True
)

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

@app.route('/chat', methods=['POST'])
def chat():
    data = request.json
    user_query = data.get('query')
    section = data.get('section', 'main')
    chat_id = data.get('chat_id')
    messages = data.get('messages', [])

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

    # Add system message based on section
    system_messages = {
        'main': "You are a helpful legal assistant",
        'for_against': "You are a legal analyst specializing in balanced arguments",
        'bare_acts': "You are a legal expert explaining legal acts"
    }
    
    messages_with_system = [{"role": "system", "content": system_messages[section]}] + messages

    def generate():
        try:
            stream = client.chat.completions.create(
                model="deepseek-chat",
                messages=messages_with_system,
                stream=True,
                max_tokens=2048,
                temperature=0.7
            )
            for chunk in stream:
                content = chunk.choices[0].delta.content or ""
                if content:
                    yield f"data: {json.dumps({'content': content})}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            print(f"Error: {e}")
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return Response(generate(), mimetype='text/event-stream')

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

@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "http://localhost:5173"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type,Authorization"
    response.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
    return response

@app.route('/chat', methods=['OPTIONS'])
def handle_options():
    return Response(status=200)

@app.route("/")
def home():
    return "Hello, this is the chatbot!"

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
