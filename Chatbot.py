from flask import Flask, request, jsonify
import requests
from dotenv import load_dotenv
from flask_cors import CORS
from ragflow_sdk import RAGFlow
from datetime import datetime

# Load environment variables
load_dotenv()

RAGFLOW_API_URL = "https://ragflow-ogno0-u30628.vm.elestio.app"
RAGFLOW_API_KEY = "ragflow-Q1NmJhMTcyZDViNTExZWY5ZTY3MDI0Mm"

# Separate storage for query history for each section
query_history = {
    'main': [],
    'for_against': [],
    'bare_acts': []
}

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

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

@app.route('/chat', methods=['POST'])
def chat():
    data = request.json
    user_query = data.get('query')
    section = data.get('section', 'main')  # Default to main if not specified
    
    if not user_query:
        return jsonify({'error': 'No query provided'}), 400

    # Store query in appropriate history
    query_history[section].append({'query': user_query, 'timestamp': datetime.now().isoformat()})

    try:
        session = get_or_create_session(section)
        cont = ""
        response_content = ""
        for ans in session.ask(user_query, stream=True):
            response_content += ans.content[len(cont):]
            cont = ans.content

        query_history[section][-1]['response'] = response_content
        return jsonify({'answer': response_content})

    except Exception as e:
        print(f"Ragflow error: {e}")
        return jsonify({'error': 'Unable to process the request at this time'}), 500

@app.route('/history/<section>', methods=['GET'])
def get_history(section):
    return jsonify(query_history.get(section, []))

@app.route('/history/<section>/clear', methods=['POST'])
def clear_history(section):
    global global_sessions
    if section in query_history:
        query_history[section].clear()
        # Reset the session for the specific section
        global_sessions[section] = None
        return jsonify({'message': f'Query history cleared for {section}'}), 200
    return jsonify({'error': 'Invalid section'}), 400

@app.route("/")
def home():
    return "Hello, this is the chatbot!"

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
