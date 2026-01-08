import discord
import gspread
import re
import os
from dotenv import load_dotenv
from oauth2client.service_account import ServiceAccountCredentials
from datetime import timedelta 

# --- 1. 配置区域 ---
SHEET_ID = "1Ce5k2Blbf5MYXbM4rSTeWHOf2uTHPrvZX6vm6Cdyc5Q" 
JSON_KEYFILE = 'credentials.json'
#COMMANDS_CHANNEL_ID = 1446237650473189460
load_dotenv('DISCORD_BOT_TOKEN.env')

# 读取 Token
BOT_TOKEN = os.getenv('DISCORD_BOT_TOKEN')

if BOT_TOKEN is None:
    print("错误：未找到 Token")
else:
    print("Token 读取成功，准备启动...")

# 两个工作表的名字
SHEET_GamesPt = "Games/pt"   
SHEET_Games_Riichi = "Games Riichi" 

# --- 2. 初始化 ---
intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
client = discord.Client(intents=intents)

print("正在连接 Google Cloud...")
scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
try:
    creds = ServiceAccountCredentials.from_json_keyfile_name(JSON_KEYFILE, scope)
    gs_client = gspread.authorize(creds)
    spreadsheet = gs_client.open_by_key(SHEET_ID)
    sheet_date_log = spreadsheet.worksheet(SHEET_GamesPt)
    sheet_content_log = spreadsheet.worksheet(SHEET_Games_Riichi)
    print("✅ 连接成功")
except Exception as e:
    print(f"❌ 连接失败: {e}")

# --- 3. 核心逻辑 ---
@client.event
async def on_ready():
    print(f'🤖 机器人已就绪: {client.user}')

@client.event
async def on_message(message):
    if message.author == client.user:
        return
    #if message.channel.id != COMMANDS_CHANNEL_ID:
        return

    if "00/" in message.content:
        print(f"📥 处理消息: {message.content}")

        try:
            # --- 时间处理 ---
            utc_time = message.created_at
            local_time = utc_time + timedelta(hours=-8) # 西八区
            formatted_time = local_time.strftime('%m/%d/%Y %H:%M')

            # --- 准备数据 ---
            split_parts = message.content.lower().split('/')
            total_score = 0
            for part in split_parts:
    # \d+ 表示匹配连续的数字（不包含小数点）
                match = re.search(r"-?\d+", part) 
                if match:
                # 既然只处理整数，这里用 int()
                    total_score += int(match.group())
        # 3. 校验逻辑
            if total_score != 100000:
                await message.channel.send("Point incorrect, please check and resent")
                return
         
            data_for_sheet1 = [formatted_time]
            data_for_sheet2 = split_parts

            # --- 写入表格 ---
            sheet_date_log.append_row(data_for_sheet1)
            sheet_content_log.append_row(data_for_sheet2)
            
            print(f" -> 记录成功: {formatted_time}")
            
            # --- 反馈给用户 ---
            await message.add_reaction('✅') # 打钩
            await message.channel.send("Game Recorded") # 【新增】发送文字回复

        except Exception as e:
            print(f"❌ 错误: {e}")
            await message.add_reaction('❌')

if __name__ == "__main__":
    client.run(BOT_TOKEN)