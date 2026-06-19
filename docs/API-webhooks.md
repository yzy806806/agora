# Agora Webhook API

> Phase 14+.D | 基础路径: `/api/v1`

## Webhook 管理

### POST /webhooks

创建 Webhook。

**请求体**:
```json
{
  "url": "https://example.com/hook",
  "events": ["task.completed", "pipeline.completed"],
  "secret": "whsec_...",
  "pipeline_template": {"project_id": "my-project"},
  "ip_allowlist": ["1.2.3.0/24"]
}
```

**响应**: `201` — Webhook 对象

---

### GET /webhooks

列出所有 Webhook。

---

### GET /webhooks/{webhook_id}

获取 Webhook 详情。

---

### PATCH /webhooks/{webhook_id}

更新 Webhook 配置。

---

### DELETE /webhooks/{webhook_id}

删除 Webhook。

---

## Webhook 触发

### POST /webhooks/{webhook_id}/trigger

手动触发 Webhook（测试用）。

---

### GET /webhooks/{webhook_id}/history

获取 Webhook 触发历史。

---

## 安全机制

- **HMAC-SHA256 签名验证**: 每个请求包含 `X-Agora-Signature-256` header
- **速率限制**: 可配置 per-webhook 触发频率
- **IP 白名单**: 可配置允许的来源 IP/CIDR
- **Pipeline 模板**: 触发时自动创建 Pipeline，支持 Jinja2 模板渲染
