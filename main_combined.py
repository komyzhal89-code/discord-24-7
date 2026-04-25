# -*- coding: utf-8 -*-
"""
Combined Discord Bot & Flask Authentication Server
===================================================
- Uses environment variables for sensitive data (TOKEN, GUILD_ID, PORT).
- Keeps the original functionality:
  * /인증 command (DM에 인증 코드 전송)
  * /고유번호변경, /고유번호삭제 관리자 명령
  * Flask `/verify` endpoint for Roblox verification
  * 24시간 가동 (keep‑alive thread)
"""

import os
import json
import random
import string
import threading
from flask import Flask, request, jsonify
import discord
from discord import app_commands
from discord.ext import commands

# ------------------- 설정 -------------------
TOKEN = os.getenv("DISCORD_TOKEN", "YOUR_DISCORD_TOKEN")  # 로컬 테스트용 기본값
GUILD_ID = int(os.getenv("DISCORD_GUILD_ID", "1326498746933972993"))
DATA_FILE = os.getenv("DATA_FILE", "data.json")
UNVERIFIED_ROLE = os.getenv("UNVERIFIED_ROLE", "미인증")
# Flask가 사용할 포트 (클라우드 배포 시 환경변수 PORT 로 자동 지정)
PORT = int(os.getenv("PORT", "8080"))

# ------------------- 데이터베이스 -------------------
def load_data():
    if not os.path.exists(DATA_FILE):
        return {"last_uid": 0, "users": {}, "codes": {}}
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {"last_uid": 0, "users": {}, "codes": {}}

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

# ------------------- Discord Bot -------------------
intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

def generate_code():
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=6))

@bot.event
async def on_ready():
    await tree.sync()
    print(f"{bot.user} 고유번호 봇 실행 완료!")

# 🔑 /인증
@tree.command(name="인증", description="로블록스 연동 인증 코드를 개인 DM으로 발급받습니다.")
async def 인증(interaction: discord.Interaction):
    data = load_data()
    user_id_str = str(interaction.user.id)
    if user_id_str in data["users"]:
        return await interaction.response.send_message("❌ 이미 인증된 계정입니다.", ephemeral=True)
    code = generate_code()
    data["codes"][code] = user_id_str
    save_data(data)
    try:
        await interaction.user.send(
            f"✅ **인증 안내**\n"
            f"로블록스 인증 센터(https://www.roblox.com/ko/games/123167227935181/DBS) 에 접속하여 아래 코드를 입력해주세요:\n\n"
            f"🔑 **인증 코드:** `{code}`"
        )
        await interaction.response.send_message("✅ 개인 DM으로 인증 코드를 전송했습니다! DM을 확인해주세요.", ephemeral=True)
    except discord.Forbidden:
        await interaction.response.send_message(
            "❌ DM을 보낼 수 없습니다. 서버 개인정보 보호 설정에서 '서버 멤버가 보내는 다이렉트 메시지 허용'을 켜주세요.",
            ephemeral=True,
        )

# 🛠️ /고유번호변경 (관리자 전용)
@tree.command(name="고유번호변경", description="[관리자] 특정 유저의 고유번호를 다른 번호로 강제 변경합니다.")
@app_commands.describe(member="변경할 대상", new_uid="새로운 고유번호 (숫자)")
@app_commands.default_permissions(administrator=True)
async def 고유번호변경(interaction: discord.Interaction, member: discord.Member, new_uid: int):
    data = load_data()
    user_id_str = str(member.id)
    if user_id_str not in data["users"]:
        return await interaction.response.send_message("❌ 인증되지 않은 유저입니다.", ephemeral=True)
    # 중복 UID 체크
    for info in data["users"].values():
        if info["uid"] == new_uid:
            return await interaction.response.send_message(f"❌ 이미 다른 유저가 사용 중인 고유번호입니다 ({new_uid}).", ephemeral=True)
    data["users"][user_id_str]["uid"] = new_uid
    save_data(data)
    # 닉네임 업데이트
    info = data["users"][user_id_str]
    nickname = f"{info['uid']}ㆍ{info['job']}ㆍ{info['roblox']}"
    try:
        await member.edit(nick=nickname)
    except Exception as e:
        return await interaction.response.send_message(
            f"✅ 데이터는 저장되었으나 권한 문제로 닉네임을 변경하지 못했습니다. ({e})",
            ephemeral=True,
        )
    await interaction.response.send_message(
        f"✅ {member.mention} 님의 고유번호가 **{new_uid}** 로 변경되었습니다.",
        ephemeral=True,
    )

