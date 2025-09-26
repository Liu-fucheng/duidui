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
SUGGESTION_CATEGORY_ID = 1421113336149577808

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

# --- 48小时未创建工单且未审核 自动踢出逻辑 ---
CHECK_DELAY_SECONDS = 48 * 60 * 60
_member_check_tasks = {}

async def _member_has_ticket(guild: discord.Guild, member: discord.Member) -> bool:
    """只有当成员在其ticket频道中实际发过消息时才视为有工单。"""
    for channel in guild.text_channels:
        try:
            if not channel.name.startswith(TICKET_CHANNEL_PREFIX):
                continue
            # 查找工单开头的机器人提示并识别被@的开票人
            is_owner = False
            async for old_message in channel.history(limit=10, oldest_first=True):
                if old_message.author.bot and old_message.mentions:
                    ticket_owner = old_message.mentions[0]
                    if ticket_owner.id == member.id:
                        is_owner = True
                    break
            if not is_owner:
                continue

            # 必须成员自己在该频道发过至少一条消息，才算有效工单
            async for m in channel.history(limit=200, oldest_first=True):
                if m.author and not m.author.bot and m.author.id == member.id:
                    return True
            # 没有成员消息则视为未有效创建工单
        except Exception:
            continue
    return False

async def _kick_if_still_unverified_and_no_ticket(member: discord.Member):
    guild = member.guild
    if guild is None:
        return
    try:
        # 重新获取对象，避免缓存造成信息不准
        member = await guild.fetch_member(member.id)
    except Exception:
        return

    verified_role = discord.utils.get(guild.roles, name=VERIFIED_ROLE_NAME)
    pending_role = discord.utils.get(guild.roles, name=PENDING_ROLE_NAME)

    # 已离开、已审核、或没有待审核角色，均不处理
    if verified_role and verified_role in member.roles:
        return
    if pending_role is None or pending_role not in member.roles:
        return

    # 已经创建过工单则不处理
    if await _member_has_ticket(guild, member):
        return

    # 私信说明并踢出
    try:
        dm_text = (
            "您有一封来自堆堆demo的信：\n\n"
            "我们非常遗憾地告知您，由于您进入堆堆demo 48h后仍然没有进行审核，出于对服务器发展的考虑（防止男性混入），您已被请离该服务器。\n"
            "如果您只是没有及时查看消息、上传证明，或者刚搭建酒馆，聊天楼层数较少，我们欢迎您满足要求后随时加入服务器。\n"
            "以下为本服务器的永久邀请链接：https://discord.com/invite/gtU8UCa22F"
        )
        try:
            await member.send(dm_text)
        except Exception:
            pass
        await member.kick(reason="加入48小时未创建工单且仍为待审核")

        log_channel = bot.get_channel(LOG_CHANNEL_ID)
        if log_channel:
            await log_channel.send(f"已踢出成员 {member.mention} ({member})：48小时未审核且未创建工单。")
    except discord.Forbidden:
        log_channel = bot.get_channel(LOG_CHANNEL_ID)
        if log_channel:
            await log_channel.send(f"⚠️ 权限不足：无法踢出 {member.mention}（需要踢出成员权限且身份层级足够）。")
    except Exception as e:
        log_channel = bot.get_channel(LOG_CHANNEL_ID)
        if log_channel:
            await log_channel.send(f"处理成员 {member.mention} 时发生错误：{e}")

async def _schedule_member_check(member: discord.Member, delay_seconds: int):
    # 防重复调度
    key = (member.guild.id, member.id)
    if key in _member_check_tasks and not _member_check_tasks[key].done():
        return

    async def _runner():
        try:
            await asyncio.sleep(max(0, delay_seconds))
            await _kick_if_still_unverified_and_no_ticket(member)
        finally:
            _member_check_tasks.pop(key, None)

    task = asyncio.create_task(_runner())
    _member_check_tasks[key] = task

