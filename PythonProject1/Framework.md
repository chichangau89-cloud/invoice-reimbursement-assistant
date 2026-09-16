# 报销合规审核助手后端总体框架

本文档基于 `SKILL.md` 设计后端代码思路，目标是形成一套可落地、可扩展、可审计的报销审核系统架构。前端界面暂不纳入本阶段设计。

## 一、系统目标

后端系统负责接收报销材料，识别发票、行程单、审批单等附件内容，对照报销制度、预算、主数据和历史入账记录进行审核，推荐费用科目，并输出“通过 / 退回 / 人工复核”结论。

核心要求：

- 将 OCR、结构化抽取、大模型判断、规则校验、预算查询、历史比对拆成清晰模块。
- 对所有结论保留依据、命中规则、输入数据和模型调用记录，便于财务追溯。
- 对不确定事项输出“人工复核”，避免大模型直接替代财务最终判断。
- 支持企业制度、科目表、预算口径和风险阈值配置化。

## 二、总体架构

建议采用分层后端架构：

```text
API 层
  ├─ 报销单提交接口
  ├─ 附件上传接口
  ├─ 审核任务查询接口
  ├─ 审核结果查询接口
  └─ 人工复核反馈接口

应用服务层
  ├─ ReimbursementAuditService
  ├─ DocumentProcessingService
  ├─ ComplianceCheckService
  ├─ BudgetCheckService
  ├─ DuplicateCheckService
  ├─ AccountSubjectRecommendService
  └─ AuditDecisionService

领域能力层
  ├─ 单据识别
  ├─ 字段标准化
  ├─ 材料完整性校验
  ├─ 制度规则校验
  ├─ 预算占用校验
  ├─ 历史入账比对
  ├─ 费用科目推荐
  └─ 风险分级与结论生成

基础设施层
  ├─ OCR 服务适配器
  ├─ 大模型服务适配器
  ├─ 数据库访问
  ├─ 文件存储
  ├─ 消息队列 / 任务队列
  ├─ 企业系统接口适配器
  └─ 日志、审计、监控
```

推荐技术方向：

- 后端框架：`FastAPI` 或 `Flask`。如果项目后续需要高并发异步任务，优先 `FastAPI`。
- 数据库：`PostgreSQL` 保存业务数据、审核记录、规则配置；`Redis` 用于任务状态和缓存。
- 向量库：`Milvus` 保存制度条款、历史案例、票据文本、科目映射说明等向量化内容，用于语义检索和相似案例召回。
- 异步任务：`Celery`、`RQ` 或 `FastAPI BackgroundTasks`。生产场景建议使用独立任务队列。
- 文件存储：本地存储、对象存储或企业文档系统。
- 大模型调用：通过统一 `LLMClient` 封装，避免业务代码直接依赖某一家模型 API。
- OCR：通过 `OCRClient` 封装，可接入云 OCR、企业票据识别服务或本地模型。

## 三、核心处理流程

```text
1. 接收报销单和附件
2. 创建审核任务
3. 附件分类：发票 / 行程单 / 审批单 / 补充材料
4. OCR 或票据接口识别原始内容
5. 大模型结构化抽取并输出字段置信度
6. 字段标准化与一致性预检查
7. 查询制度规则、预算数据、主数据、历史入账记录
8. 执行材料完整性校验
9. 执行制度合规校验
10. 执行预算校验
11. 执行历史入账和重复报销校验
12. 推荐费用科目
13. 汇总风险、生成审核结论
14. 保存审核报告、证据链和模型调用记录
15. 返回审核结果
```

建议所有步骤都生成结构化中间结果，不只保存最终文本。这样后续可以重跑某个校验环节，也方便审计。

## 四、建议代码目录

