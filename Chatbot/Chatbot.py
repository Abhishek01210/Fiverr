from flask import Flask, request, jsonify, Response
import requests
from dotenv import load_dotenv
from flask_cors import CORS
from datetime import datetime, timedelta
import json
import re
import boto3
from botocore.exceptions import ClientError
import tempfile
import os
import logging
from typing import List, Dict, Any, Optional

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

load_dotenv()

DEEPSEEK_API_KEY = os.getenv('DEEPSEEK_API_KEY', "sk-802fe5996aa441199db50ff2c951a261")
DEEPSEEK_API_URL = os.getenv('DEEPSEEK_API_URL', "https://api.deepseek.com/chat/completions")
AWS_ACCESS_KEY = os.getenv('AWS_ACCESS_KEY')
AWS_SECRET_KEY = os.getenv('AWS_SECRET_KEY')
S3_BUCKET = os.getenv('S3_BUCKET')
S3_KEY = os.getenv('S3_KEY')

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

class JudgmentProcessingError(Exception):
    """Custom exception for judgment processing errors"""
    pass

def validate_judgment_data(judgment: Dict[str, Any]) -> bool:
    """
    Validate the structure of a judgment entry.
    
    Args:
        judgment: Dictionary containing judgment data
    
    Returns:
        bool: True if valid, False otherwise
    """
    try:
        required_fields = ['JudgmentSummary']
        if not all(field in judgment for field in required_fields):
            logger.warning(f"Missing required fields in judgment: {required_fields}")
            return False

        summary = judgment['JudgmentSummary']
        required_summary_fields = ['DocumentID', 'JudgmentName', 'Brief']
        if not all(field in summary for field in required_summary_fields):
            logger.warning(f"Missing required summary fields: {required_summary_fields}")
            return False

        if 'Introduction' not in summary['Brief']:
            logger.warning("Missing Introduction in Brief")
            return False

        return True
    except Exception as e:
        logger.error(f"Error validating judgment data: {str(e)}")
        return False

