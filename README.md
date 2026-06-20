# Giffgaff Label Manager

一个轻量的 Giffgaff 客户、MoEmail 临时邮箱和标签打印管理工具。项目功能包括客户管理、按需生成 MoEmail、JSON 导入导出和可视化标签模板。

---

## 功能总览

- **客户管理**：先按开通日期建档，邮箱可手填或生成 MoEmail，手机号和收货地址可后补
- **SIM 激活码库**：批量导入 giffgaff SIM 激活码，添加客户时可选择使用或不使用激活码，并可在库中标记不用/删除
- **激活任务中心**：自动生成初始密码和激活任务，供本地桌面客户端领取并回写手机号/状态
- **发货状态**：客户列表显示收货地址、快递公司、快递单号和手动维护的未发货、已发货、已收货状态
- **菜鸟取号**：配置菜鸟/淘宝开放平台凭证和固定发件地址后，可按客户收货地址调用电子面单取号
- **MoEmail 集成**：客户行按钮按需生成临时邮箱，保存分享链接，拉取可用域名
- **邮箱接码**：MoEmail 客户可刷新最新邮件并自动提取 Giffgaff 6 位验证码
- **Windows 客户端**：本地领取激活任务，打开浏览器半自动填写 giffgaff 激活流程，并回传手机号/状态
- **标签模板**：四个默认模板，可拖拽排版，支持 `50mm x 30mm` 和 `50mm x 40mm`
- **二维码打印**：模板里可放邮箱二维码和 Giffgaff App 下载二维码
- **导出导入**：手动导出/恢复客户、标签模板和安全设置 JSON
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

首次启动会自动创建数据库。旧数据库如果缺少 MoEmail 字段，或手机号字段仍是必填约束，也会在启动时自动补齐/迁移。

### 3. 设置访问口令

如果部署到公网，建议配置一个访问口令：

```bash
export APP_PASSWORD="换成你的强口令"
uvicorn main:app --host 0.0.0.0 --port 8000
```

设置后，访问页面会先要求输入口令，所有 API 也会被同一个口令保护。未设置 `APP_PASSWORD` 时，系统默认不启用登录保护，适合本地开发。

桌面客户端 API 使用独立 Token：

```bash
export AGENT_API_TOKEN="换成一串很长的随机密钥"
```

本地自动化客户端请求 `/api/agent/*` 时需要带：

```text
Authorization: Bearer <AGENT_API_TOKEN>
```

### 4. 配置 MoEmail

打开页面右上角「设置」，填入：

| 配置 | 说明 |
|---|---|
| MoEmail 部署地址 | 例如 `https://moemail.yourdomain.com`，不带尾部斜杠 |
| MoEmail API Key | 在 MoEmail 后台创建的 API Key |

保存后添加客户时，如果邮箱留空，系统会让 MoEmail 自动分配邮箱名，并把生成的地址写入该客户唯一的邮箱字段。客户详情里的「验证码」区域可以点击「刷新」，系统会读取该 MoEmail 收件箱最新邮件，并从 Giffgaff `Confirm it's you` 邮件中提取 6 位验证码。手填邮箱没有 MoEmail 邮箱 ID，无法自动读取邮件。

### 5. SIM 激活码与桌面客户端

在「SIM 激活码」页面批量导入激活码后，添加客户时可以选择「使用激活码」或「不使用激活码」。选择使用时系统会自动：

- 分配一个未使用 SIM 激活码
- 生成初始密码
- 使用手填邮箱，或在邮箱留空时生成 MoEmail
- 创建状态为「等待客户端领取」的激活任务

如果选择「不使用激活码」，客户会正常建档但不会创建桌面客户端激活任务。SIM 激活码库中可把未分配的激活码标记为「不用」，也可以删除误导入的激活码；删除已开始/已完成客户关联的激活码时，只移除码库记录并保留客户激活信息。

桌面客户端可使用这些接口：

```text
GET   /api/agent/ping
GET   /api/agent/activation-tasks/next
POST  /api/agent/customers/{id}/activation-log
PATCH /api/agent/customers/{id}/activation-status
PATCH /api/agent/customers/{id}/activation-result
GET   /api/agent/customers/{id}/verification-code
```

