# API 调度网关

高性能 API 代理服务，支持负载均衡、健康检查、流式响应和多密钥管理。

## 功能清单

- ✅ 请求转发 - 路由到后端服务
- ✅ 负载均衡 - 轮询 + IP 会话保持
- ✅ 健康检查 - 后台定时检测后端状态
- ✅ 可视化仪表板 - 实时显示健康状态
- ✅ API 密钥认证 - 全局/后端特定密钥
- ✅ 流式响应 - SSE / NDJSON 零缓冲转发

## 快速开始

### 安装依赖

```bash
cd server
pip install -r requirements.txt
```

### 配置环境变量

```bash
cp .env.example .env
```

编辑 `server/.env`:
```bash
BACKEND_API_KEY=your-secret-key-here
BACKEND_AUTH_MODE=Authorization
```

### 配置后端

编辑 `server/config/backends.json`:
```json
{
  "services": {
    "google": {
      "model": {
        "gemma-4-26b-a4b-it": {
          "backends": [
            {
              "id": "backend-1",
              "name": "后端节点1",
              "url": "http://192.168.1.10:5000",
              "weight": 1,
              "api_key": "sk-backend-key",
              "auth_mode": "Authorization"
            }
          ]
        }
      }
    }
  }
}
```

### 启动

```bash
cd server
python main.py
```

访问仪表板：http://localhost:8000

## 配置说明

### 环境变量 (.env)

| 变量 | 默认值 | 说明 |
|------|--------|------|
| PORT | 8000 | 服务端口 |
| LOG_LEVEL | INFO | 日志级别 |
| BACKENDS_CONFIG_PATH | ./config/backends.json | 后端配置路径 |
| HEALTH_CHECK_INTERVAL | 30 | 健康检查间隔(秒) |
| REQUEST_TIMEOUT | 30 | 请求超时(秒) |
| MAX_CONNECTIONS | 100 | 连接池最大连接数 |
| MAX_KEEPALIVE_CONNECTIONS | 20 | 保活连接数 |
| BACKEND_API_KEY | - | 全局 API 密钥 |
| BACKEND_AUTH_MODE | Authorization | 认证方式 |

### 后端配置 (backends.json)

```json
{
  "services": {
    "服务名": {
      "model": {
        "模型名": {
          "backends": [
            {
              "id": "唯一标识",
              "name": "显示名称",
              "url": "http://IP:PORT",
              "weight": 1,
              "api_key": "可选后端密钥",
              "auth_mode": "Authorization 或 x-api-key"
            }
          ]
        }
      }
    }
  }
}
```

**密钥优先级**：后端特定密钥 > 全局密钥

## API 端点

| 端点 | 说明 | 认证 |
|------|------|------|
| GET /health | 健康检查 | ❌ |
| GET /ready | 就绪检查 | ❌ |
| GET /api/health/status | 所有后端状态 | ❌ |
| GET /api/health/status/{service} | 服务状态 | ✅ |
| GET /{service}/{model}/... | 转发请求 | ✅ |

**认证方式**：
```
Authorization: Bearer <API_KEY>
# 或
X-API-Key: <API_KEY>
```

## 并发配置

```bash
# 低并发 (<100 req/s)
MAX_CONNECTIONS=100
MAX_KEEPALIVE_CONNECTIONS=20

# 中等并发 (100-1000 req/s)
MAX_CONNECTIONS=200
MAX_KEEPALIVE_CONNECTIONS=50

# 高并发 (>1000 req/s)
MAX_CONNECTIONS=500
MAX_KEEPALIVE_CONNECTIONS=100
```

## 项目结构

```
new-api-proxy/
├── server/
│   ├── main.py              # FastAPI 主应用
│   ├── config.py            # 配置管理
│   ├── model.py             # 数据模型
│   ├── backends_manager.py # 后端管理器
│   ├── health_checker.py   # 健康检查
│   ├── requirements.txt     # Python依赖
│   ├── .env.example         # 环境变量示例
│   ├── config/
│   │   └── backends.json    # 后端配置
│   └── static/
│       └── index.html       # 前端仪表板
├── client/
│   └── index.html           # 可选前端
└── README.md               # 本文档
```

## 生产部署

### Gunicorn 多进程

```bash
pip install gunicorn
gunicorn main:app -w 4 -b 0.0.0.0:8000 --timeout 120
```

### Nginx 反向代理

