# Giffgaff Label Manager

一个轻量的 Giffgaff 客户、MoEmail 临时邮箱和标签打印管理工具。项目功能包括客户管理、按需生成 MoEmail、JSON 导入导出、飞牛 NAS 目录备份和可视化标签模板。

---

## 功能总览

- **客户管理**：增删改查手机号、邮箱、开通日期
- **MoEmail 集成**：客户行按钮按需生成临时邮箱，保存分享链接，拉取可用域名
- **标签模板**：三个默认模板，可拖拽排版，支持 `50mm x 30mm` 和 `50mm x 40mm`
- **二维码打印**：模板里可放邮箱二维码和 Giffgaff App 下载二维码
- **导出导入**：一键备份/恢复客户、标签模板和安全设置 JSON
- **飞牛备份**：设置备份目录后，可在页面里立即备份、下载备份、恢复备份
- **管理界面**：纯 HTML/CSS/JS，无需前端构建

---

## 架构说明

```
管理界面
    ↓
FastAPI API
    ↓
SQLite 保存客户、MoEmail 信息和系统设置
    ↓
MoEmail API 生成邮箱和分享链接
```

MoEmail 部署地址和 API Key 在管理界面的「系统设置」中保存，不依赖本地 `.env` 文件。

---

## 快速开始

### 1. 安装依赖

```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. 启动 Web 服务

```bash
cd backend
source venv/bin/activate
uvicorn main:app --host 0.0.0.0 --port 8000
```

访问：

```text
http://localhost:8000
```

首次启动会自动创建数据库。旧数据库如果缺少 MoEmail 字段，也会在启动时自动补齐。

### 3. 设置访问口令

如果部署到公网，建议配置一个访问口令：

```bash
export APP_PASSWORD="换成你的强口令"
uvicorn main:app --host 0.0.0.0 --port 8000
```

设置后，访问页面会先要求输入口令，所有 API 也会被同一个口令保护。未设置 `APP_PASSWORD` 时，系统默认不启用登录保护，适合本地开发。

### 4. 配置 MoEmail

打开页面右上角「设置」，填入：

| 配置 | 说明 |
|---|---|
| MoEmail 部署地址 | 例如 `https://moemail.yourdomain.com`，不带尾部斜杠 |
| MoEmail API Key | 在 MoEmail 后台创建的 API Key |

保存后即可在客户列表里点击「生成邮箱」，系统会让 MoEmail 自动分配邮箱名，并把生成的地址写入该客户唯一的邮箱字段。

### 5. 使用标签模板

「标签模板」页面内置三个模板：

- `基础标签 50x30`
- `完整标签 50x40`
- `双码标签 50x40`

模板支持拖拽排版，变量名称使用中文，包括手机号、邮箱、开通日期、邮箱二维码、Giffgaff 下载二维码等。编辑器中的二维码使用固定演示值；在客户行点击「打印标签」时，会自动替换成该客户的邮箱/收件箱二维码和当前设置里的 Giffgaff 下载链接二维码。

---

## 飞牛 NAS 备份

推荐把飞牛 NAS 的某个目录映射到运行本项目的机器或容器里，然后在页面右上角「设置」里填入这个目录。

例如：

```text
/vol1/1000/backups/giffgaff-label-manager
```

保存后，「飞牛备份」区域可以：

- 立即生成备份 JSON
- 查看最近备份文件
- 下载单个备份
- 从指定备份恢复

备份内容包含客户数据、Giffgaff 下载链接、MoEmail 部署地址和标签模板。MoEmail API Key 不会写入备份文件。

也可以用脚本配合系统定时任务：

```bash
BACKUP_DIR="/vol1/1000/backups/giffgaff-label-manager" ./backend/backup.sh
```

默认保留 30 天备份，如需调整：

```bash
BACKUP_KEEP_DAYS=90 BACKUP_DIR="/vol1/1000/backups/giffgaff-label-manager" ./backend/backup.sh
```

### 定时备份

```bash
crontab -e
```

添加：

```cron
0 10 * * * BACKUP_DIR="/vol1/1000/backups/giffgaff-label-manager" /path/to/giffgaff-label-manager/backend/backup.sh >> /path/to/backup.log 2>&1
```

---

## 数据导出 / 导入

### 导出

管理界面右上角有「导出」按钮。

或用 API：

```bash
curl http://localhost:8000/api/export > backup.json
```

### 导入

管理界面上传 JSON 文件即可恢复。

或用 API：

```bash
curl -X POST http://localhost:8000/api/import \
  -F "file=@backup.json"
```

导入会替换现有客户数据，并恢复备份中的标签模板和安全设置。后端会先校验备份结构，并在事务中执行恢复；失败会回滚，不会先清空数据后中断。

---

## 目录结构

```
giffgaff-label-manager/
├── backend/
│   ├── main.py          # FastAPI 主程序
│   ├── database.py      # SQLite 初始化和轻量迁移
│   ├── crud.py          # 数据库操作
│   ├── moemail.py       # MoEmail API 客户端
│   ├── models.py        # Pydantic 数据模型
│   ├── backup.sh        # 本地/飞牛 NAS 目录备份脚本
│   ├── requirements.txt
│   └── giffgaff.db      # 数据库（自动创建，已被 .gitignore 忽略）
├── frontend/
│   └── index.html       # 管理界面
└── README.md
```

---

## 技术栈

- 后端：FastAPI + SQLite（aiosqlite）
- 邮箱：MoEmail 临时邮箱和分享链接
- 前端：纯 HTML/CSS/JS
- 备份：本地/飞牛 NAS 目录 JSON 快照