```text
app/
  main.py
  api/
    reimbursement.py
    audit.py
    files.py
  core/
    config.py
    logging.py
    exceptions.py
  models/
    reimbursement.py
    document.py
    audit_result.py
    rules.py
    budget.py
    ledger.py
  schemas/
    reimbursement.py
    document.py
    audit.py
    llm.py
  services/
    reimbursement_audit_service.py
    document_processing_service.py
    compliance_check_service.py
    budget_check_service.py
    duplicate_check_service.py
    subject_recommend_service.py
    audit_decision_service.py
  engines/
    rule_engine.py
    risk_engine.py
    matching_engine.py
    prompt_engine.py
  clients/
    ocr_client.py
    llm_client.py
    embedding_client.py
    milvus_client.py
    budget_client.py
    ledger_client.py
    master_data_client.py
  repositories/
    reimbursement_repo.py
    document_repo.py
    audit_repo.py
    rule_repo.py
  prompts/
    document_extract.md
    compliance_reasoning.md
    subject_recommend.md
    audit_summary.md
  tasks/
    audit_tasks.py
  utils/
    amount.py
    date.py
    text_normalizer.py
tests/
  test_document_processing.py
  test_rule_engine.py
  test_budget_check.py
  test_duplicate_check.py
  test_audit_decision.py
```

## 五、关键数据模型

### 5.1 报销单

```python
class ReimbursementClaim:
    id: str
    claim_no: str
    applicant_id: str
    applicant_name: str
    department_id: str
    cost_center_id: str | None
    project_id: str | None
    expense_type: str
    amount: Decimal
    currency: str
    business_purpose: str
    expense_start_date: date | None
    expense_end_date: date | None
    approval_status: str
```

### 5.2 单据识别结果

```python
class ExtractedDocument:
    id: str
    claim_id: str
    document_type: str  # invoice / itinerary / approval / supplement
    source_file_id: str
    fields: dict
    confidence: float
    field_confidence: dict
    issues: list[str]
```

### 5.3 校验结果

```python
class CheckResult:
    check_type: str  # completeness / compliance / budget / duplicate / subject
    status: str      # pass / fail / review
    risk_level: str  # low / medium / high
    message: str
    evidences: list[dict]
    suggestions: list[str]
```

### 5.4 最终审核结果

```python
class AuditResult:
    claim_id: str
    decision: str  # approved / rejected / manual_review
    risk_level: str
    recommended_subject: str | None
    subject_confidence: str | None
    check_results: list[CheckResult]
    data_gaps: list[str]
    report_markdown: str
```

## 六、大模型调用设计

大模型不直接决定所有财务结论，应主要承担以下职责：

- 从 OCR 文本和附件内容中抽取结构化字段。
- 对非结构化制度条款进行摘要、归类和候选规则提取。
- 在规则结果基础上生成自然语言审核说明。
- 在科目映射不确定时给出候选科目和理由。
- 对复杂业务说明进行语义判断，但必须输出依据和置信度。

### 6.1 LLMClient 统一封装

```python
class LLMClient:
    def extract_document_fields(self, document_text: str, document_type: str) -> dict:
        ...

    def classify_expense_type(self, claim: dict, documents: list[dict]) -> dict:
        ...

    def recommend_subject(self, context: dict, subject_catalog: list[dict]) -> dict:
        ...

    def generate_audit_report(self, audit_context: dict) -> str:
        ...
```

封装层必须处理：

- 模型名称、温度、超时、重试。
- JSON Schema 输出校验。
- Prompt 版本管理。
- 请求和响应脱敏记录。
- 调用失败降级策略。

### 6.2 Prompt 使用原则

- 所有抽取任务要求模型输出 JSON，不直接输出散文。
- Prompt 中明确“不知道就返回 null，不要编造”。
- 金额、日期、税号、发票号码等关键字段以 OCR 或原始票据接口结果为准，大模型只能辅助纠错。
- 审核结论生成时，大模型只能基于已有校验结果总结，不应新增未被规则或数据支持的违规结论。

示例抽取输出：

```json
{
  "document_type": "invoice",
  "fields": {
    "invoice_code": "string|null",
    "invoice_no": "string|null",
    "issue_date": "YYYY-MM-DD|null",
    "buyer_name": "string|null",
    "buyer_tax_no": "string|null",
    "seller_name": "string|null",
    "amount_without_tax": "number|null",
    "tax_amount": "number|null",
    "total_amount": "number|null"
  },
  "confidence": 0.0,
  "field_confidence": {},
  "issues": []
}
```

## 七、规则引擎设计

规则引擎处理确定性判断，优先于大模型判断。

规则来源：

- 企业报销制度。
- 费用类型附件要求。
- 城市、职级、金额标准。
- 审批权限矩阵。
- 预算控制规则。
- 禁止报销事项。
- 风险阈值配置。

建议规则结构：