```nginx
upstream api_proxy {
    server localhost:8000;
}

server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://api_proxy;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

## 版本历史

- **v2.0.0** - 流式响应优化，SSE/NDJSON 支持，全局连接池复用，并发优化

---
# API 调度网关 - 完整部署指南

## 📋 功能清单

✅ **请求转发** - 将请求路由到对应的后端服务  
✅ **负载均衡** - 轮询策略分配请求  
✅ **会话保持** - 同IP始终转发到同一后端  
✅ **健康检查** - 后台定时检查所有后端状态  
✅ **可视化仪表板** - 实时显示所有后端的健康状态  
✅ **分组管理** - 按服务/模型组织后端  
✅ **API 密钥认证** - 除健康检查端点外，其他接口需要认证  
✅ **后端特定密钥** - 每个后端可独立配置自己的 API 密钥，支持多个密钥管理器  
✅ **流式响应** - 自动检测并转发 Server-Sent Events (SSE) 和 NDJSON 流式响应  

---

## 🚀 快速开始

### 步骤1: 安装依赖

```bash
cd server
pip install -r requirements.txt
```

### 步骤2: 配置环境变量 (密钥认证)

复制并编辑环境变量文件：

```bash
cd server
cp .env.example .env
```

编辑 `server/.env`：

```bash
# 应用配置
PORT=8000
LOG_LEVEL=INFO

# 后端配置文件路径
BACKENDS_CONFIG_PATH=./config/backends.json

# 健康检查间隔(秒)
HEALTH_CHECK_INTERVAL=30

# 请求超时
REQUEST_TIMEOUT=30
HEALTH_CHECK_TIMEOUT=5

# API 密钥认证
BACKEND_API_KEY=your-secret-key-here
BACKEND_AUTH_MODE=Authorization
```

### 步骤3: 配置后端

编辑 `server/config/backends.json` 添加您的后端地址：

**方案 1 - 所有后端使用相同密钥（全局密钥）：**

```json
{
  "services": {
    "google": {
      "models": {
        "gemma-4-26b-a4b-it": {
          "backends": [
            {
              "id": "backend-1",
              "name": "后端节点1",
              "url": "http://192.168.1.10:5000",
              "weight": 1
            }
          ]
        }
      }
    }
  }
}
```

**方案 2 - 每个后端使用不同密钥（后端特定密钥）⭐ 推荐：**

```json
{
  "services": {
    "google": {
      "models": {
        "gemma-4-26b-a4b-it": {
          "backends": [
            {
              "id": "backend-1",
              "name": "后端节点1",
              "url": "http://192.168.1.10:5000",
              "weight": 1,
              "api_key": "sk-backend1-unique-key-abc123",
              "auth_mode": "Authorization"
            },
            {
              "id": "backend-2",
              "name": "后端节点2",
              "url": "http://192.168.1.11:5000",
              "weight": 1,
              "api_key": "sk-backend2-unique-key-xyz789",
              "auth_mode": "x-api-key"
            }
          ]
        }
      }
    }
  }
}
```

### 步骤4: 启动网关

```bash
cd server
python main.py
```

预期输出：
```
✅ 配置加载成功
🚀 应用启动中...
🚀 启动健康检查 (间隔: 30秒)
✅ 应用启动完成
启动服务器: 0.0.0.0:8000
```

### 步骤5: 访问仪表板

打开浏览器访问：http://localhost:8000

---

## 📊 核心功能详解

### 1. 请求转发

**路由规则:**
```
HTTP_METHOD /service/model[/path]
例如: 
  GET /google/gemma-4-26b-a4b-it/v1/models
  POST /google/gemma-4-26b-a4b-it/v1/chat/completions
  DELETE /google/gemma-4-26b-a4b-it/v1/files/file_id
```

**支持的 HTTP 方法:**
- 🔵 `GET` - 查询
- 🟢 `POST` - 创建/执行
- 🟡 `PUT` - 更新
- 🔴 `DELETE` - 删除
- 🟣 `PATCH` - 部分更新
- ⚪ `HEAD` - 仅获取头信息
- ⚫ `OPTIONS` - 获取通讯选项

**工作流程:**
1. 接收客户端请求到 `/{service}/{model}[/{path...}]`
2. 保留原始 HTTP 方法（GET、POST 等）
3. 基于 IP 和轮询策略选择后端
4. 使用相同的 HTTP 方法转发请求到选定的后端服务
5. 返回后端响应

**示例:**
```bash
# 使用 Authorization header
curl -X POST http://localhost:8000/google/gemma-4-26b-a4b-it \
  -H "Authorization: Bearer your-secret-key-here" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Hello"}'

