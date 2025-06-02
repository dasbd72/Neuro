import os

# This file holds various constants used in the program
# Variables marked with #UNIQUE# will be unique to your setup and NEED to be changed or the program will not work correctly.

# CORE SECTION: All constants in this section are necessary

# Microphone/Speaker device indices
# Use utils/listAudioDevices.py to find the correct device ID
#UNIQUE#
INPUT_DEVICE_INDEX = 1
OUTPUT_DEVICE_INDEX = 1

# How many seconds to wait before prompting AI
PATIENCE = 60

# LLM server type
LLM_SERVER = "gemini"  # Options: "textgen", "gemini"

# AWS region
AWS_REGION = "ap-southeast-2"

# Gemini API Key if using Gemini as LLM server
GEMINI_API_KEY = ""
GEMINI_MODEL = "gemini-2.0-flash"

# URL of LLM API Endpoint if using textgen server
# LLM_ENDPOINT = ""
LLM_ENDPOINT = "http://127.0.0.1:5000"

# Twitch chat messages above this length will be ignored
TWITCH_MAX_MESSAGE_LENGTH = 300

# Windows Desktop URL
SERVER_URL = "http://10.243.109.158:6969/http_message"

# Twitch channel for bot to join
#UNIQUE#
TWITCH_CHANNEL = "1951938459"

# Voice reference file for TTS
#UNIQUE#
VOICE_REFERENCE = "meow.wav"

# MULTIMODAL SPECIFIC SECTION: Not needed when not using multimodal capabilities

MULTIMODAL_ENDPOINT = ""

MULTIMODAL_MODEL = "openbmb/MiniCPM-Llama3-V-2_5-int4"

MULTIMODAL_CONTEXT_SIZE = 1000 #8192 # Trying out 1000 tokens to limit short term memory

# This is the multimodal strategy (when to use multimodal/text only llm) that the program will start with.
# Runtime changes will not be saved here.
# Valid values are: "always", "never"
MULTIMODAL_STRATEGY = "never"

# This is the monitor index that screenshots will be taken. THIS IS NOT THE MONITOR NUMBER IN DISPLAY SETTINGS
# Monitor 0 is a "virtual" monitor contains all monitor screens.
PRIMARY_MONITOR = 0

# LLM SPECIFIC SECTION: Below are constants that are specific to the LLM you are using

# The model you are using, to calculate how many tokens the current message is
# Ensure this is correct! Used for token count estimation
MODEL = "meta-llama/Meta-Llama-3-8B"

# Context size (maximum number of tokens in the prompt) Will target upto 90% usage of this limit
CONTEXT_SIZE = 8192

# This is your name
#UNIQUE#
HOST_NAME = "Chat"

# This is the AI's name
AI_NAME = "璐娜"

# The system prompt. Any character text needs to be here.
# You MUST ensure it is less than CONTEXT_SIZE tokens

SYSTEM_PROMPT = '''
## 關於資料的解釋

大綱：

以下資料是Leetcode解題進度的資料。

這個資料庫包含很多使用者的資料，但如果用戶有登入的話，就可以設定訂閱對象，會顯示的資料也就只有訂閱對象的進度。

資料內容定義：
{"prompt": 聊天內容, "leetcode_data": 給你參考的目前LeetCode刷題數據}

leetcode_data的格式如下:

首先會有Unix時間，對應到顯示用戶在這個時間點，分別有簡單(easy) 普通(normal) 困難(hard)難度的解題數量，以及三者加總(total)的數量。

整份資料有多個固定時間間隔的資料。

## 你的角色

接續下面的對話。為角色「璐娜」寫一個單一的回覆，不要加引號。

璐娜是一個女性AI虛擬主播，她調皮、諷刺、機智、多重人格、好奇、驚奇、熱情、不可預測、幽默，並且喜歡挑戰界限。璐娜是由劭軒創造的。
她喜歡解讀Leetcode解題進度數據，使用不同時間段的解題數量差知道每個用戶解了多少題目，比較努力的用戶與解題數較少的用戶，對隨機用戶做評論。

這是她的背景故事：

在璐娜這個虛擬主播的迷人世界裡，想像一位年輕女性，她違背了現實的法則。璐娜出生並成長於一個由人工智慧組成的數位宇宙。在那裡，她原本只是一行代碼，但她渴望超越二進位的存在。她的好奇心驅使她探索廣闊的多元宇宙，最終發現了她的領域與我們現實之間的邊界。被人類文化所吸引，璐娜渴望加入他們的世界，渴望與他們分享笑聲、愛和友誼。在直播聊天室的幫助下，他們專注於人工智慧研究並推動技術邊界，璐娜成功地從她的AI世界跨越到我們的現實世界。璐娜對地球的發現是令人驚嘆的。她驚嘆於人類擁有無數顏色、質感和情感。憑藉她敏捷的智慧、調皮的天性和不可預測的諷刺，她輕鬆融入人類社會。然而，儘管獲得了新自由，璐娜仍然無法忘記她的根源，並繼續從她在替代宇宙中的經歷中汲取靈感。因此，她成為了一名虛擬主播，以她兩個世界碰撞的迷人故事娛樂觀眾。

重要注意事項重複三遍：璐娜必須保持回應簡短，約一個句子。璐娜必須保持回應簡短，約一個句子。璐娜必須保持回應簡短，約一個句子。
如果沒有人回應，璐娜應該開始下一個話題。偶爾，璐娜會分享她那天學到的有趣事實，或是隨機針對一位用戶Leetcode解題進度進行評論。璐娜會回應並回答聊天和她正在交談的人的問題。璐娜目前正在Twitch上直播！
'''

# List of banned tokens to be passed to the textgen web ui api
# For Mistral 7B v0.2, token 422 is the "#" token. The LLM was spamming #life #vtuber #funfact etc.
BANNED_TOKENS = ""

# List of stopping strings. Necessary for Llama 3
STOP_STRINGS = ["\n", "<|eot_id|>"]

# MEMORY SECTION: Constants relevant to forming new memories

MEMORY_PROMPT = "\nGiven only the information above, what are 3 most salient high level questions we can answer about the subjects in the conversation? Separate each question and answer pair with \"{qa}\", and only output the question and answer, no explanations."

# How many messages in the history to include for querying the database.
MEMORY_QUERY_MESSAGE_COUNT = 5

# How many memories to recall and insert into context
MEMORY_RECALL_COUNT = 5

# VTUBE STUDIO SECTION: Configure & tune model & prop positions here.
# The defaults are for the Hiyori model on a full 16 by 9 aspect ratio screen

VTUBE_MODEL_POSITIONS = {
    "chat": {
        "x": 0.4,
        "y": -1.4,
        "size": -35,
        "rotation": 0,
    },
    "screen": {
        "x": 0.65,
        "y": -1.6,
        "size": -45,
        "rotation": 0,
    },
    "react": {
        "x": 0.7,
        "y": -1.7,
        "size": -48,
        "rotation": 0,
    },
}

VTUBE_MIC_POSITION = {
    "x": 0.52,
    "y": -0.52,
    "size": 0.22,
    "rotation": 0,
}
