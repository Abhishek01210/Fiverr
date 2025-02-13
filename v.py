import os
os.environ["PYTHONUTF8"] = "1"
os.environ["PYTHONIOENCODING"] = "utf-8"
os.environ["LC_CTYPE"] = "en_US.UTF-8"

import sys
import io
import tempfile
import re
from PIL import Image, ImageDraw, ImageFont
import numpy as np
from pilmoji import Pilmoji

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

from moviepy.editor import VideoFileClip, TextClip, CompositeVideoClip, concatenate_videoclips, ColorClip, ImageClip
import moviepy.config as mp_config
from moviepy.config import change_settings
import locale

# Set UTF-8 encoding globally
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')
locale.setlocale(locale.LC_ALL, 'en_US.UTF-8')
# ========================================
# DYNAMIC PATH HANDLING
# ========================================
def get_base_dir():
    """Get the correct base directory for both script and compiled exe"""
    if getattr(sys, 'frozen', False):
        # Running as compiled executable
        return os.path.dirname(sys.executable)
    else:
        # Running as script
        return os.path.dirname(os.path.abspath(__file__))

current_dir = get_base_dir()

# ========================================
# PATH CONFIGURATION
# ========================================
# Configure ImageMagick
imagemagick_dir = os.path.join(current_dir, "ImageMagick-7.1.1-Q8")
imagemagick_path = os.path.join(imagemagick_dir, "magick.exe")

# Configure FFmpeg
ffmpeg_path = os.path.join(current_dir, "ffmpeg", "bin", "ffmpeg.exe")

# Update MoviePy settings
change_settings({"IMAGEMAGICK_BINARY": imagemagick_path})
mp_config.change_settings({"FFMPEG_BINARY": ffmpeg_path})

# Service account and fonts
SERVICE_ACCOUNT_FILE = os.path.join(current_dir, "ivory.json")

# Update these font paths in the code
EMOJI_FONT_PATH = os.path.join(current_dir, "seguiemj.ttf")
TEXT_FONT_PATH = os.path.join(current_dir, "arial.ttf")  # Standard system font

# ========================================
# REMAINING CONSTANTS
# ========================================
SCOPES = [
    'https://www.googleapis.com/auth/drive.readonly',
    'https://www.googleapis.com/auth/spreadsheets.readonly'
]
SPREADSHEET_ID = '1A0uMFvDeGR2Vh3VUrFT2aSA11U9VpRfLCqvyWahAO24'
RANGE_NAME = 'Sheet1!A:D'
VIDEO_FOLDER_ID = '1xLYRUJvI0MVWh6xnvCYP-e0gEk7JOpA8'

OUTPUT_DIR = os.path.join(current_dir, 'output_videos')
if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR)

# ========================================
# AUTHENTICATION
# ========================================
credentials = service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE, scopes=SCOPES)

sheets_service = build('sheets', 'v4', credentials=credentials)
drive_service = build('drive', 'v3', credentials=credentials)

# ========================================
# EMOJI HANDLING FUNCTIONS
# ========================================

def is_emoji(char):
    """Check if a character is an emoji using Unicode ranges."""
    cp = ord(char)
    return (0x1F600 <= cp <= 0x1F64F or  # Emoticons
            0x1F300 <= cp <= 0x1F5FF or  # Misc Symbols and Pictographs
            0x1F680 <= cp <= 0x1F6FF or  # Transport and Map
            0x2600 <= cp <= 0x26FF or    # Misc symbols
            0x2700 <= cp <= 0x27BF or    # Dingbats
            0x1F1E6 <= cp <= 0x1F1FF)    # Flags

def create_emoji_image(emoji_char, fontsize=40):
    """Create emoji image using system emoji font with proper sizing"""
    try:
        emoji_font = ImageFont.truetype(EMOJI_FONT_PATH, fontsize)
    except Exception as e:
        print(f"Error loading emoji font: {e}")
        emoji_font = ImageFont.load_default()

    # Create temporary image to calculate size
    temp_image = Image.new("RGBA", (1, 1), (0, 0, 0, 0))
    draw = ImageDraw.Draw(temp_image)
    bbox = draw.textbbox((0, 0), emoji_char, font=emoji_font)
    
    # Create properly sized image
    width = bbox[2] - bbox[0]
    height = bbox[3] - bbox[1]
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    
    # Draw emoji centered in image
    with Pilmoji(image) as pilmoji:
        pilmoji.text((-bbox[0], -bbox[1]), emoji_char, (0, 0, 0), emoji_font)
    
    return image

# ========================================
# TEXT PROCESSING FUNCTIONS
# ========================================

