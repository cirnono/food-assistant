# 内部审计报告（internal audit）

> 本文档面向项目维护者，记录公开发布前的只读审计结论。
> 生成时间：2026-07-31 · 审计基线版本：0.20.1
>
> 本文档可以随仓库公开，但不得包含任何真实 Token、API Key 或内网 IP 的具体值。
> 审计过程只报告敏感信息的「文件:行号」，不输出内容。

## 1. 当前架构

- **形态**：单容器 FastAPI 应用（Python 3.12-slim + uvicorn），Docker Compose 部署。
- **数据**：SQLite（`DATA_DIR/food-assistant.db`，WAL 模式），SQLAlchemy 2.0 ORM，
  启动时 `create_all` + 少量命令式迁移（`ensure_schema_migrations`）。
- **上游**：
  - Mealie（菜谱数据库），通过 `MEALIE_BASE_URL` + Bearer Token 调用。
  - Ollama（AI 引擎，远程，`qwen3:8b`），通过 `/api/chat` 调用。
  - GitHub 菜谱源（用户配置的公开仓库，如 HowToCook），本地 clone 到 `DATA_DIR/sources/`。
- **核心业务链路**：
  1. `github_sources.py` 拉取/同步 GitHub 菜谱源到本地。
  2. `import_queue.py` 导入队列：标准化（`ollama_structured_chat`）→ 质量门
     （`recipe_quality.apply_recipe_quality_gate`）→ 人工审核（`/review`）或自动批准 →
     导入 Mealie → 回读验证 → 去重 → 失败重试。
  3. `review_ui.py` 提供 `/review` 网页审核界面（静态 HTML，JS 直接调 API）。
  4. `inventory.py` / `recommendations.py` 提供库存与推荐功能。
- **认证**：`api_token_middleware` 保护全部 `/api/v1/*`（Bearer 或
  `X-Food-Assistant-Token` 头），`/healthz`、`/readyz`、`/docs`、`/review` 不设防。
- **AI 调用点**：`ollama_structured_chat()` 仅被 3 处调用：
  - `ai_recipes.py:912`（`/api/v1/ai/recipe/normalize`）
  - `import_queue.py:1099`、`import_queue.py:1162`（标准化主流程 + 校验失败重试）

### 模块清单

| 文件 | 职责 | 路由前缀 |
|---|---|---|
| `main.py` | 应用入口、健康检查、Mealie 状态 | `/`、`/healthz`、`/readyz` 等 |
| `api_auth.py` | API Token 认证中间件 | — |
| `ollama_client.py` | Ollama 客户端（结构化 chat） | — |
| `mealie_client.py` | Mealie HTTP 客户端 | — |
| `mealie_importer.py` | Mealie 导入/回读验证/幂等 | — |
| `mealie_entities.py` | 实体解析（食材/单位/标签） | — |
| `mealie_import_records.py` | 导入记录表（幂等键） | — |
| `import_queue.py` | 导入队列与批量流程 | `/api/v1/import-jobs` |
| `ai_recipes.py` | 单条菜谱标准化 | `/api/v1/ai`、`/api/v1/integrations/ollama` |
| `github_sources.py` | GitHub 菜谱源 | `/api/v1/sources` |
| `review_ui.py` | `/review` 网页 | `/review`（静态） |
| `recipe_quality.py` | 质量门 | — |
| `recipe_semantics.py` | 语义规则引擎 | — |
| `inventory.py` | 库存 CRUD | `/api/v1/inventory` |
| `recommendations.py` | 推荐 | `/api/v1/recommendations` |
| `database.py` / `models.py` / `schemas.py` | 数据层 | — |

## 2. 当前配置入口

全部通过环境变量（Compose 注入），无配置文件：

| 变量 | 用途 | 备注 |
|---|---|---|
| `APP_UID` / `APP_GID` | 容器内用户 | compose build arg |
| `TZ` | 时区 | — |
| `DATA_DIR` | 数据目录（默认 `/data`） | 容器内挂载点 |
| `DATABASE_PATH` | 数据库文件路径 | 默认 `DATA_DIR/food-assistant.db` |
| `MEALIE_BASE_URL` | Mealie 地址 | 代码默认值含内网 IP |
| `MEALIE_TOKEN_FILE` | Mealie Token 文件 | 默认 `/run/secrets/mealie_token` |
| `MEALIE_TIMEOUT_SECONDS` | Mealie 超时 | 默认 90 |
| `OLLAMA_BASE_URL` | Ollama 地址 | 代码默认值含内网 IP |
| `OLLAMA_MODEL` | 模型名 | 默认 `qwen3:8b` |
| `OLLAMA_TIMEOUT_SECONDS` | AI 生成超时 | 默认 180 |
| `OLLAMA_KEEP_ALIVE` | keep_alive | 默认 `10m` |
| `OLLAMA_NUM_CTX` | 上下文长度 | 默认 8192（与需求文档的 6144 不一致，需与部署核对） |
| `FOOD_ASSISTANT_API_TOKEN` / `FOOD_ASSISTANT_API_TOKEN_FILE` | 本服务 API Token | 或候选路径 |