```yaml
id: travel_hotel_limit
name: 差旅住宿标准校验
expense_type: travel
condition:
  city_level: first_tier
  employee_level: M2
check:
  field: hotel_amount_per_day
  operator: less_equal
  value: 600
on_fail:
  status: review
  risk_level: medium
  message: 住宿金额超过一线城市 M2 标准，需检查是否存在超标准审批。
```

规则执行输出统一为 `CheckResult`，不得只返回布尔值。

## 八、各业务模块设计

### 8.1 单据识别模块

职责：

- 接收图片、PDF、电子票据。
- 识别文件类型。
- 调用 OCR 或票据识别接口。
- 调用大模型抽取字段。
- 输出标准化 `ExtractedDocument`。

关键点：

- 发票号码、金额、税号、日期等字段必须保留原文位置或原始文本依据。
- 识别置信度低于阈值时，不进入自动通过路径。
- 同一附件可能包含多张票据，需要拆分成多条识别记录。

### 8.2 材料完整性校验模块

职责：

- 按报销类型匹配附件要求。
- 检查必需材料是否存在。
- 检查报销单、发票、行程单、审批单之间的关键字段一致性。

输出：

- 缺失材料清单。
- 不一致字段清单。
- 是否退回或人工复核建议。

### 8.3 制度合规模块

职责：

- 检查抬头、税号、金额、日期、费用事项、审批时间、审批金额。
- 检查是否超标准、是否属于禁止事项。
- 检查跨部门、跨项目、跨期间、拆分报销等异常模式。

确定性规则命中时直接输出 `fail` 或 `review`，大模型只负责解释复杂文本和生成说明。

### 8.4 预算校验模块

职责：

- 根据成本中心、项目、费用类型和期间查询预算。
- 计算本次报销后的预算余额。
- 判断预算状态：充足、临界、不足、冻结、无预算、期间不匹配。

预算接口建议抽象为：

```python
class BudgetClient:
    def get_available_budget(self, cost_center_id: str, project_id: str | None, expense_type: str, period: str) -> dict:
        ...

    def preview_occupy_budget(self, claim_id: str, amount: Decimal, dimension: dict) -> dict:
        ...
```

第一阶段建议只做预算“预检查”，不要直接真实占用预算；真实占用应由 ERP 或预算系统完成。

### 8.5 历史入账比对模块

职责：

- 使用发票号、订单号、行程单号等强匹配字段查询历史记录。
- 使用员工、供应商、金额、日期、路线等字段做相似匹配。
- 输出重复风险和相似记录。

匹配策略：

- 强匹配命中：通常退回。
- 相似匹配高：人工复核。
- 相似匹配低：记录风险提示，不阻断自动审核。

### 8.6 费用科目推荐模块

职责：

- 根据费用类型、发票项目、部门、项目、历史入账习惯推荐科目。
- 当规则映射明确时优先规则映射。
- 当规则不明确时调用大模型给出候选科目和理由。

推荐优先级：

1. 企业科目映射规则。
2. 同部门 / 同项目历史入账习惯。
3. 发票项目和业务用途语义判断。
4. 大模型候选推荐。

### 8.7 审核结论模块

职责：

- 汇总所有 `CheckResult`。
- 根据优先级生成最终结论。
- 生成标准审核报告。

建议决策优先级：

```text
存在明确重复报销、禁止事项、关键材料缺失、明确超标准无审批
  => 退回

存在高风险、识别低置信、制度解释空间、预算争议、相似重复风险
  => 人工复核

所有关键校验通过，且科目推荐置信度足够
  => 通过
```

## 九、外部系统集成

后端应通过适配器层对接外部系统，避免业务代码直接绑定外部接口。

常见接口：

- 报销系统：报销单、附件、审批流。
- OCR 或票据平台：票据识别、发票验真、电子发票解析。
- ERP / 总账系统：历史入账记录、会计凭证、供应商信息。
- 预算系统：预算余额、预算冻结、预算追加、预算占用。
- 主数据系统：员工、部门、成本中心、项目、公司抬头、税号。
- 科目系统：费用科目表、科目映射规则、税务处理口径。

第一阶段可以用本地数据库或 CSV 模拟外部系统数据，接口保持一致，便于后续替换。

## 十、Milvus 向量库设计

