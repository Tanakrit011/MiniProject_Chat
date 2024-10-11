from flask import Flask, request, jsonify
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import TextSendMessage, QuickReply, QuickReplyButton, MessageAction
import requests
import json
import re
from bs4 import BeautifulSoup
from neo4j import GraphDatabase

app = Flask(__name__)

# Neo4j Database connection details
URI = "bolt://localhost:7687"
AUTH = ("neo4j", "test")

# LINE API access details
with open('username_line1.txt', 'r') as file:
    lines = file.readlines()
    channel_access_token = lines[0].strip()
    channel_secret = lines[1].strip()

line_bot_api = LineBotApi(channel_access_token)
handler = WebhookHandler(channel_secret)

# Cache to store menu items
menu_items_cache = []

# ---- Function to fetch menu items from the website ----
def fetch_menu_items():
    url = "https://mixue.asia/"
    try:
        response = requests.get(url)
        response.raise_for_status()  # Raise an error for bad responses
        soup = BeautifulSoup(response.text, 'html.parser')
        menu_items = [h3.text.strip() for h3 in soup.find_all('h3', class_='elementor-image-box-title')]
        return menu_items
    except Exception:
        return None  # Return None if there's an error fetching the menu

# ---- Function to fetch menu price ----
def fetch_menu_price(menu_name):
    url = "https://mixue.asia/"
    try:
        response = requests.get(url)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        
        for item in soup.find_all('div', class_='elementor-image-box-content'):
            item_name = item.find('h3', class_='elementor-image-box-title').text.strip()
            if menu_name in item_name:
                price_match = re.search(r"\((\d+k)\)", item_name)  # Find price in parentheses
                if price_match:
                    return price_match.group(1)  # Return the price found in parentheses
                else:
                    return "ไม่พบข้อมูลราคาเมนูนี้"
        
        return "ไม่พบข้อมูลเมนูนี้"
    
    except Exception as e:
        return f"เกิดข้อผิดพลาดในการดึงข้อมูลราคา: {e}"

# ---- Function to fetch menu details ----
def fetch_menu_details(menu_name):
    url = "https://mixue.asia/"
    try:
        response = requests.get(url)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        
        for item in soup.find_all('div', class_='elementor-image-box-content'):
            item_name = item.find('h3', class_='elementor-image-box-title').text.strip()
            if menu_name in item_name:
                details = item.find('p', class_='elementor-image-box-description').text.strip()
                return details
        
        return "ไม่พบข้อมูลรายละเอียดเมนูนี้"
    
    except Exception as e:
        return f"เกิดข้อผิดพลาดในการดึงข้อมูลรายละเอียด: {e}"

# ---- Function to save user response ----
def save_response(uid, user_msg, response_msg):
    query = '''
    MATCH (u:User {uid: $uid})
    MERGE (ur:UserReply {text: $user_msg})
    MERGE (r:Response {text: $response_msg})
    CREATE (u)-[:user_reply]->(ur)
    CREATE (ur)-[:response]->(r)
    '''
    parameters = {
        'uid': uid,
        'user_msg': user_msg,
        'response_msg': response_msg
    }
    run_query(query, parameters)

# ---- Function to save user name ----
def save_user_name(uid, name):
    query = '''
    MERGE (u:User {uid: $uid})
    SET u.name = $name
    '''
    parameters = {
        'uid': uid,
        'name': name
    }
    run_query(query, parameters)

# ---- Function to get user name ----
def get_user_name(uid):
    query = '''
    MATCH (u:User {uid: $uid})
    RETURN u.name AS name
    '''
    parameters = {
        'uid': uid
    }
    result = run_query(query, parameters)
    if result and len(result) > 0:
        return result[0].get('name')
    return None

# ---- Neo4j query execution function ----
def run_query(query, parameters=None):
    try:
        with GraphDatabase.driver(URI, auth=AUTH) as driver:
            with driver.session() as session:
                result = session.run(query, parameters)
                return [record for record in result]
    except Exception:
        return None

