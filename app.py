import discord
from discord.ext import commands
import os
import re
import asyncio
from flask import Flask
from threading import Thread

# --- Flask Web Server (用于保活) ---
# 创建一个 Flask 应用实例
app = Flask('')

# 定义一个路由，这是保活网站要访问的地址
@app.route('/')
def home():
    return "I'm alive!"

# 定义一个函数来运行 Flask 服务器
def run_flask():
    # Render 会通过 PORT 环境变量告诉我们用哪个端口
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

STAFF_ROLE_NAME = "管理" 
VERIFIED_ROLE_NAME = "已审核"
PENDING_ROLE_NAME = "待审核"
TICKET_CHANNEL_PREFIX = "ticket-" 
LOG_CHANNEL_ID = 1396366170386464768 
ARCHIVE_CATEGORY_ID = 1386933518034141256

KICK_KEYWORD = "请离"


SPECIAL_TOP_CHANNEL_ID = 1402101438334631967
SPECIAL_TOP_URL = "https://discord.com/channels/1338365085072101416/1402101438334631967/1402102653952987179"

VERIFY_KEYWORDS_PATTERN = re.compile(
    r"已审核|审核通过|审核已通过|审核结束|结束审核|通过审核|审核已结束|完成审核|审核已完成|审核过了"
)

class DeleteTicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="删除该频道", style=discord.ButtonStyle.secondary, custom_id="delete_ticket_confirm")
    async def delete_button_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        ticket_creator = None
        async for old_message in interaction.channel.history(limit=10, oldest_first=True):
            if old_message.author.bot and old_message.mentions:
                ticket_creator = old_message.mentions[0]
                break

        if ticket_creator:
            final_message = f"🎉恭喜{ticket_creator.mention}已通过审核，请阅读并遵守吃饭须知，此频道即将被删除"
            await interaction.response.send_message(final_message)
        else:
            await interaction.response.send_message("此频道即将被删除。")
        
        await asyncio.sleep(5)
        await interaction.channel.delete()

# --- Bot 事件 ---
@bot.event
async def on_ready():
    print(f'机器人已登录，用户名为: {bot.user}')
    bot.add_view(DeleteTicketView())
    try:
        synced = await bot.tree.sync()
        print(f"成功同步 {len(synced)} 条斜杠命令。")
    except Exception as e:
        print(f"同步命令时发生错误: {e}")

# --- 斜杠命令 ---
@bot.tree.command(name="回顶", description="回到当前帖子或讨论串的顶部")
async def top(interaction: discord.Interaction):
    # 1. 检查是否为特殊频道
    if interaction.channel.id == SPECIAL_TOP_CHANNEL_ID:
        view = discord.ui.View()
        button = discord.ui.Button(label="回到指定顶楼", style=discord.ButtonStyle.link, url=SPECIAL_TOP_URL)
        view.add_item(button)
        await interaction.response.send_message("点击下面的按钮回到本频道的指定顶楼：", view=view, ephemeral=True)
    
    # 2. 如果不是特殊频道，再检查是否为帖子或讨论串
    elif isinstance(interaction.channel, discord.Thread):
        thread_url = f"https://discord.com/channels/{interaction.guild.id}/{interaction.channel.id}/{interaction.channel.id}"
        view = discord.ui.View()
        button = discord.ui.Button(label="回到顶楼", style=discord.ButtonStyle.link, url=thread_url)
        view.add_item(button)
        await interaction.response.send_message("点击下面的按钮回到这个帖子的最上方：", view=view, ephemeral=True)
    
    # 3. 如果都不是，则发送提示
    else:
        await interaction.response.send_message("这个命令只能在帖子、讨论串里使用哦！", ephemeral=True)