def create_mixed_text_clip(text, fontsize=35, font=TEXT_FONT_PATH, color="black", max_width=None):
    try:
        text_font = ImageFont.truetype(font, fontsize)
    except:
        text_font = ImageFont.load_default()
    

    current_dir = os.path.dirname(os.path.abspath(__file__))
    noto_emoji_font_path = os.path.join(current_dir, "NotoColorEmoji-Regular.ttf")

    try:
        emoji_font = ImageFont.truetype(noto_emoji_font_path, fontsize)
    except:
        emoji_font = ImageFont.load_default()

    # Tokenize text into words, spaces, and emojis
    segments = []
    current_text = ""
    for char in text:
        if is_emoji(char):
            if current_text:
                split = re.split(r'(\s+)', current_text)
                for s in split:
                    if s.strip() == '' and s != '':
                        segments.append(('space', s))
                    elif s != '':
                        segments.append(('word', s))
                current_text = ""
            segments.append(('emoji', char))
        else:
            current_text += char
    if current_text:
        split = re.split(r'(\s+)', current_text)
        for s in split:
            if s.strip() == '' and s != '':
                segments.append(('space', s))
            elif s != '':
                segments.append(('word', s))
    # Calculate token widths with reduced spacing
    tokens = []
    for seg_type, content in segments:
        if seg_type in ('word', 'space'):
            bbox = text_font.getbbox(content)
            width = bbox[2] - bbox[0]
        elif seg_type == 'emoji':
            bbox = emoji_font.getbbox(content)
            width = bbox[2] - bbox[0]
        else:
            continue
        tokens.append((seg_type, content, width))

    # Build lines with reduced max width
    if max_width is not None:
        max_width = int(max_width)
    lines = []
    current_line = []
    current_line_width = 0
    for token in tokens:
        seg_type, content, width = token
        if current_line and max_width and (current_line_width + width) > max_width:
            lines.append(current_line)
            current_line = [token]
            current_line_width = width
        else:
            current_line.append(token)
            current_line_width += width
    if current_line:
        lines.append(current_line)

    # Trim whitespace in lines
    trimmed_lines = []
    for line in lines:
        start = 0
        while start < len(line) and line[start][0] == 'space':
            start += 1
        end = len(line) - 1
        while end >= 0 and line[end][0] == 'space':
            end -= 1
        if start > end:
            continue
        trimmed_lines.append(line[start:end+1])

    # Create line clips with reduced spacing
    line_clips = []
    line_spacing = 0  

    for line in trimmed_lines:
        clips = []
        x_offset = 0
        max_height = 0
        for seg_type, content, width in line:
            if seg_type in ('word', 'space'):
                txt_clip = TextClip("utf8:" + content, fontsize=fontsize, font=font, 
                color=color, method='caption', align='center')

                clips.append((txt_clip, x_offset))
                max_height = max(max_height, txt_clip.h)
            elif seg_type == 'emoji':
                emoji_img = create_emoji_image(content, fontsize)
                emoji_clip = ImageClip(np.array(emoji_img)).set_duration(10)
                clips.append((emoji_clip, x_offset))
                max_height = max(max_height, emoji_img.height)
            x_offset += width

        if clips:
            line_composite = CompositeVideoClip([
                clip.set_position((int(x), 0)) for clip, x in clips
            ], size=(int(x_offset), int(max_height)))
            line_clips.append(line_composite)

    # Stack lines vertically with reduced spacing
    if not line_clips:
        return CompositeVideoClip([], size=(0, 0))
    
    total_height = int(sum(clip.h + line_spacing for clip in line_clips) - line_spacing)
    y_positions = []
    current_y = 0
    for clip in line_clips:
        y_positions.append(int(current_y))
        current_y += clip.h 

    final_clip = CompositeVideoClip([
        clip.set_position(('center', y)) for clip, y in zip(line_clips, y_positions)
    ], size=(int(max_width) if max_width else 0, int(total_height)))
    
    return final_clip
# ========================================
# TEXT OVERLAY FUNCTION
# ========================================

def create_text_with_background(text, video_size, fontsize=30, font=TEXT_FONT_PATH, 
                              color="black", bg_opacity=0.8, padding=5):  # Reduced padding further
    """Create text overlay with minimal size"""
    W, H = video_size
    max_text_width = int(W * 0.8)  # Reduced from 0.8 to 0.65 for more compact width
    
    # Reduce font size for more compact appearance
    mixed_clip = create_mixed_text_clip(text, fontsize, font, color, max_width=max_text_width)
    
    txt_w, txt_h = mixed_clip.size
    
    # Create background with minimal padding
    def create_rounded_rectangle(size, radius):
        image = Image.new('L', (int(size[0]), int(size[1])), 0)
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle([(0, 0), (int(size[0])-1, int(size[1])-1)], radius=int(radius), fill=255)
        return np.array(image) / 255.0
    
    h_padding = 0 #int(fontsize * 0.2)  # Minimal horizontal padding
    v_padding = 0 #int(fontsize * 0.1)  # Normal vertical padding
    
    bg_w = int(txt_w + 2 * h_padding)
    bg_h = int(txt_h + 2 * v_padding)
    mask = create_rounded_rectangle((bg_w, bg_h), radius=12)
    bg_clip = ColorClip(size=(bg_w, bg_h), color=(255, 255, 255))
    bg_clip = bg_clip.set_mask(ImageClip(mask, ismask=True))
    bg_clip = bg_clip.set_opacity(bg_opacity)
    
    # Center the text in the background with minimal spacing
    composite = CompositeVideoClip([
        bg_clip,
        mixed_clip.set_position(("center", "center"))
    ], size=(bg_w, bg_h))

    return composite.set_position(("center", "center"))