# 或使用 X-API-Key header
curl -X POST http://localhost:8000/google/gemma-4-26b-a4b-it \
  -H "X-API-Key: your-secret-key-here" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Hello"}'
```

### 2. 负载均衡策略

**轮询 + IP 映射:**
- 请求按顺序轮询分配给后端
- 同一 IP 的请求始终映射到同一后端（会话保持）
- 如果后端不可用，自动切换到其他后端

**配置权重 (可选):**
```json
{
  "id": "backend-1",
  "name": "后端节点1",
  "url": "http://...",
  "weight": 2  // 权重按轮询顺序应用
}
```

### 3. 多密钥管理⭐ 新功能

**场景：** 多个后端由不同的服务商提供或需要不同的凭证

**配置方式：**

在 `backends.json` 中为每个后端分别配置密钥：

```json
{
  "services": {
    "llm": {
      "models": {
        "gpt-4": {
          "backends": [
            {
              "id": "openai-backend",
              "name": "OpenAI",
              "url": "https://api.openai.com",
              "api_key": "sk-openai-prod-key-12345",
              "auth_mode": "Authorization"
            },
            {
              "id": "azure-backend", 
              "name": "Azure OpenAI",
              "url": "https://myresource.openai.azure.com",
              "api_key": "azure-api-key-67890",
              "auth_mode": "x-api-key"
            }
          ]
        }
      }
    }
  }
}
```

**工作原理：**

1. 客户端使用**全局密钥**请求网关：`Authorization: Bearer your-secret-key`
2. 网关将请求转发到**后端指定的密钥**：`Authorization: Bearer sk-openai-prod-key`
3. 这样可以**隐藏内部密钥**，只暴露一个统一的全局密钥给客户端

**优势：**

- 🔐 **安全性** - 客户端只需知道网关的密钥，后端密钥保密
- 🔄 **灵活性** - 可独立更新每个后端的密钥，不影响其他后端
- 🔗 **多服务商** - 支持集成多个不同的 API 服务商
- 🎯 **按需认证** - 每个后端使用最合适的认证方式

### 4. 健康检查

**检查机制:**
- 定时向每个后端发送 `GET /health` 请求
- HTTP 200 = 健康，否则 = 不健康
- 超时时间: 5 秒
- 检查间隔: 可配置 (默认 30 秒)

**实时状态:**
- 🟢 **healthy** - 后端正常
- 🔴 **unhealthy** - 后端不可用
- ⚪ **unknown** - 未检查

### 5. 可视化仪表板

**页面位置:** http://localhost:8000/

**功能:**
- 按服务分组显示所有后端
- 实时显示健康状态和响应时间
- 自动刷新 (5 秒间隔)
- 整体可用率统计

### 6. 流式响应支持⭐

**自动检测和转发流式响应** - 适配 LLM API（OpenAI、Google、Gemini 等）

**支持的流式格式：**

1️⃣ **Server-Sent Events (SSE)** - `text/event-stream`
```bash
curl -X POST http://localhost:8000/openai/gpt-4/v1/chat/completions \
  -H "Authorization: Bearer your-key" \
  -H "Content-Type: application/json" \
  -d '{"model": "gpt-4", "stream": true, "messages": [...]}'

# 响应示例：
# data: {"choices":[{"delta":{"content":"Hello"},"index":0}]}
# data: {"choices":[{"delta":{"content":" world"},"index":0}]}
```

2️⃣ **NDJSON (Newline Delimited JSON)** - `application/x-ndjson`
```bash
curl -X POST http://localhost:8000/service/model/v1/stream \
  -H "Authorization: Bearer your-key" \
  -H "Content-Type: application/json" \
  -d '{"stream": true, "parameters": [...]}'
```

**工作原理：**

- 🔍 **自动检测** - 检查响应的 `Content-Type` 头
- ⚡ **零缓冲** - 流式内容直接从后端转发到客户端
- 🔐 **保持认证** - 所有安全检查和密钥管理都适用
- ✨ **实时性能** - 无延迟地流式传输数据

**与非流式响应的区别：**

| 特点 | 流式响应 | 非流式响应 |
|-----|---------|----------|
| **检测** | `text/event-stream` 或 `application/x-ndjson` | 其他类型（JSON、HTML 等） |
| **缓冲** | 不缓冲，即时转发 | 完整读取后返回 |
| **适用场景** | LLM 流式输出、实时数据推送 | 标准 API 响应 |
| **延迟** | 极低（毫秒级） | 可能较高（需等待完整响应） |

---

## 🔧 配置说明

### 环境变量 (.env)

```bash
# 应用端口
PORT=8000