# --- Bot 事件 ---
@bot.event
async def on_ready():
    print(f'机器人已登录，用户名为: {bot.user}')
    bot.add_view(DeleteTicketView())
    bot.add_view(SuggestionView())
    try:
        synced = await bot.tree.sync()
        print(f"成功同步 {len(synced)} 条斜杠命令。")
    except Exception as e:
        print(f"同步命令时发生错误: {e}")

    # 启动时对现有成员做一次排查与调度
    try:
        for guild in bot.guilds:
            pending_role = discord.utils.get(guild.roles, name=PENDING_ROLE_NAME)
            if pending_role is None:
                continue
            for member in guild.members:
                if pending_role not in member.roles:
                    continue
                # 已审核跳过
                verified_role = discord.utils.get(guild.roles, name=VERIFIED_ROLE_NAME)
                if verified_role and verified_role in member.roles:
                    continue
                # 计算已加入时长
                if member.joined_at is None:
                    continue
                # Discord 的 joined_at 是UTC时间
                now = discord.utils.utcnow()
                elapsed = (now - member.joined_at).total_seconds()
                if elapsed >= CHECK_DELAY_SECONDS:
                    await _schedule_member_check(member, 0)
                else:
                    await _schedule_member_check(member, int(CHECK_DELAY_SECONDS - elapsed))
    except Exception as e:
        print(f"启动检查时发生错误: {e}")

# --- 建议提交按钮视图 ---
class SuggestionView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="提交建议", style=discord.ButtonStyle.primary, custom_id="submit_suggestion")
    async def submit_suggestion_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            # 获取建议分类
            suggestion_category = interaction.guild.get_channel(SUGGESTION_CATEGORY_ID)
            if not suggestion_category:
                await interaction.response.send_message("❌ 错误：找不到建议分类！", ephemeral=True)
                return
            
            # 计算下一个建议编号
            existing_suggestions = [ch for ch in suggestion_category.channels if ch.name.startswith("建议-")]
            next_number = len(existing_suggestions) + 1
            channel_name = f"建议-{next_number:04d}"
            
            # 获取管理组角色
            staff_role = discord.utils.get(interaction.guild.roles, name=STAFF_ROLE_NAME)
            if not staff_role:
                await interaction.response.send_message("❌ 错误：找不到管理组角色！", ephemeral=True)
                return
            
            # 创建私密频道
            overwrites = {
                interaction.guild.default_role: discord.PermissionOverwrite(read_messages=False),
                interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
                staff_role: discord.PermissionOverwrite(read_messages=True, send_messages=True),
                interaction.guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
            }
            
            suggestion_channel = await interaction.guild.create_text_channel(
                name=channel_name,
                category=suggestion_category,
                overwrites=overwrites,
                reason=f"用户 {interaction.user} 提交建议"
            )
            
            # 发送欢迎消息
            welcome_message = f"{interaction.user.mention} 您好！这是只有您与管理能看到的私密频道。非常感谢您对堆堆demo的建言献策！您对社区建设有任何的意见或者建议都可以在这个频道内直接表达，管理在上线后会赶到与您进行讨论。{staff_role.mention}"
            await suggestion_channel.send(welcome_message)
            
            # 回复用户
            await interaction.response.send_message(f"✅ 建议频道已创建，点击此链接跳转：{suggestion_channel.mention}", ephemeral=True)
            
            # 记录日志
            log_channel = bot.get_channel(LOG_CHANNEL_ID)
            if log_channel:
                await log_channel.send(f"{interaction.user.mention} 创建了建议频道：{suggestion_channel.mention}")
                
        except Exception as e:
            await interaction.response.send_message(f"❌ 创建建议频道时发生错误：{e}", ephemeral=True)

# --- 斜杠命令 ---
@bot.tree.command(name="公告", description="发送公告消息和建议提交按钮")
async def announcement(interaction: discord.Interaction, 内容: str):
    """发送公告并添加建议提交按钮"""
    try:
        # 检查权限
        staff_role = discord.utils.get(interaction.guild.roles, name=STAFF_ROLE_NAME)
        if not staff_role or staff_role not in interaction.user.roles:
            await interaction.response.send_message("❌ 权限不足：只有管理组可以使用此命令！", ephemeral=True)
            return
        
        # 创建建议提交按钮
        view = SuggestionView()
        
        # 发送公告
        announcement_text = f"{内容}\n\n如果您对社区的建设有任何意见或者建议，请点击下方按钮进行提交⬇️"
        
        await interaction.response.send_message(announcement_text, view=view)
        
        # 记录日志
        log_channel = bot.get_channel(LOG_CHANNEL_ID)
        if log_channel:
            await log_channel.send(f"{interaction.user.mention} 发布了公告")
            
    except Exception as e:
        await interaction.response.send_message(f"❌ 发送公告时发生错误：{e}", ephemeral=True)

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

@bot.event
async def on_member_join(member: discord.Member):
    try:
        # 对新成员设置48小时检查
        await _schedule_member_check(member, CHECK_DELAY_SECONDS)
    except Exception as e:
        print(f"为新成员调度检查时发生错误: {e}")

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
