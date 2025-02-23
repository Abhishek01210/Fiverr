import os
from asyncio import TimeoutError
import gspread
import logging
import json
from collections import defaultdict
import asyncio
import aiohttp
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from json import JSONDecodeError
from contextlib import asynccontextmanager
from fastapi import FastAPI, BackgroundTasks, HTTPException
from pydantic import BaseModel
from vapi import AsyncVapi
from openai import AsyncOpenAI, APIError
from google.oauth2.service_account import Credentials
from collections import defaultdict
from datetime import datetime
from twilio.rest import Client
from dotenv import load_dotenv
load_dotenv()

logger = logging.getLogger(__name__)

# Update logging config at top of file
logging.basicConfig(
    level=logging.INFO,  # Changed from INFO to DEBUG
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('app.log')
    ]
)

call_states = defaultdict(dict)

# Initialize locks for each call_id
locks = defaultdict(asyncio.Lock)

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting application initialization...")
    await validate_env()
    await validate_vapi()
    await test_sheets()
    logger.info("Application startup completed")
    
    yield  # App runs here
    
    # Cleanup logic
    logger.info("Shutting down...")
    try:
        gc.session.close()  # Close Google Sheets session
        logger.info("Connections closed gracefully")
    except Exception as e:
        logger.error(f"Cleanup error: {str(e)}")

app = FastAPI(lifespan=lifespan)

current_dir = os.path.dirname(os.path.abspath(__file__))

# Configuration
# In the Config class:
class Config:
    VAPI_TOKEN = os.getenv("VAPI_TOKEN")
    OPENAI_KEY = os.getenv("OPENAI_KEY")

    GS_SHEET_KEY = "1uFjrbfDijKsD4cUwqxZNTmDeDR66NLfpjr25oImb4Vk"
    BASE_SCRIPT = "Hi, this is Abhimanyu from Paintworks Finance limited. We help businesses like yours with Business Loans, Investment Strategies and Cash Flow Solutions. I'd love to connect and explore how we can support your growth. Feel free to reach out or visit fivewaysaccounting.com to schedule a call. Looking forward to speaking with you!"
    # Load credentials properly
    GS_CREDS = Credentials.from_service_account_file(
        os.path.join(current_dir, "Google Console Credentials.json"),
        scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

config = Config()
vapi = AsyncVapi(token=config.VAPI_TOKEN)
openai = AsyncOpenAI(api_key=config.OPENAI_KEY)

# Google Sheets Client
gc = gspread.authorize(config.GS_CREDS)
sheet = gc.open_by_key(config.GS_SHEET_KEY).sheet1

# Pydantic Models
class CallRequest(BaseModel):
    phone_number_id: str
    assistant_id: str
    customer_number: str

class CallAnalysis(BaseModel):
    transcript: str
    ivr_path: list[str]
    is_human: bool

# Initialize in Config
config = Config()

# Modify the call context structure
call_contexts = defaultdict(lambda: {
    'ivr_path': [],
    'state': 'initial',
    'retry_count': 0,
    'max_retries': 3,
    'last_dtmf': None,
    'control_url': None,
    'message_injected': False,  # Renamed from 'message_delivered' to indicate injection
    'message_delivered': False,  # New flag for when message is fully spoken
    'ending': False,
    'assistant_transcript': ''  # New field to accumulate assistant's speech
})

class InvalidAnalysisResult(Exception):
    pass

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((APIError, TimeoutError, JSONDecodeError, InvalidAnalysisResult))
)
async def analyze_conversation(transcript: str) -> dict:
    """Enhanced analysis to detect IVR scenarios and determine next action"""
    prompt = f"""Analyze this phone interaction transcript and return a JSON object with:
- "is_human": boolean (true if human response detected, false if IVR)
- "ivr_detected": boolean (true if IVR menu detected)
- "ivr_options": dict (mapping of option numbers to descriptions, e.g., {{"1": "Accounts Payable"}})
- "scenario": string ("direct_departments" | "general_finance" | "no_finance" | "no_ivr")
- "next_action": string ("deliver_message" | "navigate_ivr" | "end_call")
- "target_option": string (specific option number to select, if applicable)

Rules:
1. If human-like responses (short or conversational), set is_human=true, scenario="no_ivr"
2. If IVR menu with direct options (e.g., "Press 1 for Accounts Payable"), scenario="direct_departments"
3. If IVR menu with general "Accounts" or "Finance" option, scenario="general_finance"
4. If IVR menu without Accounts/Finance, scenario="no_finance"

Transcript: {transcript}"""
    try:
        response = await openai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.0
        )
        analysis = json.loads(response.choices[0].message.content)
        logger.info(f"OpenAI Analysis Result: {analysis}")
        
        # Validate analysis structure
        required_keys = {"is_human", "ivr_detected", "ivr_options", "scenario", "next_action", "target_option"}
        if not all(key in analysis for key in required_keys):
            raise InvalidAnalysisResult("Missing required analysis fields")
        
        return analysis
    except Exception as e:
        logger.error(f"OpenAI analysis failed: {str(e)}")
        return {
            "is_human": False,
            "ivr_detected": False,
            "ivr_options": {},
            "scenario": "no_ivr",
            "next_action": "end_call",
            "target_option": None
        }   

