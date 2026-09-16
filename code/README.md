# 发票报销审核助手 FastAPI 后端

本目录是基于现有 MySQL 表结构与 Milvus 知识库设计生成的 FastAPI 后端骨架。

## 启动

```powershell
cd "D:\实战三个项目\1 发票报销审核助手\code"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

默认读取相邻 `PythonProject1\.env`，也可以在本目录放置 `.env` 覆盖。

## 主要接口

- `GET /health`：服务、MySQL、Milvus 基础状态
- `GET /api/invoices`：查询发票记录
- `POST /api/invoices/import`：批量写入发票
- `POST /api/attachments`：上传附件并写入 MySQL
- `POST /api/knowledge/import`：写入知识切片到 MySQL，默认同步到 Milvus
- `POST /api/knowledge/sync/{tenant_id}`：同步待同步知识到 Milvus
- `POST /api/knowledge/search`：语义检索知识库
- `POST /api/audits/claims/{claim_no}/run`：MVP 审核，执行发票重复检查并召回制度依据

## 说明

当前版本保留财务审核边界：Milvus 检索结果只作为相似制度或案例依据，不作为自动通过或退回的唯一依据。

## 百炼 Qwen 大模型接入

配置读取优先级：进程环境变量 > code/.env > ../PythonProject1/.env。
现有密钥文件无需移动，也不需要配置 Windows 系统环境变量。

```dotenv
DASHSCOPE_API_KEY=本地填写密钥
LLM_BASE_URL=百炼控制台提供的OpenAI兼容完整地址
LLM_MODEL=qwen3.5-plus
LLM_TIMEOUT=45
LLM_MAX_RETRIES=1
LLM_TRUST_ENV=false
```

接口采用 httpx 直接调用百炼 Chat Completions 协议；非思考模式、JSON 输出、Pydantic 校验。
LLM_TRUST_ENV=false 表示忽略系统代理；只有明确需要代理时才设置为 true。
生产进程的环境变量仍然优先于两个 .env 文件。修改配置后需重启服务。
密钥不会进入日志或错误返回；.env 不应提交到版本控制。

### 票据文本抽取

`POST /api/llm/extract-invoice`

```json
{"text":"发票号码：1234567890，开票日期：2026-09-15，购买方：示例公司，销售方：示例酒店，价税合计：680.00，币种：CNY"}
```

返回 fields（每个字段的 value 和原文 evidence）、missing_fields、needs_confirmation 和 Token usage。
缺失字段为 null；字段值保留原文格式，尚未做日期和金额标准化。
原文证据校验只能防止无来源文本，不能保证模型选中了正确的字段。
接口只接受已提取/OCR文本，不读取图片或 PDF，不自动写入 invoices；需人工确认后使用发票导入接口。

### 审核说明

原有 `POST /api/audits/claims/{claim_no}/run` 增加可选请求字段：

```json
{"tenant_id":"demo","use_llm":true}
```

use_llm 默认 true；密钥未配置则继续返回规则报告。
大模型只收到规则检查结果、召回制度和规则结论，用于生成辅助说明。
返回新增 llm_report：status 为 generated / failed / disabled / not_configured，
成功时包含模型、说明、引用 id 和 Token 用量，失败时仅返回安全错误代码。
模型不能改写结构化 decision；模型说明仍需人工核对，非新增审核规则。
当前业务规则仍然主要是跨报销单发票查重，approved 不代表完成全部财务审核。
调用超时、非成功状态、输出不合法或引用不存在时，保留原有规则报告。

### 启动和测试（已有项目虚拟环境）

在 code 目录运行：

```powershell
& '..\PythonProject1\database_guide\.venv\Scripts\python.exe' -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

打开 http://127.0.0.1:8000/docs，可直接测试上述接口。当前接口没有身份认证，仅用于本地学习联调。

离线回归（不调用真实模型、不连接数据库）：

```powershell
& '..\PythonProject1\database_guide\.venv\Scripts\python.exe' -m unittest discover -s tests -v
```

错误代码：LLM_NOT_CONFIGURED（缺少密钥）、LLM_INVALID_BASE_URL（域名配置无效）、
LLM_CONNECTION_FAILED（网络/超时）、LLM_HTTP_401（认证失败）、LLM_HTTP_429（限流）、
LLM_INVALID_OUTPUT（结构不合法）、LLM_INCOMPLETE_OUTPUT（输出被截断）、
LLM_UNGROUNDED_FIELD（字段缺少原文依据）、LLM_UNKNOWN_CITATION（引用不存在）、
LLM_INPUT_TOO_LARGE（上下文过长）。

### 本次验证（2026-09-15）