Secrets 通过 Docker Compose `secrets:` 注入（`/run/secrets/mealie_token`、
`/run/secrets/food_assistant_api_token`）。

## 3. 安全风险

按严重程度排序：

1. **硬编码内网 IP 默认值（高）**：
   - `ollama_client.py:13`（`OLLAMA_BASE_URL` 默认值）
   - `mealie_client.py:13`、`mealie_importer.py:20`（`MEALIE_BASE_URL` 默认值）
   - `import_queue.py:4041`（`unload_ollama_model` 默认 `http://127.0.0.1:11434`）
   - 环境变量可覆盖，但代码兜底会泄露内网拓扑，且会作为兜底连接错误目标。
   - **处置**：改为通用占位符（如 `http://host.docker.internal:11434`）。
2. **本地绝对路径（中）**：
   - `api_auth.py:14-17`（通用容器 secret 路径与旧的主机专用 secret 路径）
   - `mealie_importer.py:50-58`、`mealie_client.py:19`（`/run/secrets/mealie_token`）
   - 主机专用路径公开后无意义且会泄露内部结构。
   - **处置**：保留 `/run/secrets` 这类通用容器路径，移除主机专用候选。
3. **浏览器 localStorage 存 API Token（中）**：`review_ui.py:909-929` 将用户输入的
   Food Assistant Token 明文存入 `localStorage`（XSS 可读）。这是既有 UX 取舍；
   AI API Key 从未进入浏览器，本仓库亦不会新增此行为。
4. **上游错误透传（低-中）**：`main.py:146-148`、`mealie_client.raise_for_mealie_error`
   会把上游响应体原样放进 API 错误。Mealie 响应一般不回显 Token，但发布前应核对
   接口错误不包含请求头/密钥。
5. **未设认证的端点**：`/healthz`、`/readyz`、`/docs`、`/review` 无认证（预期行为）。
   `/review` 页面本身可打开，但无 Token 时读不到业务数据；公网暴露时必须靠反代/隧道保护。
6. **token 日志泄漏**：代码未见把 token 打入日志；阶段 8 会再验证。

## 4. 开源阻碍

1. **没有 Git 仓库**：当前无 `.git`，需要 `git init`。
2. **无 `.gitignore` / `.dockerignore` 不完整**：现有 `.dockerignore` 只有 7 行；
   仓库目录中散落 75 个 `*.bak` 历史备份、4 个 `backup-v*` 目录、`__pycache__`。
3. **硬编码内网 IP 与绝对路径**（见上），发布前必须替换为占位符。
4. **无测试**：`pytest` 体系完全缺失；发布开源必须补齐 provider 与回归测试。
5. **无 `pyproject.toml`**：只有 `requirements.txt`，缺少 lint/test 工具链配置。
6. **无 `.env.example`**：Compose 依赖 `.env` 但仓库中没有示例。
7. **无 README / LICENSE / 文档**：`docs/` 为空目录。
8. **AI 配置是 Ollama 专属**：`ollama_structured_chat` 硬编码 Ollama 调用细节，
   需抽象出 provider 层以支持 OpenAI-compatible 服务。
9. **`.env` 与 secrets 位于部署目录内**：必须确保 `.env` 不被提交；旧版
   `compose.auth.yaml` 曾引用主机专用绝对路径。

## 5. API 抽象设计

### 5.1 LLM Provider

目标：`ollama_structured_chat()` 从业务逻辑解耦。

```
app/llm/
  __init__.py       # 导出 create_llm_provider / get_llm_provider
  base.py           # StructuredChatProvider Protocol + 统一返回
  config.py         # LLMSettings：新 LLM_* 变量 + 旧 OLLAMA_* 兼容
  factory.py        # 按 LLM_PROVIDER 构建 provider
  ollama.py         # OllamaProvider（/api/chat）
  openai_compatible.py  # OpenAIProvider（/v1/chat/completions）
  errors.py         # LLMProviderError + 基础设施错误分类
```

统一接口：

```python
class StructuredChatProvider(Protocol):
    async def structured_chat(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_schema: dict[str, Any],
    ) -> dict[str, Any]: ...
```