COLUMN_MAPPING = {
    "Connection Test": "A",
    "Contact Number": "B",
    "Status": "C",
    'Call Summary': 'D',
    'Transcript': 'E',
    'IVR Option': 'F',
    'Call Duration': 'G',
    'Cost': 'I'
}

async def update_sheet(row: int, data: dict):
    try:
        updates = []
        for key, value in data.items():
            col = COLUMN_MAPPING.get(key)
            if col:
                updates.append((f"{col}{row}", value))
        
        if updates:
            sheet.batch_update([
                {
                    'range': cell,
                    'values': [[value]]
                }
                for cell, value in updates
            ])
    except Exception as e:
        logger.error(f"Sheet update failed: {str(e)}")

async def determine_ivr_path(transcript: str, analysis: dict) -> str:
    """Determine DTMF sequence based on IVR scenario"""
    if not analysis["ivr_detected"]:
        return ""  # No IVR, no DTMF needed
    
    ivr_options = analysis["ivr_options"]
    scenario = analysis["scenario"]
    context = call_contexts.get(message['call']['id'], {}) if 'message' in globals() else {}

    if scenario == "direct_departments":
        # Navigate to Accounts Payable
        for option, desc in ivr_options.items():
            if "accounts payable" in desc.lower():
                return option
        logger.warning("Accounts Payable not found in direct options")
        return ""  # Fallback to empty if not found

    elif scenario == "general_finance":
        # First level: Navigate to Accounts/Finance
        if not context.get("in_submenu", False):
            for option, desc in ivr_options.items():
                if "accounts" in desc.lower() or "finance" in desc.lower():
                    context["in_submenu"] = True
                    return option
        # Second level: Navigate to Accounts Receivable
        else:
            for option, desc in ivr_options.items():
                if "accounts receivable" in desc.lower():
                    return option
        logger.warning("Target option not found in general finance menu")
        return ""

    elif scenario == "no_finance":
        # Navigate to Receptionist
        for option, desc in ivr_options.items():
            if "receptionist" in desc.lower() or "operator" in desc.lower() or "main" in desc.lower():
                return option
        logger.warning("Receptionist option not found")
        return ""  # Fallback to empty if not found

    return ""  # Default fallback

async def handle_conversation_update(message: dict):
    try:
        call_id = message['call']['id']
        context = call_contexts[call_id]

        async with locks[call_id]:  # Acquire lock for this call_id
            # Skip if call is ending
            if context.get('ending', False):
                logger.info(f"Call {call_id} is ending, skipping update")
                return {"status": "skipped"}

            # Skip if message has already been injected
            if context.get('message_injected', False):
                logger.info(f"Message already injected for call {call_id}, skipping")
                return {"status": "skipped"}
            
            if context.get('message_delivered', False):
                logger.info(f"Message already delivered for call {call_id}, ending call")
                control_url = context.get('control_url')
                if control_url:
                    await end_call(control_url)
                    context['ending'] = True
                return {"status": "skipped"}

            conversation = message.get('conversation', [])
            transcript = "\n".join([msg['content'] for msg in conversation if msg['role'] == 'user'])
            logger.info(f"Raw transcript: {transcript}")
            
            analysis = await analyze_conversation(transcript)
            logger.debug(f"OpenAI Analysis Result: {analysis}")
            
            if analysis.get('is_human') and not context.get('message_injected', False):
                context['state'] = 'human_detected'
                logger.info("Human detected - injecting BASE_SCRIPT via controlUrl")
                control_url = context.get('control_url')
                if control_url:
                    logger.info(f"Using controlUrl to inject message: {control_url}")
                    await inject_message(control_url, config.BASE_SCRIPT)
                    context['message_injected'] = True
                    context['assistant_transcript'] = ''
                else:
                    logger.warning("No controlUrl available to inject message")
                return {"status": "processed"}
            
            if analysis["ivr_detected"]:
                dtmf_sequence = await determine_ivr_path(transcript, analysis)
                if dtmf_sequence:
                    description = analysis['ivr_options'].get(dtmf_sequence, 'Unknown')
                    context['ivr_path'].append((dtmf_sequence, description))
                    twilio_sid = call_contexts[call_id].get('twilio_sid')
                    if twilio_sid:
                        await send_dtmf_twilio(twilio_sid, dtmf_sequence)
                        logger.info(f"Sent DTMF: {dtmf_sequence} ({description}) via Twilio")
                    else:
                        logger.error(f"No Twilio SID for call {call_id}")
                else:
                    logger.info("No valid DTMF option found, treating as human target")
                    if not context.get('message_injected', False):
                        control_url = context.get('control_url')
                        if control_url:
                            await inject_message(control_url, config.BASE_SCRIPT)
                            context['message_injected'] = True
                            context['assistant_transcript'] = ''
                return {"status": "processed"}
            
    except Exception as e:
        logger.error(f"Error in conversation update: {str(e)}", exc_info=True)
        return {"status": "error", "message": str(e)}
    