# --- 消息监听与审核逻辑 ---
@bot.event
async def on_message(message):
    if message.author.bot or not message.guild:
        return

    if not message.channel.name.startswith(TICKET_CHANNEL_PREFIX):
        return
        
    staff_role = discord.utils.get(message.guild.roles, name=STAFF_ROLE_NAME)
    if not staff_role or staff_role not in message.author.roles:
        return

    if VERIFY_KEYWORDS_PATTERN.search(message.content):
        try:
            ticket_creator = None
            async for old_message in message.channel.history(limit=10, oldest_first=True):
                if old_message.author.bot and old_message.mentions:
                    ticket_creator = old_message.mentions[0]
                    break 

            if not ticket_creator:
                await message.channel.send("❌ 错误：无法在此工单中自动识别开票人。")
                return

            verified_role = discord.utils.get(message.guild.roles, name=VERIFIED_ROLE_NAME)
            pending_role = discord.utils.get(message.guild.roles, name=PENDING_ROLE_NAME)
            if not verified_role:
                await message.channel.send(f"❌ 错误：找不到 `{VERIFIED_ROLE_NAME}` 身份组！")
                return
            
            await ticket_creator.add_roles(verified_role)
            if pending_role and pending_role in ticket_creator.roles:
                await ticket_creator.remove_roles(pending_role)

            archive_category = message.guild.get_channel(ARCHIVE_CATEGORY_ID)
            if archive_category and isinstance(archive_category, discord.CategoryChannel):
                new_name = message.channel.name.replace('ticket-', 'closed-', 1)
                await message.channel.edit(name=new_name, category=archive_category)
            else:
                await message.channel.send(f"⚠️ **管理员请注意**: 未能找到归档类别，频道未移动。")

            await message.channel.send(f"✅ 用户 {ticket_creator.mention} 已审核通过。")
            await message.channel.send("请点击下方的按钮删除此工单：", view=DeleteTicketView())

            log_channel = bot.get_channel(LOG_CHANNEL_ID)
            if log_channel:
                ticket_number = message.channel.name.split('-')[-1]
                admin_user = message.author
                log_msg = f"工单 `ticket-{ticket_number}`: 管理员 **{admin_user.display_name}** 审核了用户 {ticket_creator.mention} ({ticket_creator})。"
                await log_channel.send(log_msg)
            else:
                print(f"错误：找不到ID为 {LOG_CHANNEL_ID} 的日志频道。")
                await message.channel.send(f"⚠️ **管理员请注意**: 未能找到日志频道，本次操作未记录。")
        except Exception as e:
            await message.channel.send(f"执行审核操作时发生未知错误: {e}")


    elif message.content == KICK_KEYWORD:
        try:
            # 查找开票人
            ticket_creator = None
            async for old_message in message.channel.history(limit=10, oldest_first=True):
                if old_message.author.bot and old_message.mentions:
                    ticket_creator = old_message.mentions[0]
                    break 

            if not ticket_creator:
                await message.channel.send("❌ 错误：无法在此工单中自动识别开票人。")
                return

            admin_user = message.author
            kick_reason = f"由管理员 {admin_user.display_name} 在工单频道 {message.channel.name} 中操作"
            
            # 执行踢人操作
            await ticket_creator.kick(reason=kick_reason)
            
            # 发送频道内通知
            await message.channel.send(f"✅ 操作成功！用户 {ticket_creator.mention} 已被踢出服务器。")
            
            # 发送日志
            log_channel = bot.get_channel(LOG_CHANNEL_ID)
            if log_channel:
                ticket_number = message.channel.name.split('-')[-1]
                log_msg = f"工单 `ticket-{ticket_number}`: 管理员 **{admin_user.display_name}** 已将用户 {ticket_creator.mention} ({ticket_creator}) **踢出服务器**。"
                await log_channel.send(log_msg)

            await message.channel.delete()

        except discord.Forbidden:
            await message.channel.send(f"❌ 权限错误！请确保机器人拥有 **踢出成员** 的权限，并且其身份组层级高于目标用户。")
        except Exception as e:
            await message.channel.send(f"发生未知错误: {e}")


# --- 运行 Bot ---
if __name__ == "__main__":
    # 创建并启动 Flask 服务器线程
    # 这样 Flask 服务器就不会阻塞我们的机器人运行
    flask_thread = Thread(target=run_flask)
    flask_thread.start()

    # 运行机器人
    bot_token = os.getenv("DISCORD_TOKEN")
    if bot_token is None:
        print("错误：未找到 DISCORD_TOKEN。")
    else:
        bot.run(bot_token)