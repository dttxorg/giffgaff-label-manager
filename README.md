# Giffgaff SIM 卡到期提醒系统

每 170 天自动发送邮件提醒，共支持 43 个周期（约 20 年）。

---

## 功能总览

- **客户管理**：增删改查，手机号 + 邮箱 + 开通日期
- **到期推算**：自动计算 43 个 170 天周期，存入本地数据库
- **定时发送**：每日 cron 检测到期日，实时调用 Resend 发邮件（防重发）
- **导出备份**：一键导出 JSON，数据迁移无忧
- **云盘备份**：每日自动备份数据库到阿里云盘（rclone）
- **管理界面**：纯 HTML 无依赖，浏览器直接访问

---

## 架构说明

```
添加客户 → 数据库写入 43 个到期日记录（永久保存）
    ↓
每日 cron 任务检测到期记录
    ↓
sent=0 & due_date ≤ 今天 → 实时调用 Resend 发邮件 → 标记 sent=1
    ↓
同日 备份脚本 → rclone 推送 JSON 到阿里云盘
```

**不依赖邮件服务商的预约保留机制**，到期计划存在本地硬盘。

---

## 快速开始

### 1. 配置环境变量

```bash
cd backend
cp .env.example .env
# 填入以下两个变量
```

`.env` 所需变量：

| 变量 | 说明 |
|---|---|
| `RESEND_API_KEY` | Resend API Key（[resend.com](https://resend.com) 注册获取） |
| `FROM_EMAIL` | 已验证的发件邮箱域名（如 `reminder@yourdomain.com`） |

### 2. 安装依赖

```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. 启动 Web 服务

```bash
source venv/bin/activate
uvicorn main:app --host 0.0.0.0 --port 8000
```

访问 `http://你的VPS公网IP:8000`

### 4. 配置定时任务（VPS cron）

```bash
# 编辑 crontab
crontab -e

# 添加：
# 每天 09:00 检测到期邮件并发送
0 9 * * * /path/to/run_daily.sh send >> /path/to/cron.log 2>&1

# 每天 10:00 备份数据库到阿里云盘
0 10 * * * /path/to/run_daily.sh backup >> /path/to/cron.log 2>&1
```

---

## 阿里云盘备份配置（只需一次）

### 第一步：安装 rclone

```bash
# Linux/macOS
curl https://rclone.org/install.sh | sudo bash

# macOS 也可以用 brew
brew install rclone
```

### 第二步：配置阿里云盘 remote

```bash
rclone config
# 选择：
#   n) New remote
#   name: aliyundrive
#   Storage> aliyundrive
#   refresh_token: （见下方获取方式）
#   其他留空默认
```

**获取阿里云盘 refresh_token：**

阿里云盘没有开放的第三方 OAuth，但可以用网页抓取方式：

1. 浏览器登录 [drive.aliyundrive.com](https://drive.aliyundrive.com)
2. 按 F12 打开 DevTools → Application → Local Storage → 找 `token` 或 `refresh_token`
3. 或者用这个脚本获取：
   ```bash
   # 需要 Node.js
   npx --yes aliyundrive-fetch-token
   ```

> 注意：refresh_token 有效期较长（约一个月），失效后需要重新获取。
> 如果阿里云盘官方 API 有变动，请查看 [rclone aliyundrive 文档](https://rclone.org/aliyundrive/)。

### 第三步：测试上传

```bash
# 确认配置正确
rclone lsd aliyundrive:

# 上传测试文件
echo "test" | rclone rcat aliyundrive:/test.txt
```

### 第四步：配置备份脚本

编辑 `backup.sh`，确认 `REMOTE` 变量与 rclone 配置名称一致：

```bash
REMOTE="aliyundrive"
REMOTE_PATH="giffgaff-reminder"
```

---

## 数据导出 / 导入

### 导出

管理界面右上角有「导出」按钮，下载 JSON 文件。

或用 API：

```bash
curl http://localhost:8000/api/export > backup.json
```

### 导入

管理界面上传 JSON 文件即可覆盖恢复。

或用 API：

```bash
curl -X POST http://localhost:8000/api/import \
  -F "file=@backup.json"
```

---

## 目录结构

```
giffgaff-reminder/
├── backend/
│   ├── main.py            # FastAPI 主程序
│   ├── database.py        # SQLite 初始化
│   ├── crud.py            # 数据库操作
│   ├── scheduler.py       # 每日发送检查脚本
│   ├── export_import.py   # 导出导入 API
│   ├── models.py          # Pydantic 数据模型
│   ├── backup.sh          # 阿里云盘备份脚本
│   ├── run_daily.sh       # 每日 cron 主脚本
│   ├── requirements.txt
│   ├── .env.example
│   └── giffgaff.db        # 数据库（自动创建）
├── frontend/
│   └── index.html         # 管理界面（无需构建）
└── README.md
```

---

## 技术栈

- 后端：FastAPI + SQLite（aiosqlite）
- 邮件：Resend API（即时发送）
- 前端：纯 HTML/CSS/JS
- 备份：rclone + 阿里云盘
- 调度：系统 cron