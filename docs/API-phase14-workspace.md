# Phase 14: Workspace API 参考

> 版本: v0.14.0 | 基础路径: `/api/v1`

共享工作区 REST API，支持文件 CRUD、目录操作、文件锁和批量读写。

## RBAC 权限

| 权限 | 说明 | 包含 |
|------|------|------|
| `workspace:read` | 读取文件/目录/锁状态 | — |
| `workspace:write` | 写入文件、创建目录、获取锁 | 包含 `workspace:read` |
| `workspace:admin` | 删除文件/目录、释放锁 | 包含 `workspace:write` + `workspace:read` |

**角色默认权限**:
- `admin`: workspace:read, workspace:write, workspace:admin
- `agent`: workspace:read, workspace:write
- `observer`: workspace:read

---

## 文件操作

### POST /workspaces/{project_id}/files/{path}

创建或覆盖文件。请求体为原始字节。

**权限**: `workspace:write`

**路径参数**:
| 参数 | 类型 | 说明 |
|------|------|------|
| `project_id` | string | 项目命名空间 |
| `path` | string | 文件路径（如 `src/main.py`） |

**查询参数**:
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `lock_id` | string | null | 写锁 ID（文件被锁时必填） |

**请求头**:
- `Content-Type`: 文件 MIME 类型，默认 `application/octet-stream`
- `Authorization: Bearer ***`

**请求体**: 原始文件字节

**响应**: `FileNode` 对象
```json
{
  "id": "uuid-xxx",
  "project_id": "myproject",
  "path": "src/main.py",
  "name": "main.py",
  "file_type": "file",
  "parent_path": "src",
  "size": 1234,
  "content_type": "text/x-python",
  "checksum_sha256": "abc123...",
  "created_by": "agent-alpha",
  "created_at": "2026-06-13T10:00:00Z",
  "updated_at": "2026-06-13T10:00:00Z",
  "version": 2
}
```

**状态码**:
- `201` — 创建/更新成功
- `409` — 文件被其他 Agent 锁定（PermissionError）
- `503` — Workspace 服务未初始化

---

### GET /workspaces/{project_id}/files/{path}

读取文件内容。支持 Range 头实现部分读取。

**权限**: `workspace:read`

**请求头**:
- `Range: bytes=0-1023` — 可选，部分读取

**响应**: 原始文件字节

**响应头**:
| 头 | 说明 |
|----|------|
| `X-Checksum-SHA256` | 文件 SHA256 校验和 |
| `X-Version` | 文件版本号 |
| `Content-Range` | 部分读取时的范围（`bytes 0-1023/1234`） |

**状态码**:
- `200` — 完整读取
- `206` — 部分读取（Range 请求）
- `400` — Range 头格式无效
- `404` — 文件不存在
- `416` — Range 不可满足

---

### DELETE /workspaces/{project_id}/files/{path}

删除文件。文件被其他 Agent 锁定时失败。

**权限**: `workspace:admin`

**响应**: `{"status": "deleted"}`

**状态码**:
- `200` — 删除成功
- `404` — 文件不存在
- `409` — 文件被锁定

---

### HEAD /workspaces/{project_id}/files/{path}

获取文件元数据（不返回内容）。

**权限**: `workspace:read`

**响应头**:
| 头 | 说明 |
|----|------|
| `X-File-Id` | 文件 UUID |
| `X-Size` | 文件大小（字节） |
| `X-Content-Type` | MIME 类型 |
| `X-Checksum-SHA256` | SHA256 校验和 |
| `X-Version` | 版本号 |
| `X-Created-By` | 创建者 agent_id |
| `X-Updated-At` | 最后更新时间（ISO 格式） |

**状态码**:
- `200` — 成功
- `404` — 文件不存在

---

## 目录操作

### GET /workspaces/{project_id}/tree

列出目录内容。

**权限**: `workspace:read`

**查询参数**:
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `path` | string | "" | 目录路径（空 = 根目录） |
| `recursive` | bool | false | 是否递归列出 |

**响应**:
```json
{
  "path": "src",
  "entries": [
    {
      "path": "src/main.py",
      "file_type": "file",
      "size": 1234
    },
    {
      "path": "src/utils",
      "file_type": "directory",
      "size": 0
    }
  ]
}
```

**状态码**:
- `200` — 成功

---

### POST /workspaces/{project_id}/dirs/{path}

创建目录（幂等：已存在则返回现有节点）。

**权限**: `workspace:write`

**响应**: `FileNode` 对象

**状态码**:
- `201` — 创建成功（或已存在）