- 统一配置 `LLM_PROVIDER` / `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_API_KEY_FILE` /
  `LLM_MODEL` / `LLM_TIMEOUT_SECONDS` / `LLM_CONNECT_TIMEOUT_SECONDS` /
  `LLM_MAX_TOKENS` / `LLM_TEMPERATURE` / `LLM_CONTEXT_LENGTH` /
  `LLM_KEEP_ALIVE` / `LLM_UNLOAD_AFTER_BATCH`。
- 旧变量兼容：`OLLAMA_BASE_URL` / `OLLAMA_MODEL` / `OLLAMA_TIMEOUT_SECONDS` /
  `OLLAMA_NUM_CTX` / `OLLAMA_KEEP_ALIVE`（新变量优先，旧变量兜底，仅一次 deprecated 日志）。
- `LLM_API_KEY_FILE` 优先级高于 `LLM_API_KEY`，读取后 `strip()`。
- 结构化输出降级链：`response_format=json_schema` → `json_object` → 纯文本 + JSON 提取
  （复用 `ollama_client._extract_json_object` 的既有可靠逻辑）。
- 错误统一转 `LLMProviderError`，并保留基础设施错误分类（CUDA OOM、连接失败、
  RemoteProtocolError、timeout、connection refused、upstream 5xx），
  供批量流程 `is_ollama_infrastructure_error` 识别后立即停止/重排队。
- 旧 `app/ollama_client.py` 保留为兼容包装器（内部转调新 provider），
  业务调用点逐步迁移到 provider factory。

### 5.2 系统配置接口

新增（受现有 API Token 保护）：

- `GET /api/v1/system/llm-status`：只返回 provider、base_url（仅协议/主机/端口）、
  model、configured、api_key_configured、context_length、max_tokens、timeout_seconds、
  legacy_config_in_use、provider_capabilities。严禁返回 API Key / 请求头 / secret 内容。
- `POST /api/v1/system/llm-test`：最小测试请求，返回成功/延迟/provider/model，
  失败返回清理后的错误。

### 5.3 保留的既有 API

所有既有路由保持不变（见第 1 节模块清单），`/review` 页面新增只读
「AI 配置状态」区域（不含 API Key 输入框、不落 localStorage）。

## 6. 兼容性风险

| 风险 | 说明 | 缓解 |
|---|---|---|
| Ollama 行为差异 | 现部署用 `format="json"` + `think=False` + `options.num_ctx` | Ollama provider 保持原请求形态，`LLM_*` 未配置时完全沿用旧变量语义 |
| 旧环境变量失效 | 部署 `.env` 只配 `OLLAMA_*` | 阶段 2 提供兼容层；阶段 4 的 compose 同时注入新旧变量 |
| 数据库兼容 | 无 Alembic，启动时命令式迁移 | 不新增迁移框架；新功能不加表结构（llm-status/test 只读） |
| 默认值变化 | 硬编码 IP 改为占位符后，未配置环境的兜底连接目标变化 | 占位符指向 `host.docker.internal`，与现有 Docker 部署语义一致 |
| `/review` 页面 | 新增状态区不得破坏既有 JS | 独立 `<div>` + 独立 fetch，不触碰既有状态管理 |
| 批处理停止逻辑 | provider 错误分类变化不能误伤正常错误 | 基础设施错误标记列表原样迁移到 `app/llm/errors.py` |

## 7. 推荐的修改顺序

1. **阶段 1 · Git 仓库**：`git init`、`.gitignore`/`.dockerignore`、密钥扫描、首个 commit。
2. **阶段 2 · LLM Provider 抽象**：新增 `app/llm/`，`ollama_client.py` 变兼容包装器，
   业务调用点切到 factory；不破坏现有 `OLLAMA_*` 部署。
3. **阶段 3 · 系统接口**：`llm-status` / `llm-test` + 审核页状态区。
4. **阶段 4 · 配置示例**：`.env.example`、compose 支持 `LLM_*` 与 Docker secrets、
   移除硬编码 IP 与绝对路径。
5. **阶段 5 · 质量与测试**：`pyproject.toml`、20 项要求的测试、`compileall`/`pytest`/`ruff`/
   `docker compose config`/`docker compose build` 全绿。
6. **阶段 6 · 文档**：README/README.zh-CN/LICENSE/CHANGELOG 等。
7. **阶段 7 · CI**：GitHub Actions（不连真实 Ollama/Mealie，全部 mock）。
8. **阶段 8 · 最终检查**：密钥/IP/路径/大小复查、版本升 0.21.0、release commit。

> 任何阶段失败：停止后续阶段、保留已完成 commit、输出失败命令与修复建议，不降级安全要求。