# ---- Function to get response from Ollama3 ----
def get_llama_response(prompt):
    OLLAMA_API_URL = "http://localhost:11434/api/generate"
    headers = {
        "Content-Type": "application/json"
    }
    
    role_prompt = f"ผู้ตอบเป็นผู้ช่วยเจ้าของธุรกิจ เรียบเรียงประโยคสั้นๆ: {prompt}"
    
    payload = {
        "model": "supachai/llama-3-typhoon-v1.5",
        "prompt": role_prompt,
        "stream": False
    }
    
    response = requests.post(OLLAMA_API_URL, headers=headers, data=json.dumps(payload))
    
    if response.status_code == 200:
        response_data = response.text
        data = json.loads(response_data)
        return data.get("response", "ขอโทษด้วย ฉันไม่สามารถให้คำตอบนี้ได้")
    else:
        print(f"Failed to get a response: {response.status_code}, {response.text}")
        return "ขอโทษด้วย ฉันไม่สามารถให้คำตอบนี้ได้"

# ---- Quick Reply Function ----
def quick_reply_menu(line_bot_api, tk, user_id, offset=0):
    global menu_items_cache
    menu_items_cache = fetch_menu_items()  # Fetch and cache menu items
    if menu_items_cache:
        truncated_menu_items = [item[:20] for item in menu_items_cache[offset:offset + 10]]
        
        quick_reply_buttons = [
            QuickReplyButton(action=MessageAction(label=truncated_item, text=full_item))
            for truncated_item, full_item in zip(truncated_menu_items, menu_items_cache[offset:offset + 10])
        ]
        
        if len(menu_items_cache) > offset + 10:
            quick_reply_buttons.append(
                QuickReplyButton(action=MessageAction(label="ดูเมนูเพิ่มเติม", text=f"ดูเมนูเพิ่มเติม {offset + 10}"))
            )
        
        quick_reply = QuickReply(items=quick_reply_buttons)
        line_bot_api.reply_message(tk, TextSendMessage(text="เลือกเมนูที่ต้องการ", quick_reply=quick_reply))
    else:
        line_bot_api.reply_message(tk, TextSendMessage(text="ไม่สามารถดึงเมนูได้ในขณะนี้"))

# Global user states dictionary
user_states = {}