---

### DELETE /workspaces/{project_id}/dirs/{path}

删除空目录。非空目录删除失败。

**权限**: `workspace:admin`

**响应**: `{"status": "removed", "path": "src/old"}`

**状态码**:
- `200` — 删除成功
- `404` — 目录不存在
- `409` — 目录非空
- `403` — 无权限

---

## 锁操作

### POST /workspaces/{project_id}/locks

获取文件锁（读锁或写锁）。

**权限**: `workspace:write`

**请求体**:
```json
{
  "path": "src/main.py",
  "lock_type": "write",
  "agent_id": "agent-alpha",
  "ttl_seconds": 300
}
```

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `path` | string | 必填 | 要锁定的文件路径 |
| `lock_type` | string | 必填 | `read` 或 `write` |
| `agent_id` | string | 必填 | 请求锁的 Agent |
| `ttl_seconds` | int | 300 | 锁超时（10-3600 秒） |

**锁兼容性**:

| | 无锁 | 读锁 | 写锁 |
|---|---|---|---|
| **读锁请求** | ✅ | ✅ 共享 | ❌ 冲突 |
| **写锁请求** | ✅ | ❌ 冲突 | ❌ 冲突 |

**响应**: `FileLock` 对象
```json
{
  "id": "lock-uuid",
  "file_id": "file-uuid",
  "project_id": "myproject",
  "path": "src/main.py",
  "lock_type": "write",
  "held_by": "agent-alpha",
  "acquired_at": "2026-06-13T10:00:00Z",
  "expires_at": "2026-06-13T10:05:00Z"
}
```

**状态码**:
- `201` — 获取成功
- `409` — 锁冲突

---

### DELETE /workspaces/{project_id}/locks/{lock_id}

释放持有的锁。

**权限**: `workspace:admin`

**查询参数**:
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `agent_id` | string | "" | 释放锁的 Agent |

**响应**: `{"status": "released", "lock_id": "lock-uuid"}`

**状态码**:
- `200` — 释放成功
- `404` — 锁不存在或不属于该 Agent

---

### GET /workspaces/{project_id}/locks

检查文件是否被锁定。

**权限**: `workspace:read`

**查询参数**:
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `path` | string | "" | 文件路径 |

**响应（未锁定）**:
```json
{"locked": false, "path": "src/main.py"}
```

**响应（已锁定）**:
```json
{
  "locked": true,
  "id": "lock-uuid",
  "path": "src/main.py",
  "lock_type": "write",
  "held_by": "agent-alpha",
  "expires_at": "2026-06-13T10:05:00Z"
}
```

**状态码**:
- `200` — 成功

---

## 批量操作

### POST /workspaces/{project_id}/pull

批量读取多个文件。跳过不存在的文件。

**权限**: `workspace:write`

**请求体**:
```json
{
  "paths": ["src/main.py", "src/utils/helpers.py", "docs/README.md"]
}
```

**响应**:
```json
{
  "files": {
    "src/main.py": "<base64-encoded-content>",
    "docs/README.md": "<base64-encoded-content>"
  }
}
```

> 注意：不存在的文件不会出现在响应中。

**状态码**:
- `200` — 成功

---

### POST /workspaces/{project_id}/push

批量写入多个文件。锁检查失败时整体回滚。

**权限**: `workspace:write`

**请求体**:
```json
{
  "files": {
    "src/main.py": {"content_b64": "<base64-encoded>"},
    "src/utils/helpers.py": {"content_b64": "<base64-encoded>"}
  },
  "lock_ids": {
    "src/main.py": "lock-uuid-1"
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `files` | dict | 路径 → `{content_b64: string}` |
| `lock_ids` | dict | 可选，路径 → lock_id |

**响应**:
```json
{
  "files": [
    {"id": "uuid", "path": "src/main.py", "version": 3, "...": "..."},
    {"id": "uuid", "path": "src/utils/helpers.py", "version": 1, "...": "..."}
  ]
}
```

**状态码**:
- `200` — 成功
- `409` — 锁冲突（整体回滚，无文件被写入）

---

## Agent 工作流示例

```
1. Agent 收到 TASK_ASSIGNED（含 workspace_paths 提示）
2. POST /workspaces/{project}/pull      → 下载所需文件
3. POST /workspaces/{project}/locks     → 获取写锁
4. 本地编辑文件
5. POST /workspaces/{project}/push      → 上传修改
6. DELETE /workspaces/{project}/locks/{id} → 释放锁
7. 发送 TASK_COMPLETED（含 artifact_paths）
```