# ========================================
# VIDEO PROCESSING FUNCTION
# ========================================

def process_video(input_video_path, texts, output_video_path):
    """Process video with proper clip durations"""
    with VideoFileClip(input_video_path) as video:
        duration = video.duration
        t_segment = duration / 3

        clips = []
        for i, text in enumerate(texts):
            start_time = i * t_segment
            with video.subclip(start_time, start_time + t_segment) as video_segment:
                text_bg_clip = create_text_with_background(
                    text,
                    video_size=video.size,
                    fontsize=35,
                    bg_opacity=0.8
                ).set_duration(t_segment)  # Match duration with video segment

                # Add fade-in/fade-out to prevent flashing
                text_bg_clip = text_bg_clip.crossfadein(0.7).crossfadeout(0.7)
                
                composite = CompositeVideoClip([
                    video_segment,
                    text_bg_clip.set_position("center")
                ])
                clips.append(composite)

        final_video = concatenate_videoclips(clips, method="compose")
        final_video.write_videofile(output_video_path, 
                                  codec="libx264", 
                                  audio_codec="aac",
                                  threads=4,  # Improve rendering performance
                                  preset='slow',  # Better quality encoding
                                  ffmpeg_params=['-crf', '18']) 
# ========================================
# GOOGLE SERVICES FUNCTIONS
# ========================================

def get_sheet_data():
    result = sheets_service.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=RANGE_NAME
    ).execute()
    values = result.get('values', [])
    if not values:
        print('No data found in sheet.')
        return []
    data_rows = values[1:]
    filtered_rows = []
    for row in data_rows:
        if len(row) >= 4 and all(cell.strip() != "" for cell in row[:4]):
            filtered_rows.append(row)
        else:
            print(f"Skipping invalid row: {row}")
    return filtered_rows

def list_videos_in_folder(folder_id):
    query = f"'{folder_id}' in parents and mimeType contains 'video/' and trashed=false"
    files = []
    page_token = None
    while True:
        response = drive_service.files().list(
            q=query,
            spaces='drive',
            fields='nextPageToken, files(id, name)',
            pageToken=page_token
        ).execute()
        files.extend(response.get('files', []))
        page_token = response.get('nextPageToken')
        if not page_token:
            break
    return sorted(files, key=lambda f: f['name'])

def download_video(video_file_id, destination_path):
    request = drive_service.files().get_media(fileId=video_file_id)
    fh = io.FileIO(destination_path, 'wb')
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done:
        status, done = downloader.next_chunk()
        print(f"Download progress: {int(status.progress() * 100)}%")
    fh.close()
    print(f"Downloaded video to {destination_path}")

# ========================================
# MAIN PROCESS
# ========================================

def main():
    print("Fetching text content from Google Sheets...")
    sheet_rows = get_sheet_data()
    if not sheet_rows:
        print("No valid text rows found in the sheet.")
        return

    print("Listing videos from Google Drive...")
    video_files = list_videos_in_folder(VIDEO_FOLDER_ID)
    if not video_files:
        print("No video files found in the specified folder.")
        return

    total_to_process = min(len(sheet_rows), len(video_files))
    print(f"\nProcessing {total_to_process} videos...")

    for idx in range(total_to_process):
        row = sheet_rows[idx]
        video_info = video_files[idx]
        set_id = row[0].strip()
        texts = [row[1].strip(), row[2].strip(), row[3].strip()]
        print(f"\nProcessing SET {set_id} with video '{video_info['name']}'...")
        temp_video_path = os.path.join(tempfile.gettempdir(), f"temp_video_{set_id}.mp4")
        try:
            download_video(video_info['id'], temp_video_path)
            output_video_path = os.path.join(OUTPUT_DIR, f"video_SET_{set_id}_{video_info['name']}")
            process_video(temp_video_path, texts, output_video_path)
            print(f"Completed processing SET {set_id}")
        except Exception as e:
            print(f"Error processing SET {set_id}: {str(e)}")
        finally:
            if os.path.exists(temp_video_path):
                try:
                    os.remove(temp_video_path)
                except Exception as e:
                    print(f"Error deleting temp file: {e}")

    print("\nAll videos have been processed.")

if __name__ == "__main__":
    os.environ["PYTHONUTF8"] = "1"
    os.environ["PYTHONIOENCODING"] = "utf-8"
    os.environ["LC_CTYPE"] = "en_US.UTF-8"
    main()