# 后端配置文件路径
BACKENDS_CONFIG_PATH=./config/backends.json

# 健康检查间隔 (秒)
HEALTH_CHECK_INTERVAL=30

# 请求超时 (秒)
REQUEST_TIMEOUT=30
HEALTH_CHECK_TIMEOUT=5

# 🔐 API 密钥认证
BACKEND_API_KEY=your-secret-key-here
BACKEND_AUTH_MODE=Authorization  # 或 x-api-key
```

**API 密钥说明:**
- `BACKEND_API_KEY` - **全局 API 密钥**，所有客户端请求时使用
- `BACKEND_AUTH_MODE` - **全局认证方式**：`Authorization` (Bearer token) 或 `x-api-key`
- 支持**后端特定密钥**：在 `backends.json` 中为每个后端配置 `api_key` 和 `auth_mode`
- 后端特定密钥**优先于**全局密钥
- 留空 `BACKEND_API_KEY` 可禁用认证（仅用于开发环境）
- `GET /api/health/status` 端点始终无需认证

### 后端配置 (backends.json)

```json
{
  "services": {
    "服务名": {
      "models": {
        "模型名": {
          "backends": [
            {
              "id": "唯一标识",
              "name": "显示名称",
              "url": "http://IP:PORT",
              "weight": 1,
              "api_key": "sk-backend-specific-key (可选)",
              "auth_mode": "Authorization 或 x-api-key (可选)"
            }
          ]
        }
      }
    }
  }
}
```

**字段说明：**

| 字段 | 必需 | 说明 |
|-----|------|------|
| id | ✅ | 后端的唯一标识符 |
| name | ✅ | 可读的后端名称 |
| url | ✅ | 后端服务地址 |
| weight | ❌ | 负载均衡权重 (默认: 1) |
| api_key | ❌ | 该后端的 API 密钥（优先于全局密钥） |
| auth_mode | ❌ | 该后端的认证方式（优先于全局设置） |

**🔑 密钥优先级：**

1. 使用**后端特定的密钥**（如果配置了 `api_key`）✅ **最优先**
2. 否则使用**全局密钥**（`BACKEND_API_KEY` 环境变量）✅ **备选**
3. 都没配置则不添加认证头 ⚠️ **不安全**

---

## 📡 API 端点

### 应用健康检查
```
GET /health
GET /ready
```

**响应:**
```json
{
  "status": "ok",
  "service": "api-proxy-gateway",
  "version": "1.0.0"
}
```

### 转发请求到后端⭐ (需要 API 密钥)
```
HTTP_METHOD /{service}/{model}[/{path...}]
Authorization: Bearer <API_KEY>
```

**支持所有 HTTP 方法的示例:**

1️⃣ **GET - 查询模型列表**
```bash
curl -X GET http://localhost:8000/google/gemma-4-26b-a4b-it/v1/models \
  -H "Authorization: Bearer your-secret-key-here"
```

2️⃣ **POST - 执行 API 调用**
```bash
curl -X POST http://localhost:8000/google/gemma-4-26b-a4b-it/v1/chat/completions \
  -H "Authorization: Bearer your-secret-key-here" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Hello"}'
```

3️⃣ **DELETE - 删除资源**
```bash
curl -X DELETE http://localhost:8000/openai/gpt-4/v1/files/file_id \
  -H "Authorization: Bearer your-secret-key-here"
```

4️⃣ **PUT - 更新资源**
```bash
curl -X PUT http://localhost:8000/openai/gpt-4/v1/files/file_id \
  -H "Authorization: Bearer your-secret-key-here" \
  -H "Content-Type: application/json" \
  -d '{"name": "new-name"}'
```

**认证说明：**

网关会自动将指定的密钥转发给后端。认证方式由后端配置决定：

1️⃣ **Authorization Header (Bearer Token)** - 推荐
```
Authorization: Bearer your-api-key
```

2️⃣ **X-API-Key Header**
```
X-API-Key: your-api-key
```

**密钥来源优先级：**
- 🔴 **优先使用**：后端特定密钥（`backends.json` 中的 `api_key`）
- 🟡 **次选**：全局密钥（环境变量 `BACKEND_API_KEY`）
- ⚪ **都没有**：不添加认证头（不推荐）

### 获取所有健康状态 ✅ (无需 API 密钥)
```
GET /api/health/status
```

**响应:**
```json
{
  "service": "api-proxy-gateway",
  "type": "health_status",
  "data": {
    "google": {
      "gemma-4-26b-a4b-it": [
        {
          "id": "backend-1",
          "name": "后端节点1",
          "url": "http://...",
          "status": "healthy",
          "response_time_ms": 45.3,
          "last_check": "2024-04-14T10:30:00"
        }
      ]
    }
  }
}
```

### 获取服务的健康状态⭐ (需要 API 密钥)
```
GET /api/health/status/{service}
Authorization: Bearer <BACKEND_API_KEY>
```

**示例:**
```
GET /api/health/status/google
Authorization: Bearer your-secret-key-here
```

---

## 🐛 故障排查

### 问题1: "配置文件不存在"

**解决:**
```bash
# 确保配置文件存在
ls server/config/backends.json

