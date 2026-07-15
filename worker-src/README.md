# public-card Worker

Cloudflare Worker：把扫码公开页 (`/p/{token}`) 部署到边缘，30 天版本化缓存。

## 部署方式

### 方式 A：GitHub 自动部署（推荐）

1. 把这个目录 (`worker-src/`) 推到 GitHub（它已在 `dttxorg/giffgaff-label-manager` 仓库里）
2. Cloudflare 控制台 → **Workers & Pages** → **Create** → **Pages** → **Connect to Git**
3. 选择 `dttxorg/giffgaff-label-manager` 仓库
4. 配置：
   - **Project name**: `public-card`（可改）
   - **Production branch**: `main`
   - **Build command**: 留空
   - **Build output directory**: 留空
   - **Root directory** (advanced): `worker-src`
5. 点 **Save and Deploy** —— 第一次部署会失败，因为环境变量还没设
6. 进 **Settings** → **Environment variables** → 加一个：
   - `API_BASE` = `https://label.example.com`（你 admin 的实际 URL，**不要带尾部斜杠**）
7. 重新触发部署（Deployments → Retry）

以后改代码 push 到 main，Cloudflare 自动部署。

### 方式 B：手动 wrangler CLI

```bash
cd worker-src
npm install
# 编辑 wrangler.toml 把 API_BASE 改成你的 admin URL
wrangler deploy
```

### 绑自定义域名（两种方式都要做）

1. Cloudflare 控制台 → Workers & Pages → `public-card` → **Settings** → **Triggers** → **Custom Domains** → **Add Custom Domain**
2. 输入子域，例如 `card.example.com` → **Add Custom Domain**
3. DNS 自动配好

### 回到 admin 填域名

你的 admin → **Worker 部署** 标签页 → 顶部「Worker 域名」输入框 → 填 `https://card.example.com` → 保存

之后客户扫码会走 `card.example.com`，所有公共流量不打到你的服务器。

## 验证

F12 → Network → 扫码访问 `/p/{token}` → 第二次刷新响应头应该有 `X-Cache: HIT`。

## 回滚

Cloudflare → Workers & Pages → `public-card` → **Deployments** → 选旧版本 → **Rollback to this deploy**。
