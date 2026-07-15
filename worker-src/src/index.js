// Cloudflare Worker：公开扫码页边缘代理 + 版本化缓存
// 部署说明见 worker-src/README.md
// 代码与 frontend/worker_setup.js 保持同步（修改时两边一起改）

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const m = url.pathname.match(/^\/p\/([A-Za-z0-9_-]{20,128})$/);
    if (!m) {
      return new Response("Not found", { status: 404 });
    }

    const token = m[1];

    // 1) 先拿版本号（小 JSON，~50 字节）
    //    旧 token → 404（DB 旋转后旧 token 立刻失效）
    //    新 token → {public_version: N}
    let version;
    try {
      const vResp = await fetch(`${env.API_BASE}/api/public/${token}/version`, {
        cf: { cacheTtl: 0, cacheEverything: false },
      });
      if (vResp.status !== 200) {
        return new Response("Not found", { status: 404 });
      }
      const data = await vResp.json();
      version = data.public_version;
      if (!version) return new Response("Not found", { status: 404 });
    } catch (e) {
      return new Response("Origin error", { status: 502 });
    }

    // 2) 用 (URL + 版本) 作 cache key
    const cache = caches.default;
    const cacheKey = new Request(`${url.origin}${url.pathname}?v=${version}`, {
      method: "GET",
    });
    const cached = await cache.match(cacheKey);
    if (cached) {
      const h = new Headers(cached.headers);
      h.set("X-Cache", "HIT");
      return new Response(cached.body, { status: cached.status, headers: h });
    }

    // 3) Cache miss：回调 FastAPI 拿完整 HTML
    let origin;
    try {
      origin = await fetch(`${env.API_BASE}/p/${token}`, {
        headers: { "X-Forwarded-Host": url.host },
        cf: { cacheTtl: 0, cacheEverything: false },
      });
    } catch (e) {
      return new Response("Origin error", { status: 502 });
    }

    if (origin.status !== 200) {
      return new Response("Not found", { status: 404 });
    }

    // 4) 透传 + 补安全头 + 写缓存（30 天）
    const headers = new Headers(origin.headers);
    headers.set("X-Content-Type-Options", "nosniff");
    headers.set("X-Frame-Options", "DENY");
    headers.set("Referrer-Policy", "no-referrer");
    headers.set(
      "Content-Security-Policy",
      "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; img-src data:; form-action 'none'; base-uri 'none'; frame-ancestors 'none'"
    );
    // Cloudflare Cache API 硬上限 30 天（即使这里写 60 天也会被截断）
    headers.set("Cache-Control", "public, max-age=2592000");
    headers.set("X-Cache", "MISS");
    headers.set("X-Cache-Version", String(version));

    const response = new Response(origin.body, { status: 200, headers });
    ctx.waitUntil(cache.put(cacheKey, response.clone()));
    return response;
  },
};