Milvus 不建议替代 PostgreSQL、MySQL 这类关系型数据库来保存完整业务状态。它更适合作为向量检索库，用于“找相似制度条款、相似历史报销案例、相似票据文本、相似科目解释”。结构化业务数据仍建议保存在关系库，Milvus 只保存检索需要的文本、向量和必要元数据。

### 10.1 哪些数据适合放入 Milvus

建议放入 Milvus 的数据：

- **报销制度条款**：制度原文切片、费用类别、适用部门、适用职级、生效日期、制度版本。
- **历史审核案例**：历史报销摘要、最终结论、退回原因、人工复核意见、命中规则。
- **历史入账摘要**：入账摘要、费用科目、供应商、金额区间、业务用途。注意强匹配字段仍应在关系库或 ERP 中查询。
- **费用科目说明**：科目名称、科目编码、适用场景、排除场景、税务处理提示。
- **票据 OCR 文本摘要**：发票、行程单、审批单抽取后的文本摘要，用于相似票据或相似业务场景检索。

不建议只放入 Milvus 的数据：

- 报销单主表、附件文件、审批流状态。
- 预算余额、预算占用流水。
- 发票号、订单号、入账凭证号等强一致查询字段。
- 最终财务入账凭证和审计日志。

这些数据应保存在关系库或企业系统中，Milvus 只保存可检索副本和引用 ID。

### 10.2 Collection 设计

第一阶段建议先建一个统一集合 `reimbursement_knowledge`，通过 `doc_type` 区分数据类型。后续数据量变大后，再拆成 `policy_chunks`、`audit_cases`、`subject_catalog` 等多个集合。

推荐字段：

```text
collection: reimbursement_knowledge

id              主键，字符串或整数
vector          文本向量，维度由 embedding 模型决定
doc_type        policy / audit_case / ledger_summary / subject / ticket_text
tenant_id       企业或租户 ID
source_id       原始业务数据 ID，例如制度 ID、报销单 ID、科目 ID
source_version  制度版本或数据版本
title           标题
content         用于检索和召回的文本内容
metadata        JSON 字段，保存费用类型、部门、职级、日期、风险等级等
created_at      写入时间
```

如果 embedding 模型输出 1536 维向量，则 collection 的 `vector` 维度必须设置为 1536；如果换成 768 或 3072 维模型，Milvus schema 也要对应调整。向量维度是建表时的重要约束。

### 10.3 写入 Milvus 的数据处理流程

```text
1. 从制度、历史案例、科目表、OCR 文本读取原始数据
2. 清洗文本：去掉无意义空白、页眉页脚、重复符号
3. 文本切片：按条款、段落或业务案例切分
4. 生成 embedding：调用 EmbeddingClient
5. 组装 Milvus entity：向量 + 文本 + 元数据 + 原始数据引用
6. 调用 MilvusClient.insert 写入集合
7. 保存写入结果和 source_id 映射
```

切片建议：

- 制度条款按“章节 / 条款 / 费用类型”切分，不要按固定字数粗暴切。
- 历史审核案例按一个报销单一条记录，必要时把问题和结论单独拼成摘要。
- 科目说明按一个科目一条记录。
- OCR 文本较长时按票据或附件页拆分，并保留附件 ID。

### 10.4 Milvus 客户端封装

在 `app/clients/milvus_client.py` 中封装 Milvus 访问，业务服务不要直接调用 `pymilvus`。

```python
from pymilvus import MilvusClient


class MilvusVectorClient:
    def __init__(self, uri: str, token: str | None, collection_name: str):
        self.client = MilvusClient(uri=uri, token=token)
        self.collection_name = collection_name

    def ensure_collection(self, dimension: int) -> None:
        if self.client.has_collection(self.collection_name):
            return
        self.client.create_collection(
            collection_name=self.collection_name,
            dimension=dimension,
            metric_type="COSINE",
        )

    def upsert_documents(self, documents: list[dict]) -> dict:
        return self.client.insert(
            collection_name=self.collection_name,
            data=documents,
        )

    def search(self, query_vector: list[float], doc_type: str | None = None, limit: int = 5) -> list[dict]:
        filter_expr = f'doc_type == "{doc_type}"' if doc_type else ""
        return self.client.search(
            collection_name=self.collection_name,
            data=[query_vector],
            filter=filter_expr,
            limit=limit,
            output_fields=["doc_type", "source_id", "title", "content", "metadata"],
        )
```