# 或创建配置文件夹
mkdir -p server/config
```

### 问题2: 后端显示 "unhealthy"

**检查清单:**
1. 后端服务是否已启动？
2. 后端是否实现了 `/health` 端点？
3. 网关是否可访问后端地址？
4. 防火墙/网络连接是否正常？

**测试连接:**
```bash
curl http://backend-url:port/health
```

### 问题3: CORS 错误

**解决:**
网关已配置允许所有跨域请求，如需限制：

编辑 `server/main.py`:
```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://yourdomain.com"],  # 改为具体域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

---

## 🏗️ 项目结构

```
new-api-proxy/
├── server/
│   ├── main.py                 # 主应用
│   ├── config.py               # 配置管理
│   ├── models.py               # 数据模型
│   ├── backends_manager.py     # 后端管理器
│   ├── health_checker.py       # 健康检查
│   ├── requirements.txt        # Python依赖
│   ├── .env.example            # 环境变量示例
│   ├── config/
│   │   └── backends.json       # 后端配置
│   └── static/
│       └── index.html          # 前端仪表板
├── client/
│   └── index.html              # 可选：独立前端
└── README.md                   # 本文档
```

---

## 📈 生产部署建议

### 1. 使用 Gunicorn 运行

```bash
pip install gunicorn
gunicorn main:app -w 4 -b 0.0.0.0:8000 --timeout 120
```

### 2. 配置反向代理 (Nginx)

```nginx
upstream api_proxy {
    server localhost:8000;
}

server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://api_proxy;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### 3. 使用 Systemd 管理服务

创建 `/etc/systemd/system/api-proxy.service`:
```ini
[Unit]
Description=API Proxy Gateway
After=network.target

[Service]
Type=simple
WorkingDirectory=/path/to/new-api-proxy/server
ExecStart=/usr/bin/python main.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

启动服务:
```bash
systemctl enable api-proxy
systemctl start api-proxy
```

### 4. 监控和日志

```bash
# 查看日志
journalctl -u api-proxy -f

# 配置日志轮转
# 编辑 config.py 中的日志配置
```

---

## 🔐 安全性建议

1. **限制 CORS 源:**
   ```python
   allow_origins=["https://trusted-domain.com"]
   ```

2. **添加认证:**
   ```python
   @app.post("/{service}/{model}")
   async def forward_request(request: Request, x_api_key: str = Header(None)):
       if x_api_key != "your-secret-key":
           raise HTTPException(status_code=401)
   ```

3. **速率限制:**
   ```bash
   pip install slowapi
   ```

4. **HTTPS:**
   在 Nginx 或负载均衡器上配置 SSL 证书

---

## 📞 调试技巧

### 启用详细日志

编辑 `.env`:
```bash
LOG_LEVEL=DEBUG
```

### 直接测试后端连接

```bash
# 查看所有后端状态
curl http://localhost:8000/api/health/status | jq

# 查看特定服务
curl http://localhost:8000/api/health/status/google | jq

# 转发测试请求
curl -X POST http://localhost:8000/google/gemma-4-26b-a4b-it \
  -H "Content-Type: application/json" \
  -d '{"message": "test"}' \
  -v
```

### 查看请求追踪

每个请求都有唯一的 `X-Request-ID` 头，便于追踪：

```bash
curl -i http://localhost:8000/api/health/status | grep X-Request-ID
```

---

## 🎯 下一步

1. **自定义健康检查:** 修改 `health_checker.py` 中的 `check_backend_health()` 方法
2. **添加认证:** 在 `main.py` 中实现 JWT 或其他认证机制
3. **集成监控:** 连接 Prometheus/Grafana 收集指标
4. **性能优化:** 添加缓存层（Redis）或请求批处理

---

**版本:** 1.0.0  
**最后更新:** 2024年4月14日
