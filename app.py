import discord
import os

# 1. 定义意图 (Intents)
# 确保在 Discord 开发者门户中也开启了这些意图
intents = discord.Intents.default()
intents.message_content = True  # 允许读取消息内容
intents.members = True          # 允许访问服务器成员信息

# 2. 创建 Bot 客户端实例
client = discord.Client(intents=intents)

# 3. 定义事件：当 Bot 成功连接到 Discord 时触发
@client.event
async def on_ready():
    """
    当机器人成功启动并登录后，在控制台打印一条消息。
    """
    print(f'机器人已登录，用户名为: {client.user}')

# 4. 定义事件：当收到消息时触发
@client.event
async def on_message(message):
    """
    处理接收到的消息。
    """
    # 防止机器人自己回复自己，造成无限循环
    if message.author == client.user:
        return

    # 检查消息内容是否是 '!hello'
    if message.content.startswith('!hello'):
        # 在收到消息的频道中回复 'Hello!'
        await message.channel.send('Hello!')

# 5. 运行 Bot
# 从 Hugging Face 的 Secrets 中安全地获取 Token
# 这是一个最佳实践，避免将敏感信息硬编码在代码里
try:
    bot_token = os.getenv("DISCORD_TOKEN")
    if bot_token is None:
        print("错误：未找到 DISCORD_TOKEN。请确保已在 Hugging Face Secrets 中设置。")
    else:
        client.run(bot_token)
except Exception as e:
    print(f"启动机器人时发生错误: {e}")