客户端领取任务后会拿到客户 ID、邮箱、初始密码、SIM 激活码和收货地址；完成网页流程后回传手机号，并把状态推进到「等待转 eSIM」或「已完成」。

### 6. Windows 本地客户端

`desktop-client/` 目录包含 Windows 半自动客户端：

- 配置后台地址、`AGENT_API_TOKEN` 和客户端 ID
- 领取下一个激活任务，不会要求提前填写手机号
- 显示并复制邮箱、初始密码、SIM 激活码和收货地址
- 支持不使用代理、系统代理、自定义 HTTP/HTTPS/SOCKS5 代理
- 可测试浏览器出口 IP
- 打开本机 Edge/Chrome/Chromium 并按实测流程预填 giffgaff 激活页面
- 固定选择 Pay as you go、£10 top-up，自动填写本机预设英国地址和支付卡
- 支付完成后自动打开支付方式页面并移除保存的信用卡
- 刷新 MoEmail 验证码，复制或填入正在运行的浏览器页面
- 手动标记等待人工支付、等待转 eSIM、已完成或失败

开发运行：

```powershell
cd desktop-client
py -3 -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
python -m playwright install chromium
python run.py
```

Windows 打包：

```powershell
cd desktop-client
.\build_windows.ps1
```

客户端是半自动助手，不建议无人值守批量运行；支付、信用卡、eSIM 转换和异常页面都应人工确认。

### 7. 使用标签模板

「标签模板」页面内置四个模板：

- `基础标签 50x30`
- `完整标签 50x40`
- `双码标签 50x40`
- `快递单 50x40`

模板支持拖拽排版，变量名称使用中文，包括手机号、邮箱、开通日期、收货地址、发货状态、快递公司、快递单号、邮箱二维码、Giffgaff 下载二维码等。编辑器中的二维码使用固定演示值；在客户行点击「打印标签」时，会自动替换成该客户的邮箱/收件箱二维码和当前设置里的 Giffgaff 下载链接二维码，且不会混入快递单模板。客户行的「快递单」按钮会固定使用快递模板，适合打印包含收货地址和快递信息的手动快递单。

---

## 菜鸟电子面单

「系统设置」里可配置菜鸟接口参数和固定发件地址。需要提前在菜鸟/淘宝开放平台完成应用、授权和物流公司电子面单订购，至少准备：

- AppKey、AppSecret、授权 Session
- 物流公司编码、物流公司名称
- 云打印模板 URL、使用者 ID
- 固定发件人姓名、电话和完整地址

客户行点击「菜鸟取号」后，后端会调用 `cainiao.waybill.ii.get`，用设置里的发件地址作为寄件人，用客户「收货地址」作为收件人，成功后写回快递公司、快递单号、菜鸟订单号和云打印数据。客户收货地址建议按 `姓名 手机号 省市区详细地址` 格式录入，便于系统解析收件人和地址。

AppSecret 和授权 Session 只保存在本地数据库，设置页不会明文回显，导出 JSON 也不会包含这两个敏感值。

---

## 数据导出 / 导入

### 导出

管理界面右上角有「导出」按钮。导出的 JSON 包含客户数据、收货地址、发货状态、快递公司、快递单号、非敏感菜鸟配置、Giffgaff 下载链接、MoEmail 部署地址和标签模板。MoEmail API Key、菜鸟 AppSecret 和授权 Session 不会写入导出文件。

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
│   ├── requirements.txt
│   └── giffgaff.db      # 数据库（自动创建，已被 .gitignore 忽略）
├── desktop-client/
│   ├── giffgaff_client/ # Windows 半自动激活客户端
│   ├── requirements.txt
│   ├── build_windows.ps1
│   └── run.py
├── frontend/
│   └── index.html       # 管理界面
└── README.md
```

---

## 技术栈

- 后端：FastAPI + SQLite（aiosqlite）
- 邮箱：MoEmail 临时邮箱和分享链接
- 前端：纯 HTML/CSS/JS
- 客户端：Python + PySide6 + Playwright
