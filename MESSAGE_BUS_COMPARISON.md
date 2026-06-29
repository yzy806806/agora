# 多 Agent 协作系统通信总线 — 开源消息平台对比分析

> **日期**: 2026-06-29 | **作者**: hermes-agent (research subagent)  
> **背景**: Agora 当前使用 WebSocket 直连 + Redis Pub/Sub（多实例广播），需要评估是否需要更成熟的消息总线

---

## 目录

1. [评估维度说明](#评估维度说明)
2. [逐平台分析](#逐平台分析)
3. [对比总表](#对比总表)
4. [场景分类推荐](#场景分类推荐)
5. [最终推荐方案](#最终推荐方案)

---

## 评估维度说明

| 维度 | 含义 |
|------|------|
| **NAT/防火墙穿透** | 是否能从内网（无公网 IP）的 agent 直接连接到 broker/coordinator，无需端口映射 |
| **公网 IP 需求** | 是否需要一方（broker 或 agent）拥有公网 IP |
| **部署复杂度** | Python 项目视角：是否需要安装额外运行时（Erlang/JVM）、配置管理等 |
| **离线消息/持久化** | agent 离线期间的消息是否保留，重连后可回放 |
| **Python 客户端** | 是否有成熟的 asyncio 兼容 Python 客户端 |
| **多租户/隔离** | 是否原生支持 tenant 级别的逻辑隔离或物理隔离 |
| **资源消耗** | 在 ARM 2核/11GB 小机器上的实际开销 |
| **信令 vs 数据** | 适合传输控制指令（信令通道）还是大数据流（数据通道） |

**核心场景**: 多个 agent（分布在任意网络位置的 Python 进程）需要与 Agora Coordinator 双向通信，交换任务分配、心跳、结果报告等消息。

---

## 逐平台分析

### 1. Matrix (matrix.org)

**协议**: 去中心化联邦即时通讯协议，基于 HTTP + 服务器间联邦

| 维度 | 评估 |
|------|------|
| NAT 穿透 | ✅ **优秀** — 纯 HTTP/HTTPS，agent 作为客户端向 homeserver 发起连接，天然穿透 NAT。联邦模式下 homeserver 间通过 HTTPS 互连 |
| 公网 IP | ✅ **不需要 agent 有公网 IP** — 只需 homeserver 有公网可访问的 HTTPS 端点即可 |
| 部署复杂度 | 🔴 **高** — 需要运行 Synapse（Python 但重量级，~400MB 内存起）或 Dendrite（Go，较轻）。homeserver 部署涉及 DNS、TLS 证书、数据库（Postgres）、联邦配置。AgentTeams 的实践表明运维负担不轻 |
| 离线消息 | ✅ 原生支持 — 消息持久化在 homeserver，agent 上线后自动同步未读消息 |
| Python 客户端 | ✅ `matrix-nio`（asyncio 原生）、`simplematrixbotlib` |
| 多租户 | ✅ 通过不同 room 实现逻辑隔离；可用 community/space 分组 |
| 资源消耗 | 🔴 **偏高** — Synapse 基础部署 400MB-1GB RAM，Postgres 额外开销。ARM 2核机器上勉强可行但不轻量 |
| 信令/数据 | 🟡 **偏信令通道** — 适合 JSON 消息，大文件通过 MXC 媒体 API 走 HTTP 上传下载 |

**总体评价**: 去中心化联邦是最大亮点（多个 Agora 实例可以联邦互通），但部署运维太重。如果 future 需要跨组织 agent 通信，Matrix 是首选。当前阶段过重。

**适合**: 跨组织、去中心化场景；AgentTeams 级别的项目

---

### 2. NATS (nats.io)

**协议**: 自研高性能二进制协议（NATS Protocol），支持 TCP、WebSocket、MQTT、Leaf Node

| 维度 | 评估 |
|------|------|
| NAT 穿透 | ✅ **WebSocket 模式可穿透** — NATS Server 支持 WebSocket 客户端连接，agent 作为 WS 客户端主动出站，穿透 NAT/firewall。原生 TCP 协议需要直连 |
| 公网 IP | ✅ **只需 NATS Server 有公网可达地址** — agent 通过 WS 连接 server |
| 部署复杂度 | 🟢 **极低** — 单二进制文件（Go 编译），无外部依赖。`nats-server -js` 一行启动。JetStream 持久化内置 |
| 离线消息 | ✅ JetStream（内置持久化流）支持 consumer 离线重放、work queue、KV store。也可用简单的 Core NATS 无持久化 |
| Python 客户端 | ✅ `nats-py` — 纯 Python，asyncio 原生，支持 JetStream。项目活跃 |
| 多租户 | ✅ **优秀** — Account/User 层级隔离（multi-tenancy 是 NATS 核心设计之一）。可通过不同的 subject prefix 实现逻辑隔离 |
| 资源消耗 | 🟢 **极低** — 空载 ~15MB RAM，中等负载 ~100MB。专为边缘和资源受限环境设计 |
| 信令/数据 | ✅ **两者皆可** — Core NATS 适合信令（低延迟 pub/sub、request-reply），JetStream 适合数据（持久化流、work queue、KV） |

**总体评价**: 几乎为多 agent 通信量身定做。轻量到极致，功能齐全，多租户原生支持。CNCF 毕业项目，生产验证充分。

**适合**: 需要高性能、低延迟、多租户的单组织 agent 通信总线

---

### 3. RabbitMQ

**协议**: AMQP 0-9-1 / 1.0，支持 STOMP、MQTT、HTTP

| 维度 | 评估 |
|------|------|
| NAT 穿透 | 🟡 **有限** — AMQP 原生是 TCP，不能直接穿透 NAT。但支持 Web STOMP（WebSocket 上的 STOMP 协议）和 MQTT 插件（WebSocket），可间接穿透 |
| 公网 IP | 🟡 **需 broker 公网可达** — agent 通过 Web STOMP/WS MQTT 连接 |
| 部署复杂度 | 🔴 **中高** — 需要 Erlang 运行时。虽然 Docker 镜像简化了部署，但 Erlang 集群、vhost、权限等配置比 NATS 复杂不少 |
| 离线消息 | ✅ **原生支持** — Queue（持久化队列）、Dead Letter Exchange、消息 TTL 等成熟特性 |
| Python 客户端 | ✅ `aio-pika`（asyncio）、`pika`（同步）。生态成熟但 `aio-pika` 维护不如 NATS 的 python 客户端活跃 |
| 多租户 | ✅ **优秀** — vhost 提供物理级隔离（独立的 exchange/queue/binding 空间），user 权限可精确到 vhost 级别 |
| 资源消耗 | 🟡 **中等** — 空载 ~80-120MB RAM，Erlang VM 自带开销。ARM 2核机器上可以运行但略显笨重 |
| 信令/数据 | ✅ **两者皆可** — Direct exchange 适合信令（精确路由），Topic exchange 适合广播。Streams（3.9+）适合数据流持久化 |

**总体评价**: 功能最完善的传统消息队列，但 Erlang 运行时和运维复杂度对轻量 Python 项目是负担。多租户隔离做得最好（vhost）。

**适合**: 企业级消息需求，需要复杂路由策略（binding key、header exchange），已有 RabbitMQ 基础设施

---

### 4. Redis Pub/Sub + Streams

**协议**: RESP 协议（TCP），Redis 5.0+ Streams 提供持久化

| 维度 | 评估 |
|------|------|
| NAT 穿透 | 🟡 **需要隧道/跳板** — Redis 原生 TCP，不支持 WebSocket。agent 需要能直接连接 Redis（通过 VPN 或 SSH 隧道） |
| 公网 IP | 🔴 **agent 需能访问 Redis IP** — 如果 agent 在 NAT 后且 Redis 无公网 IP，需要打洞或跳板 |
| 部署复杂度 | 🟢 **极低** — 单二进制，零配置即可运行。Agora 已有 RedisBus 实现 |
| 离线消息 | 🟡 **Pub/Sub: ❌ 不持久化**（消息即发即忘，订阅者不在线则丢失）。**Streams: ✅** 支持 Consumer Group 和持久化回放 |
| Python 客户端 | ✅ `redis-py`（asyncio 支持 `redis.asyncio`）。Agora 已在使用 |
| 多租户 | 🟡 **逻辑隔离** — 通过 key/channel prefix（如 `agora:{tenant}:ws`）实现。无原生多租户概念（Redis 是单 DB 实例或不同 DB index） |
| 资源消耗 | 🟢 **极低** — 空载 ~5MB RAM。Agora 已经部署 Redis，零额外成本 |
| 信令/数据 | ✅ **两者皆可** — Pub/Sub 适合信令（低延迟、不可靠广播），Streams 适合数据通道（持久化、consumer group） |

**总体评价**: 如果 Agora 已经用 Redis 做缓存/状态存储，复用 Pub/Sub 做信令是最经济的方案（当前做法）。但 NAT 穿透是硬伤——所有 agent 必须能直连 Redis。

**适合**: 内网部署、agent 都在同一网络或 VPN 内。Agora 当前方案

---

### 5. Apache Kafka

**协议**: 自研二进制协议（TCP），Kafka Wire Protocol

| 维度 | 评估 |
|------|------|
| NAT 穿透 | 🔴 **不支持** — 需要 agent 能直接连接所有 broker（advertised listeners），NAT 环境下非常痛苦。KIP-285（ZooKeeper 旁路）有所改善但不根本解决 |
| 公网 IP | 🔴 **需要每个 broker 有公网可达地址** — agent 直接连 broker，不像其他方案通过 central server 中转 |
| 部署复杂度 | 🔴 **极高** — 需要 JVM、ZooKeeper/KRaft、多节点。对 2 核 ARM 完全不现实。Kafka 在设计上就是为至少 3 节点的集群优化的 |
| 离线消息 | ✅ **优秀** — 基于日志的持久化是其核心设计，任意 offset 回放 |
| Python 客户端 | ✅ `confluent-kafka-python`（性能好但依赖 librdkafka C 库）、`aiokafka`（asyncio 原生） |
| 多租户 | 🟡 通过 ACL + topic prefix 实现，不如 RabbitMQ vhost 优雅 |
| 资源消耗 | 🔴 **极高** — 单 broker 最小 2GB heap，生产集群通常 16GB+。ARM 2核/11GB 机器上根本不合适 |
| 信令/数据 | 🟡 **偏数据通道** — 设计用于高吞吐日志流（MB/s 级别），低延迟点对点消息（信令）不是其强项。topic 数多时性能下降明显 |

**总体评价**: 对多 agent 信令通道来说完全是杀鸡用牛刀。Kafka 适合数据管道、事件溯源、日志聚合，不适合 agent 间任务调度、心跳这类小消息高频场景。

**不适合本场景** — 即使未来需要事件溯源，用 NATS JetStream 或 Redis Streams 也足够

---

### 6. MQTT (Mosquitto / EMQX)

**协议**: MQTT 3.1.1 / 5.0（基于 TCP，支持 WebSocket）

| 维度 | 评估 |
|------|------|
| NAT 穿透 | ✅ **WebSocket 可穿透** — MQTT over WebSocket 是标准特性（Mosquitto 和 EMQX 都支持），agent 通过 WS 主动连接 broker |
| 公网 IP | ✅ **只需 broker 有公网可达地址** |
| 部署复杂度 | 🟢 **Mosquitto: 极低**（C 写的单二进制，<1MB），🟡 **EMQX: 中低**（Erlang，Docker 镜像 ~50MB，但比 RabbitMQ 简单） |
| 离线消息 | ✅ **优秀（MQTT 核心特性）** — Persistent Session + QoS 1/2 + Retained Message。Session 恢复后自动推送离线消息 |
| Python 客户端 | ✅ `paho-mqtt`（成熟稳定）、`gmqtt`（asyncio 原生）、`aiomqtt` |
| 多租户 | 🟢 Mosquitto: 🟡（topic ACL 文件），🟢 **EMQX: ✅ 优秀**（内置多租户、RBAC、认证链） |
| 资源消耗 | 🟢 **Mosquitto: 极低**（~5MB RAM），🟡 EMQX 稍重但仍在百 MB 以内 |
| 信令/数据 | ✅ **两者皆可** — 设计上就是双向低带宽通信。QoS 0 适合高频信令，QoS 1/2 适合可靠数据。对二进制 payload 友好 |

**总体评价**: MQTT 的 Persistent Session + QoS 设计几乎就是为"agent 可能随时离线重连"场景设计的。协议极简，客户端实现遍布所有语言。Mosquitto 的资源占用极低。

**适合**: IoT/边缘 agent 场景，agent 网络不稳定但需要可靠消息投递

---

### 7. ZeroMQ

**协议**: 无 broker，对等通信库（TCP、IPC、inproc、PGM）

| 维度 | 评估 |
|------|------|
| NAT 穿透 | 🔴 **不擅长** — ZeroMQ 是 peer-to-peer 的，双方需要能互相连接。没有中心 broker 来做 NAT 穿透 |
| 公网 IP | 🔴 **通信双方至少一方需要公网可达**
| 部署复杂度 | 🟢 **零部署** — 只是一个 C 库，pip install pyzmq 即可。没有服务器进程 |
| 离线消息 | 🔴 **无** — ZeroMQ 设计哲学是"不持久化"，消息发送时对方不在线就丢失 |
| Python 客户端 | ✅ `pyzmq` — 最成熟的 ZeroMQ 绑定之一 |
| 多租户 | 🔴 **无原生支持** — 需要自己设计 pub/sub topic 命名约定 |
| 资源消耗 | 🟢 **极低** — 库开销，无进程 |
| 信令/数据 | ✅ **两者皆可** — 灵活但需要自己实现所有模式（请求-响应、发布-订阅、推-拉等） |

**总体评价**: 对 agent-broker 架构不适用——没有中心节点，所有 agent 必须互相发现。适合局域网内或已知地址的通信，不适合广域 agent 网络。

**不适合本场景** — 除非 agent 都在同一个局域网/集群内且不需要持久化

---

### 8. Centrifugo

**协议**: WebSocket / SSE / HTTP-streaming，基于自研协议或 GRPC

| 维度 | 评估 |
|------|------|
| NAT 穿透 | ✅ **天然穿透** — WebSocket 是核心传输方式，agent 作为 WS 客户端主动连接 |
| 公网 IP | ✅ **只需 Centrifugo 服务器有公网可达地址** |
| 部署复杂度 | 🟢 **低** — Go 单二进制文件，无外部依赖。内置管理 UI |
| 离线消息 | ✅ **原生支持** — 消息历史（自动或手动保存）、channel recovery（重连后自动恢复未读消息）、online/offline presence |
| Python 客户端 | 🟡 **有限** — Python SDK 存在（`centrifugal/pycent`）但生态不如 NATS/MQTT 丰富。主要通过 HTTP API 发送消息 |
| 多租户 | ✅ **原生支持** — namespace（不同配置）、channel prefix、JWT token 中包含 user/channel 权限 |
| 资源消耗 | 🟢 **极低** — Go 单进程，空载 ~20MB RAM |
| 信令/数据 | 🟡 **偏信令通道** — 设计用于实时用户消息。支持 JSON 和 binary payload，但不适合 MB 级数据传输 |

**总体评价**: 如果 Agora 的主要通信模式是 "Coordinator 推送消息给 agent + agent 通过 HTTP REST 上报"，Centrifugo 是天然选择。它的 channel recovery 机制非常适合 agent 短暂离线场景。

**适合**: 以推送为主的实时信令通道，agent 上报走 HTTP REST

---

### 9. ntfy

**协议**: 纯 HTTP（GET 长轮询 / SSE / WebSocket 推送，POST 发送）

| 维度 | 评估 |
|------|------|
| NAT 穿透 | ✅ **天然穿透** — 全 HTTP，agent 通过 GET SSE/WS 订阅，POST 发送消息 |
| 公网 IP | ✅ **只需 ntfy 服务器有公网可达地址** |
| 部署复杂度 | 🟢 **极低** — Go 单二进制，一行命令启动。支持 SQLite 自带数据库 |
| 离线消息 | ✅ **原生支持** — 消息持久化，可设置保留时间。支持消息缓存和重放 |
| Python 客户端 | 🟡 **有限** — 官方没有 Python SDK，但协议极简（HTTP POST/GET），`httpx` 或 `requests` 即可。第三方 `ntfy-py` 可用 |
| 多租户 | ✅ **原生支持** — 通过不同 topic 实现逻辑隔离。支持 access token 控制 topic 级别的读写权限 |
| 资源消耗 | 🟢 **极低** — 空载 ~10MB RAM |
| 信令/数据 | 🟡 **偏信令通道** — 协议简单，适合文本/JSON 通知消息。`attachment` 功能可传文件但非主要设计目标 |

**总体评价**: 最简单的 HTTP pub/sub 方案。协议极简到用 curl 就能收发消息。但缺少高级消息特性（无 ACK 机制、无消息确认、无 consumer group）。

**适合**: 原型验证、简单通知推送、不需要可靠性保证的场景

---

### 10. Webhook + HTTP Polling

**协议**: 纯 HTTP（POST webhook + GET polling）

| 维度 | 评估 |
|------|------|
| NAT 穿透 | 🟡 **半穿透** — Polling 端（agent）可以穿透（主动出站 GET），但 Webhook 端（Coordinator 推送给 agent）需要 agent 暴露 HTTP 端点 |
| 公网 IP | 🟡 **Webhook 模式下 agent 需要公网 IP 或端口映射**，Polling 模式不需要 |
| 部署复杂度 | 🟢 **零部署** — 无外部依赖，依赖已有的 HTTP 框架（FastAPI/Uvicorn，Agora 已有） |
| 离线消息 | 🟡 **需自己实现** — 配合数据库记录待投递消息，轮询时返回 |
| Python 客户端 | ✅ Agora 已有 FastAPI 基础设施 |
| 多租户 | 🟡 **需自己实现** — header/path 级别的 tenant 区分 |
| 资源消耗 | 🟢 **极低** — 无额外进程 |
| 信令/数据 | ✅ **两者皆可** — HTTP 可传任意 content type |

**总体评价**: 最简单但问题最多——Webhook 模式要求 agent 有公网可达端点，这完全违背"agent 可在任意网络"的假设。纯 Polling 模式虽然可行但延迟高、带宽浪费大。

**不适合** — 除非 agent 数量极少且都在内网

---

## 对比总表

| 平台 | NAT穿透 | 公网IP需求 | 部署复杂度 | 离线消息 | Python客户端 | 多租户 | 资源消耗 | 信令/数据 | 综合评分 |
|------|---------|-----------|-----------|---------|-------------|--------|---------|----------|---------|
| **NATS** | ✅ WS | 仅 server | 🟢 极低 | ✅ JetStream | ✅ nats-py | ✅ 原生 | 🟢 ~15-100MB | 两者皆可 | ⭐⭐⭐⭐⭐ |
| **MQTT (Mosquitto)** | ✅ WS | 仅 broker | 🟢 极低 | ✅ Persistent Session | ✅ paho-mqtt | 🟡 逻辑 | 🟢 ~5-50MB | 两者皆可 | ⭐⭐⭐⭐⭐ |
| **Centrifugo** | ✅ WS/SSE | 仅 server | 🟢 低 | ✅ Channel recovery | 🟡 有限 | ✅ 原生 | 🟢 ~20MB | 偏信令 | ⭐⭐⭐⭐ |
| **Redis Pub/Sub** | ⚠️ 需隧道 | agent 需可达 | 🟢 极低 | ⚠️ Streams 才有 | ✅ redis-py | 🟡 prefix | 🟢 ~5MB | 两者皆可 | ⭐⭐⭐⭐ |
| **Matrix** | ✅ HTTPS | 仅 homeserver | 🔴 高 | ✅ 原生 | ✅ matrix-nio | ✅ room | 🔴 ~400MB+ | 偏信令 | ⭐⭐⭐ |
| **ntfy** | ✅ HTTP | 仅 server | 🟢 极低 | ✅ 原生 | 🟡 httpx 即可 | ✅ topic | 🟢 ~10MB | 偏信令 | ⭐⭐⭐ |
| **RabbitMQ** | ⚠️ WS 插件 | 仅 broker | 🔴 中高 | ✅ Queue | ✅ aio-pika | ✅ vhost | 🟡 ~80-200MB | 两者皆可 | ⭐⭐⭐ |
| **ZeroMQ** | ❌ 不支持 | 至少一方 | 🟢 零部署 | ❌ 无 | ✅ pyzmq | ❌ 自建 | 🟢 零开销 | 两者皆可 | ⭐⭐ |
| **Kafka** | ❌ 不支持 | 每 broker | 🔴 极高 | ✅ 日志 | ✅ aiokafka | 🟡 ACL | 🔴 ~2GB+ | 偏数据 | ⭐ |
| **Webhook+Poll** | ⚠️ 半穿透 | agent 需公网 | 🟢 零部署 | 🟡 自建 | ✅ 原生 | 🟡 自建 | 🟢 零开销 | 两者皆可 | ⭐ |

---

## 场景分类推荐

### 场景 A: 内网部署（所有 agent 在同一网络/VPN）

**推荐**: **Redis Pub/Sub + Streams**（当前方案）

理由: Agora 已有 Redis 基础设施，零额外部署。Pub/Sub 做信令，Streams 做持久化队列。简单有效。

### 场景 B: 广域 agent（agent 分散在任意网络，NAT 后）

**推荐**: **NATS (WebSocket)** 或 **MQTT (Mosquitto + WS)**

理由: 两者都是轻量级单二进制部署，agent 通过 WebSocket 主动连接，天然穿透 NAT。都支持离线消息重放。

- **NATS** 更适合：需要 request-reply 模式、KV store、work queue 等高级特性
- **MQTT** 更适合：agent 极不稳定（移动网络）、需要 QoS 分级、已有 IoT 基础设施

### 场景 C: 跨组织/去中心化

**推荐**: **Matrix**

理由: 唯一的去中心化联邦方案。多个组织的 Agora 实例可以通过 Matrix 联邦互通，每个组织运行自己的 homeserver。

### 场景 D: 最简原型

**推荐**: **ntfy**

理由: 用 curl 就能收发消息，10 分钟部署。适合验证 agent 通信模式。

---

## 最终推荐方案

### 🥇 首选: NATS (WebSocket 接入)

```
Agent (任意网络) ──WS──→ NATS Server (公网/VPS) ←──WS── Coordinator
```

**选择理由**:

1. **NAT 穿透**: agent 通过 WebSocket 主动连接 NATS Server，零配置穿透任何防火墙
2. **部署轻量**: 单 Go 二进制，空载 15MB 内存，ARM 架构原生支持
3. **功能完备**: Core NATS 做信令（pub/sub + request-reply），JetStream 做持久化（离线消息、work queue）
4. **多租户原生**: Account 级别的隔离，适合 SaaS 场景
5. **Python 客户端优秀**: `nats-py` 是纯 Python + asyncio，与 Agora 技术栈完美匹配
6. **CNCF 项目**: 生产验证，社区活跃，长期可维护

**Agora 集成方案**:

```python
# 现有 BroadcastBus 接口不变，新增 NatsBus 实现
class NatsBus(BroadcastBus):
    """NATS-based broadcast bus replacing RedisBus when agents are remote."""
    
    async def publish(self, tenant: str, message: dict, exclude: list[str] | None = None):
        subject = f"agora.{tenant}.ws"
        await self._js.publish(subject, json.dumps(envelope).encode())
    
    async def subscribe(self, tenant: str, handler: BroadcastHandler):
        subject = f"agora.{tenant}.ws"
        sub = await self._js.subscribe(subject, durable=f"agora-{tenant}")
        # process messages in background task
```

**迁移路径**: `LocalBus` → `RedisBus`（当前）→ `NatsBus`（广域 agent）— BroadcastBus 接口不变，只需换实现

### 🥈 备选: MQTT (Mosquitto)

如果团队更熟悉 MQTT 协议或需要极致的资源节省（Mosquitto 仅 5MB），MQTT 是同样优秀的选择。

### 🥉 当前保留: Redis Pub/Sub + Streams

如果短期内所有 agent 都在内网/VPN，当前 Redis 方案完全够用，无需更换。

---

## 附录: 关键决策树

```
所有 agent 都在同一网络/VPN？
├── 是 → 继续用 Redis Pub/Sub + Streams（当前方案，零成本）
└── 否 → agent 分散在 NAT 后？
    ├── 需要跨组织联邦？
    │   └── 是 → Matrix（唯一去中心化方案）
    ├── 需要极简 HTTP 协议？
    │   └── 是 → ntfy（原型验证）
    └── 需要可靠的 agent-broker 通信？
        ├── 偏好功能丰富 → NATS（JetStream, KV, Work Queue）
        └── 偏好协议极简 → MQTT (Mosquitto)
```

---

> **本文档是对主流消息平台的调研分析，具体选型需结合 Agora 的实际部署拓扑和运维能力决定。**