- FastAPI TestClient + 真实 qwen3.5-plus：票据文本抽取返回 HTTP 200，6 个字段及原文证据通过校验，653 Tokens。
- 审核接口 + 真实模型：数据库/知识库使用测试替身，返回 HTTP 200，llm_report.status=generated，395 Tokens；规则结论 manual_review 未改变。
- 13 项离线测试覆盖无效输入、网络失败、重试、认证错误脱敏、截断输出、虚构字段/引用及审核降级。
- 未进行真实 MySQL/Milvus 端到端验证，也未添加 OCR、审核持久化或新财务规则。
- 修复原有 InvoiceRepository.list 遮蔽 list 类型注解导致的应用导入错误。

## 报销单管理与审核持久化（2026-09-16）

### 数据库迁移

首次升级已有数据库必须显式执行（只新增 claims、audit_runs 表，不删除已有数据）：

```powershell
& '..\PythonProject1\database_guide\.venv\Scripts\python.exe' -B scripts/migrate.py
```

迁移可重复执行。MySQL DDL 会隐式提交；如中途失败，修复后重跑。
接口不会在启动时建表。新数据库先执行 database_guide/schema.sql，再执行本迁移。
现有 invoices/attachments 继续通过 tenant_id + claim_no 与报销单关联。

### 接口

| 方法 | 路径 | 用途 |
|---|---|---|
| POST | /api/claims | 创建报销单，成功 201，重复 409 |
| GET | /api/claims?tenant_id=demo&limit=50&offset=0 | 分页查询报销单 |
| GET | /api/claims/BX001?tenant_id=demo | 报销单详情 |
| PUT | /api/claims/BX001?tenant_id=demo | 全量更新业务字段，必须提供 expected_version |
| POST | /api/audits/claims/BX001/run | 执行审核并保存独立历史记录 |
| GET | /api/audits/claims/BX001?tenant_id=demo&limit=20&offset=0 | 分页查询历史审核 |
| GET | /api/audits/{audit_id}?tenant_id=demo | 查看某次完整审核及输入快照 |

创建示例：

```json
{
  "tenant_id": "demo",
  "claim_no": "BX001",
  "applicant_name": "张三",
  "department": "研发部",
  "expense_type": "travel",
  "amount": "680.00",
  "currency": "CNY",
  "business_purpose": "项目出差住宿",
  "approval_status": "pending"
}
```

金额必须大于零且最多两位小数。tenant_id、claim_no 允许 1-64 位英文字母、数字、下划线或短横线。
PUT 使用相同业务字段，去掉 tenant_id、claim_no，再增加 expected_version（先从详情读取）。
版本冲突返回 409；不存在或不属于该租户的资源返回 404。tenant_id 过滤不等于用户认证，目前仍为本地学习接口。

### 状态与历史

- 报销单创建后 status=draft。审核记录保存成功且输入未变更后 status=audited；此状态仅表示已审核，不代表审核通过。
- 财务建议在审核记录的 decision 中；人工业务审批字段 approval_status 独立保存，不会被大模型或规则自动修改。
- 更新报销单、导入其发票或保存附件会递增 version、恢复 draft 并清除 latest_audit_id。包括重复导入，这是保守失效策略。
- 历史记录不覆盖；每次运行产生新的 audit_id。运行接口非幂等，客户端超时后应先查询历史，避免无意重复调用模型。
- 审核保存 input_snapshot（报销单、发票、附件引用、请求参数、规则/流程版本），及全部规则结果、制度原文、LLM说明、用量和 Markdown 报告。
- 规则结果和制度保存在 result 中；数据库提交失败时不返回成功报告。保存审核记录与更新报销单状态处于同一事务。
- 输入在审核过程中发生变化，返回 stale=true；记录保留，但不发布为最新审核。
- 当前快照覆盖本单数据；跨报销单查重和知识库查询发生于审核执行时，不构成全库同一时间点快照。
- 程序升级或新增规则后可重新审核，旧报告仍可查询。

兼容性变化：运行审核前必须创建报销单。旧发票无需重导；创建相同 tenant_id + claim_no 的报销单即可关联。
当前未新增金额一致性、预算或审批规则，不能将 approved 视为完整财务合规结论；新增字段用于管理和后续规则扩展。
此阶段未提供报销单删除、人工复核流程或业务权限管理。

### 实际运行

更新后需重启旧 uvicorn 进程（原命令未开启 --reload），否则 /docs 不会出现新接口。
建议流程：创建报销单 → 导入发票/上传附件 → 运行审核 → 查询 audit_id → 修改后重新审核。

真实集成验证脚本（会使用真实 MySQL、Milvus 和模型，产生独立测试租户数据；不会删除历史数据）：

```powershell
& '..\PythonProject1\database_guide\.venv\Scripts\python.exe' -B scripts/verify_claims.py
```

脚本使用本地缓存的 Embedding 模型，测试报告写入相邻 PythonProject1/verification 目录。