@app.route("/", methods=['POST'])
def linebot():
    body = request.get_data(as_text=True)

    try:
        json_data = json.loads(body)
        signature = request.headers['X-Line-Signature']
        handler.handle(body, signature)

        msg = json_data['events'][0]['message']['text']
        tk = json_data['events'][0]['replyToken']
        uid = json_data['events'][0]['source']['userId']

        # Check for quick reply menu request
        if msg in ["เมนู", "menu", "Menu"]:
            quick_reply_menu(line_bot_api, tk, uid)

        elif msg.startswith("ดูเมนูเพิ่มเติม"):
            offset = int(msg.split()[1]) if len(msg.split()) > 1 else 0
            quick_reply_menu(line_bot_api, tk, uid, offset)

        # Check for menu item selection
        elif msg in menu_items_cache:
            user_states[uid] = msg
            quick_reply_buttons = [
                QuickReplyButton(action=MessageAction(label="ราคา", text=f"ถามราคา {msg}")),
                QuickReplyButton(action=MessageAction(label="รายละเอียด", text=f"ถามรายละเอียด {msg}")),
                QuickReplyButton(action=MessageAction(label="ราคา(Ollama)", text=f"ถามราคาโดยใช้ Ollama {msg}")),
                QuickReplyButton(action=MessageAction(label="รายละเอียด(Ollama)", text=f"ถามรายละเอียดโดยใช้ Ollama {msg}"))
            ]
            quick_reply = QuickReply(items=quick_reply_buttons)
            line_bot_api.reply_message(tk, TextSendMessage(text="คุณต้องการถามอะไรเกี่ยวกับเมนูนี้?", quick_reply=quick_reply))

        # Handle asking for menu price
        elif msg.startswith("ถามราคา "):
            menu_name = msg.replace("ถามราคา ", "")
            price = fetch_menu_price(menu_name)
            response_msg = f"ราคาเมนู {menu_name} คือ {price}"
            save_response(uid, msg, response_msg)
            line_bot_api.reply_message(tk, TextSendMessage(text=response_msg))

        # Handle asking for menu details
        elif msg.startswith("ถามรายละเอียด "):
            menu_name = msg.replace("ถามรายละเอียด ", "")
            details = fetch_menu_details(menu_name)
            response_msg = f"รายละเอียดเมนู {menu_name}: {details}"
            save_response(uid, msg, response_msg)
            line_bot_api.reply_message(tk, TextSendMessage(text=response_msg))

        # Handle asking for price using Ollama
        elif msg.startswith("ถามราคาโดยใช้ Ollama "):
            menu_name = msg.replace("ถามราคาโดยใช้ Ollama ", "")
            price = fetch_menu_price(menu_name)
            response_msg = f"ราคาเมนู {menu_name} คือ {price}"
            response = get_llama_response(response_msg)  # Use Llama for response
            save_response(uid, msg, response)  # Save user message and response
            line_bot_api.reply_message(tk, TextSendMessage(text=response))

        # Handle asking for details using Ollama
        elif msg.startswith("ถามรายละเอียดโดยใช้ Ollama "):
            menu_name = msg.replace("ถามรายละเอียดโดยใช้ Ollama ", "")
            details = fetch_menu_details(menu_name)
            response_msg = f"รายละเอียดเมนู {menu_name}: {details}"
            response = get_llama_response(response_msg)  # Use Llama for response
            save_response(uid, msg, response)  # Save user message and response
            line_bot_api.reply_message(tk, TextSendMessage(text=response))

        # User name handling
        elif msg.startswith("สวัสดี"):
            name = None
            # ตรวจหาคำว่า "ชื่อ" ในข้อความเพื่อนำชื่อผู้ใช้
            if "ชื่อ" in msg:
                name = msg.split("ชื่อ")[-1].strip()  # แยกข้อความหลังคำว่า "ชื่อ"
            
            if name:
                save_user_name(uid, name)
                line_bot_api.reply_message(tk, TextSendMessage(text=f"สวัสดี {name} ยินดีต้อนรับ!"))
            else:
                user_name = get_user_name(uid)
                if user_name:
                    line_bot_api.reply_message(tk, TextSendMessage(text=f"สวัสดี {user_name} ยินดีต้อนรับ!"))
                else:
                    line_bot_api.reply_message(tk, TextSendMessage(text="สวัสดี! ยินดีต้อนรับ! กรุณาบอกชื่อของคุณ."))

        elif msg.startswith("คุณมีหน้าที่อะไร"):
            line_bot_api.reply_message(tk, TextSendMessage(text="ฉันเป็นแชทบอทที่จะมาตอบคำถามกับคูณ เกี่ยวกับข้อมูลการซื้อแฟรนไชส์ Mixue โดยข้อมูลทั้งหมดนี้อ้างอิงมาจาก https://mixue.asia/ หากคุณมีคำถามอะไรสามารถพิมพ์ 'เมนู' แล้วถามฉันได้เลย."))


        elif msg.startswith("แนะนำ") or msg.startswith("วิธีใช้"):
            line_bot_api.reply_message(tk, TextSendMessage(text="เพียงแค่คุณพิมพ์คำว่า 'เมนู' ก็จะมีตัวเลือก Qucik Reply สำหรับให้คุณเลือก แล้วฉันก็พร้อมจะตอบคำถามของคุณ."))

        # Handle unrecognized input
        else:
            line_bot_api.reply_message(tk, TextSendMessage(text="ขอโทษ ไม่เข้าใจคำสั่งของคุณ."))

    except InvalidSignatureError:
        return jsonify({'status': 'error', 'message': 'Invalid signature'}), 400
    except Exception as e:
        print(f"Error occurred: {e}")

    return jsonify({'status': 'OK'})

if __name__ == "__main__":
    app.run(port=5000)
