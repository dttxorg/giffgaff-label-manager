# Giffgaff Activation Client

Windows 本地半自动激活客户端。它从 VPS 后台领取客户任务，打开本机浏览器进入 giffgaff 激活页面，尝试填写 SIM 激活码、邮箱和初始密码，并把手机号/状态回传到后台。

客户端不是无人值守工具。验证码、支付、信用卡、eSIM 转换和异常页面都应该保留人工确认。

## 功能

- 后台地址、Agent Token、客户端 ID 配置
- 支持 Cloudflare Access Service Token：`CF Access Client ID` / `CF Access Secret`
- 测试 `/api/agent/ping`，不会误领取任务
- 领取 `/api/agent/activation-tasks/next`
- 显示并复制邮箱、初始密码、SIM 激活码、地址
- 刷新 MoEmail 验证码并复制到剪贴板
- 打开 Playwright 浏览器并尝试预填 giffgaff 页面
- 固定选择 Pay as you go、£10 top-up，并自动填写本机预设的英国地址和支付卡
- 支付完成后自动打开支付方式页并移除已保存信用卡
- 代理配置：不使用、系统模式、自定义 HTTP/HTTPS/SOCKS5
- 浏览器出口 IP 测试
- 回传状态：等待人工支付、等待转 eSIM、已完成、失败

## 开发运行

```powershell
cd desktop-client
py -3 -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
python -m playwright install chromium
python run.py
```

如果使用 Edge 或 Chrome 渠道，客户端默认优先启动本机 `msedge`，不需要把 Chromium 打包进客户端；如果选择 `chromium`，请先执行 `python -m playwright install chromium`。

## 打包 Windows exe

```powershell
cd desktop-client
.\build_windows.ps1
```

输出位置：

```text
desktop-client\dist\GiffgaffActivationClient\GiffgaffActivationClient.exe
```

打包脚本会设置 `PLAYWRIGHT_BROWSERS_PATH=0` 并安装 Chromium，方便把浏览器运行文件随 exe 一起收集。实际使用时也可以继续选择 `msedge`，直接调用 Windows 自带 Edge。

## 使用流程

1. 在 VPS 后台导入 SIM 激活码并添加客户。
2. VPS 启动时配置 `AGENT_API_TOKEN`。
3. 或者在后台「系统设置」里点击「生成/重置 Token」，复制到客户端 `Agent Token`。
4. 如果后台域名有 Cloudflare Access/Zero Trust 防护，在 Cloudflare 创建 Service Token，并把 `Client ID` / `Client Secret` 填到客户端；如果只是普通 Cloudflare Tunnel 且没有 Access 防护，可留空。
5. 客户端填写后台地址和 Token，点击“测试连接”。
6. 点击“领取下一个任务”。
7. 在“激活自动化预设”里填好固定英国地址、支付卡和“支付后自动解绑银行卡”。
8. 点击“打开并预填”，浏览器会打开 giffgaff 激活页。
9. 遇到邮箱验证码时点击“刷新验证码”，客户端会复制验证码；浏览器自动化还在运行时可点击“填入验证码”。
10. 客户端会继续完成密码、营销偏好、Pay as you go、£10、地址和支付卡填写。
11. 到支付页后，人工确认并点击 `Place order`，完成支付或 3DS。
12. 支付完成后保持浏览器打开；客户端会自动进入 `/profile/payment-details` 并移除保存的信用卡。也可以点击“自动解绑银行卡”手动触发。
13. 拿到手机号后填入客户端，点击“标记等待转 eSIM”或“标记完成”。

领取任务时，后台会自动跳过已经填写手机号的旧客户，避免把已手工处理过的客户再次交给客户端。

完整页面记录见 [`GIFFGAFF_FLOW.md`](GIFFGAFF_FLOW.md)。

## 代理说明

代理只作用于 Playwright 打开的浏览器，不影响客户端请求 VPS 后台。建议使用稳定、可信、低频的出口，不建议频繁轮换代理。

自定义代理填写：

- 类型：`http`、`https` 或 `socks5`
- 主机：代理服务器 IP/域名
- 端口：代理端口
- 用户名/密码：如代理需要认证再填写

设置保存在 Windows 用户目录的 `%APPDATA%\GiffgaffActivationClient\config.json`。这个文件只在本机，不会上传到后台。

> 注意：支付卡预设也保存在本机配置文件中，请只在受控电脑使用，并妥善保护 Windows 账户和配置文件。