官方 `MilvusClient` 支持创建 collection、写入 `insert`、向量检索 `search`，也支持通过标量字段做过滤查询。项目里统一封装后，后续切换本地 Milvus、Milvus Standalone、Zilliz Cloud 或其他向量库时影响较小。

### 10.5 Embedding 客户端封装

在 `app/clients/embedding_client.py` 中封装向量生成。它可以调用 OpenAI embedding、本地 embedding 模型或企业内部模型。

```python
class EmbeddingClient:
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        ...

    def embed_query(self, query: str) -> list[float]:
        return self.embed_texts([query])[0]
```

注意事项：

- Milvus collection 维度必须等于 embedding 输出维度。
- 同一个 collection 不要混用不同维度或语义空间差异很大的 embedding 模型。
- embedding 模型版本要写入元数据，便于重建索引。
- 敏感数据写入向量库前应脱敏或最小化。

### 10.6 上传数据到 Milvus 的接口

建议增加知识库导入接口：

```text
POST /api/knowledge/import
POST /api/knowledge/import/policy
POST /api/knowledge/import/audit-cases
POST /api/knowledge/import/subjects
POST /api/knowledge/search
```

接口职责：

- `POST /api/knowledge/import/policy`：上传制度文档或制度条款 JSON，切片后写入 Milvus。
- `POST /api/knowledge/import/audit-cases`：从历史审核记录导入案例摘要。
- `POST /api/knowledge/import/subjects`：导入费用科目表和科目适用说明。
- `POST /api/knowledge/search`：输入查询文本，返回相似条款、案例或科目说明。

接口示例：

```json
{
  "tenant_id": "demo",
  "doc_type": "policy",
  "source_id": "policy-2026-travel",
  "source_version": "2026.01",
  "title": "差旅费报销制度",
  "content": "员工一线城市住宿标准不超过每人每天600元，超标准需事前审批。",
  "metadata": {
    "expense_type": "travel",
    "rule_type": "hotel_limit",
    "city_level": "first_tier"
  }
}
```

写入 Milvus 前转换为：

```json
{
  "id": "policy-2026-travel#chunk-001",
  "vector": [0.012, -0.034],
  "doc_type": "policy",
  "tenant_id": "demo",
  "source_id": "policy-2026-travel",
  "source_version": "2026.01",
  "title": "差旅费报销制度",
  "content": "员工一线城市住宿标准不超过每人每天600元，超标准需事前审批。",
  "metadata": {
    "expense_type": "travel",
    "rule_type": "hotel_limit",
    "city_level": "first_tier"
  }
}
```

### 10.7 审核流程中如何调用 Milvus

Milvus 应接入以下几个后端环节：

```text
DocumentProcessingService
  └─ 将 OCR 文本摘要写入 Milvus，便于后续相似票据检索

ComplianceCheckService
  └─ 根据报销类型、金额、城市、职级召回相关制度条款

DuplicateCheckService
  └─ 召回相似历史案例和相似票据文本，辅助判断重复报销风险

AccountSubjectRecommendService
  └─ 召回相似科目说明和历史入账案例，辅助费用科目推荐

AuditDecisionService
  └─ 将召回证据纳入最终审核报告，但不把向量相似结果当作唯一依据
```

典型调用链：

```text
报销单上下文
  -> 拼接查询文本：“差旅 住宿 一线城市 M2 620元 无超标审批”
  -> EmbeddingClient.embed_query
  -> MilvusVectorClient.search(doc_type="policy")
  -> 返回相关制度条款
  -> RuleEngine / LLMClient 基于条款和结构化字段生成校验结果
```

### 10.8 本项目接入步骤

建议按以下顺序落地：

1. 安装依赖：`pymilvus`、后端框架、embedding SDK。
2. 增加配置：`MILVUS_URI`、`MILVUS_TOKEN`、`MILVUS_COLLECTION`、`EMBEDDING_MODEL`、`EMBEDDING_DIMENSION`。
3. 新增 `EmbeddingClient` 和 `MilvusVectorClient`。
4. 新增 `KnowledgeService`，负责清洗、切片、向量化、写入和检索。
5. 新增知识库导入 API。
6. 在制度合规、历史比对、科目推荐模块中调用 `KnowledgeService.search_*`。
7. 在审核报告中记录 Milvus 召回的 `source_id`、相似度、条款文本和用途。

