from flask import Flask, request, jsonify, Response
import requests
from dotenv import load_dotenv
from flask_cors import CORS
from datetime import datetime, timedelta
import json
import re  # Add at the top with other imports
import boto3
from botocore.exceptions import ClientError
import os
import logging
import threading
from typing import List, Dict, Any

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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

# Load AWS credentials from .env
# Load AWS credentials from .env
AWS_ACCESS_KEY = os.getenv('AWS_ACCESS_KEY').strip('"')
AWS_SECRET_KEY = os.getenv('AWS_SECRET_KEY').strip('"')
S3_BUCKET = os.getenv('S3_BUCKET').strip('"')
S3_KEY = os.getenv('S3_KEY').strip('"')

# Initialize S3 client
s3 = boto3.client(
    's3',
    aws_access_key_id=AWS_ACCESS_KEY,
    aws_secret_access_key=AWS_SECRET_KEY
)

class JudgmentManager:
    _instance = None
    _lock = threading.Lock()
    
    def __init__(self):
        if not hasattr(self, '_judgments'):
            self._judgments = []
            self._loaded = False

    @classmethod
    def get_instance(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance
    
    def load_judgments(self):
        if not self._loaded:
            with self._lock:
                if not self._loaded:
                    try:
                        logger.info("Loading judgments from S3")
                        s3 = boto3.client('s3', aws_access_key_id=AWS_ACCESS_KEY, aws_secret_access_key=AWS_SECRET_KEY)
                        obj = s3.get_object(Bucket=S3_BUCKET, Key=S3_KEY)
                        raw_content = obj['Body'].read().decode('utf-8')
                        raw_content = re.sub(r',(\s*[}\]])', r'\1', raw_content)
                        raw_data = json.loads(raw_content)
                        self._judgments = self.process_judgment_data(raw_data)
                        self._loaded = True
                        logger.info(f"Successfully loaded {len(self._judgments)} judgments")
                    except Exception as e:
                        logger.error(f"Judgment loading failed: {str(e)}")
                        raise

    @staticmethod
    def validate_judgment_data(judgment: Dict[str, Any]) -> bool:
        required_fields = ['JudgmentSummary']
        if not all(field in judgment for field in required_fields):
            return False
        return True

    @staticmethod
    def process_judgment_data(raw_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        processed = []
        for judgment in raw_data:
            try:
                if not JudgmentManager.validate_judgment_data(judgment):
                    continue
                    
                summary = judgment["JudgmentSummary"]
                processed.append({
                    "id": summary.get("DocumentID", ""),
                    "name": summary.get("JudgmentName", "Untitled"),
                    "intro": summary.get("Brief", {}).get("Introduction", "")
                })
            except Exception as e:
                logger.error(f"Skipping invalid judgment: {str(e)}")
                continue
        return processed

    @property
    def judgments(self):
        if not self._loaded:
            self.load_judgments()
        return self._judgments

def find_relevant_judgments(query: str) -> List[Dict[str, str]]:
    judgment_manager = JudgmentManager.get_instance()
    query_lower = query.lower()
    relevant = []
    
    for judgment in judgment_manager.judgments:
        search_text = ' '.join([
            judgment["name"],
            judgment["intro"]
        ]).lower()
        
        if query_lower in search_text:
            relevant.append({
                "name": judgment["name"],
                "intro": judgment["intro"]
            })
            if len(relevant) >= 3:
                break
                
    logger.info(f"Found {len(relevant)} relevant judgments for query: {query}")
    return relevant

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

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

def stream_deepseek_response(user_query, section, chat_id):
    system_messages = {
        'main': "You are a helpful legal assistant, providing clear and accurate information about legal matters.",
        'for_against': "You are a legal analyst specializing in presenting balanced arguments for and against legal positions.",
        'bare_acts': "You are a legal expert focusing on explaining sections of legal acts and statutes in simple terms."
    }
    
    headers = {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'Authorization': f'Bearer {DEEPSEEK_API_KEY}'
    }

    payload = {
        "messages": [
            {"role": "system", "content": system_messages[section]},
            {"role": "user", "content": user_query}
        ],
        "model": "deepseek-chat",
        "max_tokens": 8192,
        "temperature": 0.7,
        "stream": True
    }

    response = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload, stream=True)
    
    full_response = []
    # Stream main response
    for line in response.iter_lines():
        if line:
            decoded_line = line.decode('utf-8').strip()
            if decoded_line.startswith('data: '):
                json_str = decoded_line[6:]
                if json_str == '[DONE]':
                    continue

                try:
                    data = json.loads(json_str)
                    if 'choices' in data and data['choices'][0]['delta'].get('content'):
                        chunk = data['choices'][0]['delta']['content']
                        full_response.append(chunk)
                        yield f"data: {json.dumps({'content': chunk, 'chat_id': chat_id})}\n\n"
                except json.JSONDecodeError:
                    print(f"Failed to parse JSON chunk: {json_str}")
                    continue

    # Add judgments after main response
    judgment_text = ""
    # Modified judgment handling
    if section == 'for_against':
        try:
            judgments = find_relevant_judgments(user_query)
            if judgments:
                judgment_text = "\n\n**Relevant Judgments:**\n"
                for idx, j in enumerate(judgments, 1):
                    judgment_text += f"{idx}. **{j['name']}**\n{j['intro']}\n\n"
                
                yield f"data: {json.dumps({'content': judgment_text, 'type': 'judgments', 'chat_id': chat_id})}\n\n"
        except Exception as e:
            logger.error(f"Judgment processing failed: {str(e)}")
    # Send single DONE event after all content
    yield "data: [DONE]\n\n"

    # Store complete response
    complete_response = ''.join(full_response)
    query_history[section].append({
        'chat_id': chat_id,
        'query': user_query,
        'response': complete_response,
        'timestamp': datetime.now().isoformat()
    })

@app.route('/chat', methods=['POST'])
def chat():
    data = request.json
    user_query = data.get('query')
    section = data.get('section', 'main')
    chat_id = data.get('chat_id')

    if not user_query:
        return jsonify({'error': 'No query provided'}), 400

    # Generate new chat_id if not provided or invalid
    if not chat_id or chat_id not in chat_titles.get(section, {}):
        chat_id = get_chat_id()
        chat_titles.setdefault(section, {})[chat_id] = {
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

    return Response(
        stream_deepseek_response(user_query, section, chat_id),
        mimetype='text/event-stream'
    )

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

@app.route('/autocomplete', methods=['GET'])
def autocomplete():
    search_term = request.args.get('term', '').lower()
    section = request.args.get('section', 'main')
    suggestions = []

    if section in query_history:
        words = set()
        # Extract words using regex to ignore punctuation
        word_pattern = re.compile(r'\b\w+\b')
        
        for entry in query_history[section]:
            # Process queries
            query_words = word_pattern.findall(entry['query'].lower())
            # Process responses
            response_words = word_pattern.findall(entry['response'].lower())
            words.update(query_words + response_words)
        
        # Get matching suggestions
        suggestions = [word for word in words if word.startswith(search_term)]
        suggestions = sorted(suggestions)[:5]  # Return top 5 sorted results

    return jsonify(suggestions)

@app.route("/")
def home():
    return "Hello, this is the chatbot!"

@app.route('/debug/judgments')
def debug_judgments():
    judgment_manager = JudgmentManager.get_instance()
    judgments = judgment_manager.judgments  # This will load if not already loaded
    return jsonify({
        'count': len(judgments),
        'structure_sample': judgments[0] if judgments else None,
        'relevant_sample': find_relevant_judgments("Medical Termination of Pregnancy Act")[:2]
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