# 🗑️ /고유번호삭제 (관리자 전용)
@tree.command(name="고유번호삭제", description="[관리자] 특정 유저의 고유번호 및 인증 정보를 초기화합니다.")
@app_commands.describe(member="삭제할 대상")
@app_commands.default_permissions(administrator=True)
async def 고유번호삭제(interaction: discord.Interaction, member: discord.Member):
    data = load_data()
    user_id_str = str(member.id)
    if user_id_str not in data["users"]:
        return await interaction.response.send_message(
            "❌ 인증되지 않은 유저이거나 이미 삭제된 유저입니다.",
            ephemeral=True,
        )
    del data["users"][user_id_str]
    save_data(data)
    # 닉네임 초기화
    try:
        await member.edit(nick=None)
    except discord.Forbidden:
        pass
    # 미인증 역할 재부여
    guild = member.guild
    unverified = discord.utils.get(guild.roles, name=UNVERIFIED_ROLE)
    if unverified:
        try:
            await member.add_roles(unverified)
        except Exception:
            pass
    await interaction.response.send_message(
        f"✅ {member.mention} 님의 고유번호 및 인증 정보가 초기화되었습니다.",
        ephemeral=True,
    )

# ------------------- Flask 서버 -------------------
app = Flask(__name__)
# ---- 포트 정의 (Replit, Docker, Local 등에서 자동 제공) ----
PORT = int(os.getenv("PORT", 8080))

@app.route('/')
def home():
    return "Bot Auth Server Running! (24시간 봇 가동 중)"

# ---- UptimeRobot / Ping 라우트 (5분마다 호출) ----
@app.route('/ping')
def ping():
    return "pong"

@app.route('/verify', methods=['POST'])
def verify():
    try:
        req_data = request.get_json()
        code = req_data.get('code')
        roblox_name = req_data.get('roblox')
        data = load_data()
        if code not in data['codes']:
            return jsonify({"status": "fail", "message": "Invalid code"})
        user_id = data['codes'][code]
        # UID 할당
        data['last_uid'] += 1
        new_uid = data['last_uid']
        # 사용자 정보 저장
        data['users'][user_id] = {"uid": new_uid, "job": "승객", "roblox": roblox_name}
        # 사용된 코드 삭제
        del data['codes'][code]
        save_data(data)
        # 비동기로 디스코드 닉네임/역할 업데이트
        async def process():
            guild = bot.get_guild(GUILD_ID)
            if not guild:
                return
            member = guild.get_member(int(user_id))
            if not member:
                return
            nickname = f"{new_uid}ㆍ승객ㆍ{roblox_name}"
            try:
                await member.edit(nick=nickname)
                # 미인증 역할 제거
                unverified = discord.utils.get(guild.roles, name=UNVERIFIED_ROLE)
                if unverified and unverified in member.roles:
                    await member.remove_roles(unverified)
            except Exception as e:
                print("디코 속성 변경 오류:", e)
        bot.loop.create_task(process())
        return jsonify({"status": "success", "uid": new_uid, "job": "승객"})
    except Exception as e:
        print("서버 오류:", e)
        return jsonify({"status": "error", "message": str(e)})

# ------------------- Keep‑Alive -------------------
def run_flask():
    app.run(host="0.0.0.0", port=PORT)

def keep_alive():
    threading.Thread(target=run_flask, daemon=True).start()

# ------------------- 실행 -------------------
if __name__ == "__main__":
    keep_alive()
    bot.run("MTQ4NDg0NDg5NzMyNzUxNzgwNw.GofBTJ.ldbWm3GoUx65TbiCNtaG1ELYrRI4rf9Nd21IpI")