配置示例：

```env
MILVUS_URI=http://localhost:19530
MILVUS_TOKEN=root:Milvus
MILVUS_COLLECTION=reimbursement_knowledge
EMBEDDING_MODEL=text-embedding-model
EMBEDDING_DIMENSION=1536
```

服务封装示例：

```python
class KnowledgeService:
    def __init__(self, embedding_client: EmbeddingClient, vector_client: MilvusVectorClient):
        self.embedding_client = embedding_client
        self.vector_client = vector_client

    def import_texts(self, items: list[dict]) -> dict:
        texts = [item["content"] for item in items]
        vectors = self.embedding_client.embed_texts(texts)
        documents = []
        for item, vector in zip(items, vectors):
            documents.append({**item, "vector": vector})
        return self.vector_client.upsert_documents(documents)

    def search_policy(self, query: str, limit: int = 5) -> list[dict]:
        vector = self.embedding_client.embed_query(query)
        return self.vector_client.search(vector, doc_type="policy", limit=limit)

    def search_subjects(self, query: str, limit: int = 5) -> list[dict]:
        vector = self.embedding_client.embed_query(query)
        return self.vector_client.search(vector, doc_type="subject", limit=limit)

    def search_cases(self, query: str, limit: int = 5) -> list[dict]:
        vector = self.embedding_client.embed_query(query)
        return self.vector_client.search(vector, doc_type="audit_case", limit=limit)
```

### 10.9 注意事项

- Milvus 检索结果是“相似”，不是“确定命中”。重复报销的强判断仍应依赖发票号、订单号、入账凭证号等结构化查询。
- 制度条款召回后，应由规则引擎或人工配置规则执行确定性判断。
- 对预算余额这类强一致数据，不应从 Milvus 查，必须调用预算系统或关系库。
- 生产环境应建立重建索引机制：当 embedding 模型、制度版本或切片策略变化时，需要重新向量化。
- 多租户场景必须把 `tenant_id` 作为过滤条件，避免不同公司的制度和案例互相污染。
- 向量库中的原文内容需要做权限控制和敏感信息脱敏。

## 十一、审计与可追溯

每次审核必须保存：

- 原始报销单数据。
- 附件文件引用和文件哈希。
- OCR 原始文本。
- 大模型请求摘要、Prompt 版本、模型版本、响应结果。
- 每条规则的命中情况。
- 预算查询结果和历史入账比对结果。
- 最终结论、风险等级、建议动作。
- 人工复核人的反馈和最终处理结果。

敏感信息如身份证号、银行卡号、手机号、税号等需要脱敏展示，并按企业权限控制访问。

## 十二、异常和降级策略

- OCR 失败：标记附件识别失败，进入人工复核。
- 大模型调用失败：保留 OCR 文本和规则校验结果，无法抽取的字段进入人工复核。
- 预算接口失败：标记预算数据缺口，不能自动通过。
- 历史入账接口失败：标记历史比对数据缺口，不能自动通过高风险单据。
- 规则配置缺失：输出人工复核，并记录配置缺口。
- 文件无法解析：退回补充清晰附件或人工复核。

## 十三、第一阶段 MVP 建议

第一阶段不追求完整企业集成，建议先做可验证闭环：

1. 支持上传报销单 JSON 和附件文件。
2. 支持发票、行程单、审批单三类附件识别。
3. 使用本地配置文件维护报销规则、预算样例、历史入账样例、科目表。
4. 实现材料完整性校验、金额日期一致性校验、预算预检查、重复发票检查。
5. 调用大模型完成字段抽取、费用科目候选推荐、审核报告生成。
6. 输出结构化 JSON 结果和 Markdown 审核报告。

MVP 的建议接口：

```text
POST /api/claims
POST /api/claims/{claim_id}/attachments
POST /api/audits/{claim_id}/run
GET  /api/audits/{claim_id}
POST /api/audits/{claim_id}/manual-review
```

## 十四、后续扩展方向

- 引入发票验真和电子发票原始 XML 解析。
- 接入真实 ERP、预算系统和主数据系统。
- 增加规则配置后台。
- 引入向量检索，用于制度条款召回和历史案例召回。
- 增加人工复核反馈学习，优化科目推荐和风险阈值。
- 对高频异常建立专题风控模型。
- 支持多公司、多制度版本、多币种和跨境报销。