async def handle_ivr_interaction(call_id: str, analysis: CallAnalysis):
    if analysis.is_human:
        control_url = call_contexts[call_id].get('control_url')
        if control_url:
            await inject_message(control_url, config.BASE_SCRIPT)  # Replaced here
        else:
            logger.error("No controlUrl available to inject message")
        await vapi.calls.end(call_id)
    else:
        dtmf_sequence = "".join(analysis.ivr_path)
        twilio_sid = call_contexts[call_id].get('twilio_sid')
        if twilio_sid:
            await send_dtmf_twilio(twilio_sid, dtmf_sequence)
        else:
            logger.error(f"No Twilio SID for call {call_id}")

async def inject_message(control_url: str, message: str):
    """Inject a message into a live call using the controlUrl."""
    async with aiohttp.ClientSession() as session:
        payload = {
            "type": "say",
            "message": message
        }
        try:
            async with session.post(control_url, json=payload, headers={"Content-Type": "application/json"}) as response:
                if response.status == 200:
                    logger.info(f"Successfully injected message to {control_url}")
                else:
                    logger.error(f"Failed to inject message: {response.status} - {await response.text()}")
        except Exception as e:
            logger.error(f"Error injecting message: {str(e)}")

async def send_dtmf_twilio(call_sid: str, digits: str):
    """Send DTMF tones using Twilio API"""
    try:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            lambda: client.calls(call_sid).update(
                twiml=f'<Response><Play digits="{digits}"></Play></Response>'
            )
        )
        logger.info(f"DTMF {digits} sent to Twilio call {call_sid}")
    except Exception as e:
        logger.error(f"Twilio DTMF Error: {str(e)}")

async def end_call(control_url: str):
    async with aiohttp.ClientSession() as session:
        payload = {"type": "end-call"}
        try:
            async with session.post(control_url, json=payload, headers={"Content-Type": "application/json"}) as response:
                if response.status == 200:
                    logger.info(f"Successfully ended call via {control_url}")
                else:
                    logger.error(f"Failed to end call: {response.status} - {await response.text()}")
        except Exception as e:
            logger.error(f"Error ending call: {str(e)}")

async def delayed_end_call(control_url: str, delay: float, call_id: str):
    await asyncio.sleep(delay)
    await end_call(control_url)
    call_contexts[call_id]['ending'] = True
    logger.info(f"Call {call_id} scheduled to end after {delay} seconds")

@app.post("/initiate-calls")
async def start_calls(background_tasks: BackgroundTasks):
    """Main endpoint to start calling process"""
    try:
        records = sheet.get_all_records()
        to_call = [i+2 for i, row in enumerate(records) if row['Status'] == 'not-called']
        
        for row_num in to_call:
            number = records[row_num-2]['Phone Number']
            background_tasks.add_task(process_call, row_num, number)
            
        return {"status": "started", "calls": len(to_call)}
    except Exception as e:
        raise HTTPException(500, str(e))

async def safe_sleep(delay: float):
    """Wrapper for async sleep with import verification"""
    try:
        await asyncio.sleep(delay)
    except NameError:
        logger.critical("asyncio not imported!")
        raise

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
async def safe_api_call(func, *args, **kwargs):
    try:
        return await func(*args, **kwargs)
    except Exception as e:
        logger.error(f"API call failed: {str(e)}")
        raise