def process_judgment_data(raw_data: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """
    Process raw judgment data into a standardized format.
    
    Args:
        raw_data: List of raw judgment dictionaries
    
    Returns:
        List of processed judgment dictionaries
    
    Raises:
        JudgmentProcessingError: If processing fails
    """
    processed = []
    
    if not isinstance(raw_data, list):
        raise JudgmentProcessingError("Raw data must be a list")
    
    for index, judgment in enumerate(raw_data):
        try:
            if not validate_judgment_data(judgment):
                logger.warning(f"Skipping invalid judgment at index {index}")
                continue
                
            summary = judgment["JudgmentSummary"]
            processed.append({
                "id": summary.get("DocumentID", ""),
                "name": summary.get("JudgmentName", "Untitled"),
                "intro": summary.get("Brief", {}).get("Introduction", "")
            })
            logger.info(f"Successfully processed judgment {summary.get('DocumentID', 'Unknown ID')}")
            
        except Exception as e:
            logger.error(f"Error processing judgment at index {index}: {str(e)}")
            continue
    
    if not processed:
        raise JudgmentProcessingError("No valid judgments were processed")
        
    return processed

def get_s3_client():
    """
    Create and return an S3 client with proper error handling.
    
    Returns:
        boto3.client: Configured S3 client
    
    Raises:
        Exception: If client creation fails
    """
    try:
        if not AWS_ACCESS_KEY or not AWS_SECRET_KEY:
            raise ValueError("AWS credentials not properly configured")
            
        return boto3.client(
            's3',
            aws_access_key_id=AWS_ACCESS_KEY,
            aws_secret_access_key=AWS_SECRET_KEY
        )
    except Exception as e:
        logger.error(f"Failed to create S3 client: {str(e)}")
        raise

def load_judgments_from_s3() -> List[Dict[str, str]]:
    try:
        logger.info("Starting judgment loading process")
        s3_client = get_s3_client()
        
        try:
            obj = s3_client.get_object(Bucket=S3_BUCKET, Key=S3_KEY)
        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == 'NoSuchBucket':
                logger.error(f"S3 bucket '{S3_BUCKET}' does not exist")
            elif error_code == 'NoSuchKey':
                logger.error(f"File '{S3_KEY}' not found in bucket '{S3_BUCKET}'")
            else:
                logger.error(f"S3 error: {str(e)}")
            raise

        try:
            raw_content = obj['Body'].read().decode('utf-8')
            
            # Remove BOM if present
            if raw_content.startswith('\ufeff'):
                raw_content = raw_content[1:]
            
            # Clean the JSON content
            raw_content = raw_content.strip()
            
            # Fix trailing commas before closing brackets
            raw_content = re.sub(r',(\s*])', r'\1', raw_content)  # Fix array trailing commas
            raw_content = re.sub(r',(\s*})', r'\1', raw_content)  # Fix object trailing commas
            
            # Remove any carriage returns and normalize newlines
            raw_content = raw_content.replace('\r\n', '\n').replace('\r', '\n')
            
            # Debug logging for content preview
            logger.debug(f"Cleaned JSON content preview: {repr(raw_content[:1000])}...")
            logger.debug(f"Last 100 chars of cleaned content: {repr(raw_content[-100:])}")
            
            try:
                raw_data = json.loads(raw_content)
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse JSON data: {str(e)}")
                error_position = e.pos
                context_start = max(0, error_position - 50)
                context_end = min(len(raw_content), error_position + 50)
                
                logger.error(f"JSON parse error at position {error_position}: {str(e)}")
                logger.error(f"Context: ...{repr(raw_content[context_start:context_end])}...")
                
                # Try one more time with stricter cleaning
                try:
                    # More aggressive cleaning
                    raw_content = re.sub(r'[\r\n\t\s]+', ' ', raw_content)  # Replace all whitespace with single spaces
                    raw_content = re.sub(r',\s*([\]}])', r'\1', raw_content)  # Remove all trailing commas
                    logger.info("Attempting parse with aggressively cleaned content")
                    raw_data = json.loads(raw_content)
                except json.JSONDecodeError as e2:
                    logger.error(f"Second parse attempt failed: {str(e2)}")
                    return []

            processed_judgments = process_judgment_data(raw_data)
            logger.info(f"Successfully processed {len(processed_judgments)} judgments")
            return processed_judgments
            
        except UnicodeDecodeError as e:
            logger.error(f"Failed to decode S3 object content: {str(e)}")
            return []
            
    except Exception as e:
        logger.error(f"Critical error in judgment loading pipeline: {str(e)}")
        return []

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

# Initialize processed judgments
PROCESSED_JUDGMENTS: List[Dict[str, str]] = []

# Update the before_request function to load judgments only once
@app.before_request
def before_request_func():
    """Initialize the application and load judgments only once."""
    global PROCESSED_JUDGMENTS
    if not PROCESSED_JUDGMENTS:
        try:
            PROCESSED_JUDGMENTS = load_judgments_from_s3()
            logger.info(f"Application initialized with {len(PROCESSED_JUDGMENTS)} judgments")
        except Exception as e:
            logger.error(f"Failed to initialize application: {str(e)}")
            PROCESSED_JUDGMENTS = []

def process_judgment_data(raw_data):
    processed = []
    
    if isinstance(raw_data, list):
        for judgment in raw_data:
            if "JudgmentSummary" in judgment:
                summary = judgment["JudgmentSummary"]
                processed.append({
                    "id": summary.get("DocumentID", ""),
                    "name": summary.get("JudgmentName", "Untitled"),
                    "intro": summary.get("Brief", {}).get("Introduction", "")
                })
    
    return processed

@app.route('/judgments', methods=['GET'])
def get_judgments():
    """Endpoint to retrieve processed judgments with pagination."""
    global PROCESSED_JUDGMENTS
    
    try:
        offset = int(request.args.get('offset', 0))
        limit = int(request.args.get('limit', 10))
        
        if not PROCESSED_JUDGMENTS:
            logger.warning("No judgments available, attempting to reload")
            PROCESSED_JUDGMENTS = load_judgments_from_s3()
            
        total = len(PROCESSED_JUDGMENTS)
        paginated_data = PROCESSED_JUDGMENTS[offset:offset+limit]
        
        return jsonify({
            "status": "success",
            "count": len(paginated_data),
            "total": total,
            "data": paginated_data
        })
    except Exception as e:
        logger.error(f"Error retrieving judgments: {str(e)}")
        return jsonify({
            "status": "error",
            "message": "Failed to retrieve judgments",
            "error": str(e)
        }), 500
    
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
        "stream": True  # Enable streaming
    }

    response = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload, stream=True)
    
    full_response = []
    for line in response.iter_lines():
        if line:
            decoded_line = line.decode('utf-8').strip()
            if decoded_line.startswith('data: '):
                json_str = decoded_line[6:]
                if json_str == '[DONE]':  # Handle termination signal
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
                    
    # Send final completion marker after all chunks
    yield "data: [DONE]\n\n"

    # Store complete response in history
    complete_response = ''.join(full_response)
    if section != 'for_against':
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

    # Generate chat_id if new conversation (only for non-for_against sections)
    if not chat_id and section != 'for_against':
        chat_id = get_chat_id()
        chat_titles[section][chat_id] = {
            'queries': [],
            'title': None,
            'timestamp': datetime.now().isoformat()
        }

    # Store query only for non-for_against sections
    if section != 'for_against':
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
    if section == 'for_against':
        return jsonify({
            'today': [],
            'yesterday': [],
            'seven_days': [],
            'thirty_days': []
        })

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

if __name__ == '__main__':
    load_judgments_from_s3()
    app.run(host='0.0.0.0', port=5000)
