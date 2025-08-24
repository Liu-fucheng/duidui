# 使用官方 Python 镜像作为基础
FROM python:3.9-slim

# 将工作目录设置为 /app
WORKDIR /app

# 复制依赖文件到容器中
COPY requirements.txt .

# 安装依赖
RUN pip install --no-cache-dir -r requirements.txt

# 复制你的应用代码到容器中
COPY . .

# 容器启动时运行的命令
CMD ["python", "app.py"]