# Add batch processing capability
async def process_calls():
    """Batch call initiation with proper row handling"""
    try:
        records = sheet.get_all_records()
        uncalled = [row for row in records if row['Status'] == 'not-called']
        
        for idx, record in enumerate(uncalled):
            row_id = idx + 2  # Adjust for header row
            try:
                await process_call(row_id, record['Phone Number'])
            except Exception as e:
                logger.error(f"Failed processing row {row_id}: {str(e)}")
                await update_sheet(row_id, {'Status': 'failed'})
    except Exception as e:
        logger.error(f"Error in batch processing: {str(e)}")

# Add transcript summarization
async def summarize_transcript(transcript: str) -> str:
    """Generate call summary using OpenAI"""
    response = await openai.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": f"Summarize this call transcript: {transcript}"}]
    )
    return response.choices[0].message.content

async def process_call(row_num: int, number: str):
    try:
        logger.info(f"Initiating call to {number}")
        call = await safe_api_call(
            vapi.calls.create,
            assistant_id=os.getenv("ASSISTANT_ID"),
            customer={"number": number},
            phone_number_id=os.getenv("PHONE_NUMBER_ID"),
            assistant_overrides={
                "firstMessageMode": "assistant-waits-for-user",
                "maxDurationSeconds": 120
            }
        )
        logger.info(f"Call created: {call.id}")
        await update_sheet(row_num, {'Status': 'calling', 'Call ID': call.id})

        # Monitor status with timeout and retrieve Twilio SID
        timeout = 30  # seconds
        start_time = datetime.now()
        while (datetime.now() - start_time).total_seconds() < timeout:
            full_call = await safe_api_call(vapi.calls.get, call.id)
            logger.info(f"Call {call.id} status: {full_call.status}")
            if full_call.status in ["in-progress", "active"] and hasattr(full_call, 'phone_call_provider_id') and full_call.phone_call_provider_id:
                call_contexts[call.id]['twilio_sid'] = full_call.phone_call_provider_id
                logger.info(f"Retrieved Twilio SID for call {call.id}: {full_call.phone_call_provider_id}")
                break
            elif full_call.status == "ended":
                logger.info(f"Call {call.id} ended early")
                break
            await safe_sleep(1)
        else:
            logger.warning(f"Call {call.id} did not reach 'in-progress' with Twilio SID within {timeout}s")
            await update_sheet(row_num, {'Status': 'failed: queued timeout'})
            return

        # Initialize context
        call_contexts[call.id].update({
            'ivr_path': [],
            'state': 'initial',
            'message_delivered': False,
            'ending': False
        })

        await update_sheet(row_num, {
            'Status': 'calling',
            'Phone Number': number,
            'Call ID': call.id
        })
        
        while True:
            status = await safe_api_call(vapi.calls.get, call.id)
            if status.status == "ended":
                logger.debug(f"Call {call.id} confirmed ended")
                break
            await safe_sleep(1)

        transcript = "\n".join(status.transcript) if isinstance(status.transcript, list) else status.transcript
        summary = await summarize_transcript(transcript)
        
        duration = 0
        try:
            if all([status.started_at, status.ended_at]):
                started_str = str(status.started_at).split('+')[0]
                ended_str = str(status.ended_at).split('+')[0]
                started = datetime.fromisoformat(started_str)
                ended = datetime.fromisoformat(ended_str)
                duration = (ended - started).total_seconds()
        except Exception as time_err:
            logger.warning(f"Duration calculation failed: {str(time_err)}")
            duration = 0

        # Fetch IVR path and format it
        ivr_path = call_contexts[call.id].get('ivr_path', [])
        if ivr_path:
            ivr_options_str = "\n".join([f"{digit} - {desc}" for digit, desc in ivr_path])
        else:
            ivr_options_str = "No IVR Option Available"

        # Fetch call cost
        cost = 0
        if hasattr(status, 'cost'):
            cost = status.cost
        else:
            logger.warning(f"Cost not available for call {call.id}")
            cost = 0

        # Update sheet with IVR options and cost
        await update_sheet(row_num, {
            'Status': 'called',
            'Transcript': transcript,
            'Call Summary': summary,
            'IVR Option': ivr_options_str,
            'Call Duration': duration,
            'Cost': cost
        })
    except Exception as e:
        logger.error(f"FATAL CALL FAILURE: {str(e)}", exc_info=True)
        await update_sheet(row_num, {'Status': f'failed: {str(e)[:50]}'})

# Add helper function for sheet updates by call ID
async def update_sheet_by_call_id(call_id: str, data: dict):
    """Find row by call ID and update"""
    records = sheet.get_all_records()
    for idx, row in enumerate(records, start=2):  # Start from row 2
        if row.get('Call ID') == call_id:
            await update_sheet(idx, data)
            break

