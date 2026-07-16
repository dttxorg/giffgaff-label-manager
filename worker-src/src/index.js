// Cloudflare Worker：公开扫码页边缘代理 + 版本化缓存
// 部署说明见 worker-src/README.md
// 代码与 frontend/worker_setup.js 保持同步，并由测试强制校验。

const WORKER_VERSION = "4";
const PUBLIC_TOKEN_PATTERN = /^\/p\/([A-Za-z0-9_-]{20,128})$/;

export function getApiBase(env) {
  const raw = String(env?.API_BASE || "").trim();
  if (!raw) throw new Error("API_BASE is not configured");

  const url = new URL(raw);
  if (!['http:', 'https:'].includes(url.protocol)) {
    throw new Error("API_BASE must use http or https");
  }
  if (url.search || url.hash) {
    throw new Error("API_BASE must not contain a query or fragment");
  }

  return url.toString().replace(/\/+$/, "");
}

function workerResponse(body, status, extraHeaders = {}) {
  const headers = new Headers(extraHeaders);
  headers.set("X-Public-Card-Worker", WORKER_VERSION);
  return new Response(body, { status, headers });
}

function configurationError() {
  return workerResponse("Worker configuration error", 500, {
    "X-Worker-Error": "api-base",
  });
}

function originResult(body, status, stage, originStatus) {
  return workerResponse(body, status, {
    "X-Origin-Stage": stage,
    "X-Origin-Status": String(originStatus),
  });
}

function originError(stage, originStatus = 0) {
  return originResult("Origin error", 502, stage, originStatus);
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const match = url.pathname.match(PUBLIC_TOKEN_PATTERN);
    if (!match) {
      return workerResponse("Not found", 404);
    }

    let apiBase;
    try {
      apiBase = getApiBase(env);
    } catch (_error) {
      return configurationError();
    }

    const token = encodeURIComponent(match[1]);

    // 每次先向源站查询版本。旧 token 会由源站明确返回 404。
    let versionResponse;
    try {
      versionResponse = await fetch(`${apiBase}/api/public/${token}/version`, {
        cf: { cacheTtl: 0, cacheEverything: false },
      });
    } catch (_error) {
      return originError("version");
    }

    if (versionResponse.status === 404) {
      return originResult("Not found", 404, "version", 404);
    }
    if (versionResponse.status !== 200) {
      return originError("version", versionResponse.status);
    }

    let version;
    try {
      const data = await versionResponse.json();
      version = data.public_version;
    } catch (_error) {
      return originError("version", versionResponse.status);
    }
    if (!version) {
      return originError("version", versionResponse.status);
    }

    const cache = caches.default;
    const cacheKey = new Request(
      `${url.origin}${url.pathname}?v=${encodeURIComponent(String(version))}&worker=${WORKER_VERSION}`,
      {
        method: "GET",
      }
    );
    const cached = await cache.match(cacheKey);
    if (cached) {
      const headers = new Headers(cached.headers);
      headers.set("X-Cache", "HIT");
      headers.set("X-Public-Card-Worker", WORKER_VERSION);
      headers.set("X-Origin-Stage", "version");
      headers.set("X-Origin-Status", String(versionResponse.status));
      return new Response(cached.body, {
        status: cached.status,
        headers,
      });
    }

    let pageResponse;
    try {
      pageResponse = await fetch(`${apiBase}/p/${token}`, {
        headers: { "X-Forwarded-Host": url.host },
        cf: { cacheTtl: 0, cacheEverything: false },
      });
    } catch (_error) {
      return originError("page");
    }

    if (pageResponse.status === 404) {
      return originResult("Not found", 404, "page", 404);
    }
    if (pageResponse.status !== 200) {
      return originError("page", pageResponse.status);
    }

    const headers = new Headers(pageResponse.headers);
    headers.set("X-Content-Type-Options", "nosniff");
    headers.set("X-Frame-Options", "DENY");
    headers.set("Referrer-Policy", "no-referrer");
    headers.set(
      "Content-Security-Policy",
      "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; img-src data:; form-action 'none'; base-uri 'none'; frame-ancestors 'none'"
    );
    // Cloudflare Cache API 硬上限 30 天。
    headers.set("Cache-Control", "public, max-age=2592000");
    headers.set("X-Cache", "MISS");
    headers.set("X-Cache-Version", String(version));
    headers.set("X-Public-Card-Worker", WORKER_VERSION);
    headers.set("X-Origin-Stage", "page");
    headers.set("X-Origin-Status", String(pageResponse.status));

    const response = new Response(pageResponse.body, { status: 200, headers });
    ctx.waitUntil(cache.put(cacheKey, response.clone()));
    return response;
  },
};
