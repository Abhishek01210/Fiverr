from flask import Flask, request, jsonify
import requests
from dotenv import load_dotenv
from flask_cors import CORS
from ragflow_sdk import RAGFlow
from datetime import datetime, timedelta
from openai import OpenAI

# Load environment variables
load_dotenv()

RAGFLOW_API_URL = "https://ragflow-ogno0-u30628.vm.elestio.app"
RAGFLOW_API_KEY = "ragflow-Q1NmJhMTcyZDViNTExZWY5ZTY3MDI0Mm"
DEEPSEEK_API_KEY = "sk-802fe5996aa441199db50ff2c951a261"

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

# Initialize DeepSeek client
deepseek_client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com/v1")

# Initialize RAGFlow objects for each section
rag_object = RAGFlow(api_key=RAGFLOW_API_KEY, base_url=RAGFLOW_API_URL)
chat_assistants = {
    'main': rag_object.list_chats(name="Main Chat")[0],
    'for_against': rag_object.list_chats(name="For/Against")[0],
    'bare_acts': rag_object.list_chats(name="Bare Acts")[0]
}

# Store sessions for each section
global_sessions = {
    'main': None,
    'for_against': None,
    'bare_acts': None
}

def get_or_create_session(section):
    global global_sessions
    if global_sessions[section] is None:
        global_sessions[section] = chat_assistants[section].create_session()
    return global_sessions[section]

def generate_chat_title(queries):
    try:
        prompt = f"Create a short, descriptive title (max 5 words) for a chat session based on these queries:\n1. {queries[0]}\n2. {queries[1]}"
        response = deepseek_client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": "You are a helpful assistant that creates concise chat titles."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=20,
            temperature=0.7
        )
        return response.choices[0].message.content.strip()
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
        session = get_or_create_session(section)
        cont = ""
        response_content = ""
        for ans in session.ask(user_query, stream=True):
            response_content += ans.content[len(cont):]
            cont = ans.content

        # Store in history
        query_history[section].append({
            'chat_id': chat_id,
            'query': user_query,
            'response': response_content,
            'timestamp': datetime.now().isoformat()
        })

        return jsonify({
            'answer': response_content,
            'chat_id': chat_id
        })

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
    global global_sessions
    if section in query_history:
        query_history[section].clear()
        chat_titles[section].clear()
        global_sessions[section] = None
        return jsonify({'message': f'History cleared for {section}'}), 200
    return jsonify({'error': 'Invalid section'}), 400

@app.route("/")
def home():
    return "Hello, this is the chatbot!"

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