@app.post("/vapi-webhook")
async def vapi_webhook(data: dict):
    message = data.get('message', {})
    event_type = message.get('type')
    call_id = message.get('call', {}).get('id')

    if call_id and 'monitor' in message.get('call', {}):
        control_url = message['call']['monitor'].get('controlUrl')
        if control_url and call_contexts[call_id].get('control_url') is None:
            call_contexts[call_id]['control_url'] = control_url
            logger.debug(f"Stored controlUrl from webhook for call {call_id}: {control_url}")

    if event_type == "transcript" and message.get('role') == 'assistant':
        context = call_contexts[call_id]
        if context.get('message_injected', False) and not context.get('message_delivered', False):
            context['assistant_transcript'] += message.get('transcript', '')
            if "Looking forward to speaking with you" in context['assistant_transcript']:
                context['message_delivered'] = True
                control_url = context.get('control_url')
                if control_url:
                    await end_call(control_url)
                    context['ending'] = True
                    logger.info(f"Call {call_id} ending immediately after message delivery")
                else:
                    logger.warning(f"No controlUrl to end call {call_id}")
        return {"status": "processed"}
    elif event_type == "conversation-update":
        response = await handle_conversation_update(message)
        return response
    elif event_type == "end-of-call":
        # Handle end-of-call event
        cost = message.get('cost', 0)
        call_contexts[call_id]['cost'] = cost
        logger.info(f"Received end-of-call event for {call_id} with cost: {cost}")
        # Update sheet with cost
        await update_sheet_by_call_id(call_id, {'Cost': cost})
        return {"status": "processed"}
    return {"status": "processed"}

async def handle_call_update(call_data: dict):
    """Real-time call state handling"""
    if call_data['status'] == "in-progress":
        await vapi.calls.send_dtmf(
            call_data['id'],
            digits=await determine_dtmf_sequence(call_data['transcript'])
        )

async def determine_dtmf_sequence(transcript: str) -> str:
    """Determine DTMF based on conversation analysis"""
    analysis = await analyze_conversation(transcript)
    return analysis.get('next_dtmf', "")

# Add to VAPI Integration section
async def get_realtime_analytics():
    """Implement Milestone 2 analytics requirements"""
    return await vapi.analytics.get(
        queries=[{
            "name": "call_metrics",
            "operations": [{
                "operation": "sum",
                "column": "duration"
            }, {
                "operation": "count",
                "column": "id"
            }]
        }]
    )

# Update /call-analytics endpoint
@app.get("/call-analytics")
async def get_analytics():
    """Enhanced analytics endpoint"""
    vapi_analytics = await get_realtime_analytics()
    sheet_data = sheet.get_all_records()
    
    return {
        "total_calls": len(sheet_data),
        "success_rate": sum(1 for r in sheet_data if r['Status'] == 'called') / len(sheet_data),
        "avg_duration": sum(r['Call Duration'] for r in sheet_data if r['Call Duration']) / len(sheet_data),
        "total_cost": sum(r.get('Cost', 0) for r in sheet_data),
        "realtime_metrics": vapi_analytics
    }

# Enhance the debug/script endpoint to show both generated script and system prompts
@app.get("/debug/script")
async def debug_current_script():
    """Show generated script and system prompts"""
    assistant = await vapi.assistants.get(os.getenv("ASSISTANT_ID"))
    system_prompts = [
        {"index": idx, "content": msg.content}
        for idx, msg in enumerate(assistant.model.messages)
        if msg.role == "system"
    ]
    
    return {
        "system_prompts": system_prompts
    }
    
async def validate_env():
    required_vars = ['VAPI_TOKEN', 'OPENAI_KEY', 'ASSISTANT_ID', 'PHONE_NUMBER_ID', 'TWILIO_ACCOUNT_SID', 'TWILIO_AUTH_TOKEN']
    missing = [var for var in required_vars if not os.getenv(var)]
    if missing:
        raise RuntimeError(f"Missing environment variables: {', '.join(missing)}")
    
async def validate_vapi():
    try:
        await vapi.calls.list(limit=1)
        logger.info("VAPI connection successful")
    except Exception as e:
        logger.error(f"VAPI connection failed: {str(e)}")
        raise

async def test_sheets():
    try:
        sheet.update_acell('A1', 'Connection Test')
        logger.info("Sheets connection working")
    except Exception as e:
        logger.error(f"Sheets failed: {str(e)}")
        raise