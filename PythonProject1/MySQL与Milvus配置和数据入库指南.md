# 发票报销审核助手：MySQL 与 Milvus 配置和数据入库指南

编写日期：2026-09-15。本文采用已确定的 **MySQL＋Milvus** 方案。

适用阶段：从零搭建本地学习环境，验证数据保存、向量化和检索。配套示例位于 `database_guide/`，不依赖付费大模型 API，不需要 GPU。首次安装 Python 包、拉取镜像和下载 Embedding 模型需要网络。

验证边界：已通过 Docker Compose 配置解析、Python 3.12 语法与命令行帮助检查，已检查 CSV/JSON 样例格式及发票合计 666.50。当前电脑能找到 Docker CLI，但 Docker Linux 引擎未启动，因此未进行真实数据库连接、SQL 执行、模型下载和 Milvus 导入检索测试。配套表是教学最小表结构，不是完整财务系统。

此前 `Framework.md` 和 `prenv.md` 中仍有 PostgreSQL 选型建议；数据库配置与入库操作以本指南确定的 MySQL＋Milvus 方案为准。

## 1. 先理解：两个数据库分别存什么？

### 1.1 MySQL：保存业务事实、状态和权威原文

可以把 MySQL 理解成“按字段整理好的业务账本”。它适合精确查询、计算、关联和事务更新。

| 数据 | 建议存储内容 | 实际用途 |
|---|---|---|
| 报销单 | 单号、人员、部门、项目、金额、状态 | 查某张报销单当前到哪一步 |
| 发票 | 号码、代码（如适用）、日期、买卖方、税号、金额、币种 | 对账、号码查重、金额核对 |
| 附件元数据 | 文件路径、哈希、大小、文件名、关联报销单 | 找到原始图片或 PDF |
| OCR 与字段证据 | 原文、页码、坐标、字段值、识别状态 | 追溯金额、税号从哪里读出来 |
| 预算数据 | 期间、成本中心、预算额度、已占用额、来源时间 | 精确预算预检查；正式数据以预算系统为准 |
| 制度和规则 | 制度原文、生效日期、适用对象、规则参数、版本 | 判断某人某次出差适用哪个标准 |
| 主数据、科目表 | 公司税号、部门、员工、科目编码和映射 | 精确匹配公司抬头和费用科目 |
| 审核与审计记录 | 规则命中、结论、证据、人工复核、模型版本 | 审计和复现审核结果 |
| 知识切片与同步状态 | 条款文本、来源 ID、版本、哈希、待同步状态 | 管理 Milvus 检索副本并支持重试 |

例子：查“发票号 00000000000000000001 是否已提交过”，用 MySQL 的 `WHERE invoice_no = ...`。

### 1.2 Milvus：保存“可按语义检索”的副本

Milvus 中的一条记录通常包含：**主键＋文本向量＋原文片段＋来源 ID＋过滤字段**。

向量就是一串浮点数，用来表达文本含义。这里的向量由 Embedding 模型计算，Milvus 负责保存和检索。本示例不会让 Milvus 自动把普通文字变成向量。

| 数据 | Milvus 中保存的内容 | 典型问题 |
|---|---|---|
| 制度条款 | 单条制度的文本、向量、来源、版本 | “出差住酒店超标怎么办？” |
| 科目说明 | 科目适用场景、排除场景及向量 | “培训场地租赁费属于什么费用？” |
| 已复核历史案例 | 脱敏的业务摘要、结论、理由、案例 ID | “找与这笔业务相似的历史处理案例” |
| 票据/业务文本摘要 | 脱敏文本、向量、原始附件或报销单 ID | 查相似消费事项，作为风险候选 |

**不要把预算余额、审批状态、精确发票号查重只交给 Milvus。** 相似度高只代表语义接近，不代表是同一张发票，也不代表制度一定适用。

### 1.3 PDF 和图片本身放哪里？

- 开发阶段：本地附件目录。
- 正式部署：企业文件服务或独立的对象存储桶。
- MySQL 保存文件位置和哈希；Milvus 保存需要检索的文本及向量。

MySQL 技术上可以存二进制文件，但这个项目推荐将文件与业务行分开管理。

### 1.4 一个完整例子

```text
用户提交：住宿发票 680 元＋报销说明
  │
  ├─ 原始图片 → 文件存储
  ├─ 发票字段、报销信息 → MySQL
  ├─ “住宿超标准如何处理” → Embedding 模型 → 查询向量
  │                                      ↓
  │                                   Milvus
  │                                      ↓
  │                            召回住宿标准条款 ID
  │                                      ↓
  └────────────────────────── MySQL 回查原文、版本和适用范围
                                         ↓
                           规则引擎核对金额、职级、城市、审批
                                         ↓
                             MySQL 保存审核结果和证据
```

规则引擎负责执行“超过标准且没有有效审批”的判断。向量检索负责找到候选条款。

## 2. 本指南使用的组件

| 组件 | 本文配置 | 为什么需要 |
|---|---|---|
| MySQL | `mysql:8.4` | 业务事实和知识原文 |
| Milvus Standalone | `milvusdb/milvus:v2.6.0` | 单机向量检索教学基线 |
| etcd | `v3.5.18` | Milvus 内部元数据依赖 |
| MinIO | `RELEASE.2024-05-28T17-19-04Z` | Milvus 内部对象数据依赖 |
| Python | 建议单独使用 3.12 | 运行导入、向量化、查询示例 |
| PyMySQL | 1.x，启用 rsa 依赖 | Python 连接 MySQL |
| PyMilvus | 2.6.x | Python 连接 Milvus |
| Embedding | `BAAI/bge-small-zh-v1.5`，512 维 | 本地 CPU 生成中文向量 |

这些版本用于构造明确的学习基线，不宣称是最新版本或生产补丁基线。正式上线需重新核对维护版本、兼容矩阵和镜像来源，并锁定精确版本或镜像 digest。

本示例选 BGE-small 是为了让数据库教程可以在 CPU 上操作；不要求修改整个项目此前的大模型选型。中文 BGE-small 的向量维度为 512；英文 small 型号的维度不同，不要混用。[模型官方说明](https://huggingface.co/BAAI/bge-small-zh-v1.5)

Milvus Standalone 官方要求至少 8GB 内存、推荐 16GB，推荐 4 核以上；还需为 MySQL、Windows、IDE 和模型留空间。因此整机建议 32GB 内存起步，紧张时使用远程数据库。[部署要求](https://milvus.io/docs/v2.6.x/prerequisite-docker.md)

## 3. 配套目录及每个文件的职责

```text
database_guide/
  compose.yaml              启动 MySQL、Milvus、etcd、MinIO
  .env.example              配置模板；复制成 .env 后填写
  .gitignore                忽略密码、虚拟环境和本地附件
  schema.sql                MySQL 教学表结构
  requirements.txt          Python 依赖范围
  db_demo.py                命令行导入、同步和查询工具
  samples/
    invoices.csv            两条虚构发票
    knowledge.json          三条虚构制度/科目切片
```

所有样例都是教学数据。其中 600 元住宿标准不是实际企业制度。

## 4. 第一步：确认 Docker 环境

以下命令都在 Windows PowerShell 中执行。先打开 Docker Desktop，选择 Linux 容器和 WSL2 后端，等待引擎启动。

```powershell
docker version
docker compose version
```

成功标志：`docker version` 同时显示 Client 和 Server；Compose 能显示版本。

如果出现 `dockerDesktopLinuxEngine` 管道不存在，说明 Docker CLI 能找到，但 Docker Desktop 的 Linux 引擎没有就绪。先解决这一点，不要继续反复执行数据库命令。

如电脑尚未启用 WSL2，按 Docker Desktop 的安装引导启用，必要时管理员权限执行 WSL 安装并重启。本文不自动修改系统虚拟化设置。

## 5. 第二步：填写数据库配置

进入配套目录：

```powershell
Set-Location -LiteralPath 'D:\实战三个项目\1 发票报销审核助手\PythonProject1\database_guide'
Copy-Item -LiteralPath .env.example -Destination .env
notepad .env
```

`Copy-Item` 只在首次执行；已有 `.env` 时直接编辑，避免覆盖之前的配置。

把三个 `CHANGE_ME` 密码换成各自不同的本地学习密码。建议使用较长的字母数字组合，避免初学时因 `$`、`#`、引号等字符遇到 Compose 和 dotenv 的转义差异。

| 配置 | 含义 |
|---|---|
| `MYSQL_ROOT_PASSWORD` | MySQL 管理员初始密码 |
| `MYSQL_PASSWORD` | Python 示例使用的业务用户密码 |
| `MYSQL_HOST=127.0.0.1` | Python 在 Windows 本机运行时的连接地址 |
| `MYSQL_PORT=3307` | 宿主机端口，避开已有的 3306 |
| `MYSQL_DATABASE=reimbursement_demo` | 教学数据库名 |
| `MYSQL_USER=reimbursement_app` | 教学应用用户 |
| `MINIO_ACCESS_KEY` / `MINIO_SECRET_KEY` | Milvus 内部存储凭据，两边必须一致 |
| `MILVUS_URI=http://127.0.0.1:19530` | 本机 Milvus 服务入口 |
| `MILVUS_TOKEN` | 本地示例未开启 Milvus 认证，因此留空 |
| `MILVUS_COLLECTION` | 向量集合名，本例包含模型信息便于区分 |
| `EMBEDDING_MODEL` | 固定模型身份；本示例只支持 BGE-small-zh-v1.5 |
| `EMBEDDING_PATH` | 可选，提前下载好的同一模型本地目录 |
| `EMBEDDING_DIM=512` | 向量维度，必须与模型及集合一致 |

本例库名和应用用户名同时写在 Compose 和 SQL 中，先保留默认值；只改 `.env` 中这两项并不能完整更名。

数据库端口只绑定 `127.0.0.1`，etcd 和 MinIO 不开放宿主机端口。这里没有配置 Milvus 用户权限，是单人本地教程环境；团队/服务器部署需启用认证、访问控制和相应网络隔离。

检查 Compose 配置是否能解析，且不输出展开后的密码：

```powershell
docker compose config --quiet
```

成功标志：没有配置错误。检查不会启动服务。

## 6. 第三步：启动并确认数据库就绪

```powershell
docker compose up -d
docker compose ps
```

首次需要拉取镜像、初始化 MySQL、启动 etcd/MinIO，然后启动 Milvus。可能等待数分钟。

成功标志：mysql、etcd、minio、milvus 四个服务均为运行状态，健康检查最终为 `healthy`。仅看到容器创建成功不等于数据库已经可用。

查看失败服务的日志：

```powershell
docker compose logs --tail 100 mysql
docker compose logs --tail 100 milvus
docker compose logs --tail 100 etcd minio
```

Milvus 健康检查：

```powershell
Invoke-WebRequest -Uri 'http://127.0.0.1:9091/healthz'
```

成功标志：HTTP 200。19530 是客户端连接端口，9091 在本例中用于健康检查。

### 6.1 数据实际保存在哪里？

Compose 使用 Docker 命名卷：mysql_data、etcd_data、minio_data、milvus_data。实际卷名会带项目名前缀，可用下列命令查看：

```powershell
docker volume ls --filter name=reimbursement-db-guide
```

普通停止/启动保留这些卷。不要为了解决密码错误随意删除数据卷。

本套 MinIO 是 Milvus 内部组件，不是给应用直接存发票的演示服务。不要往 Milvus 的内部桶随意上传业务附件。

### 6.2 MySQL 的初始化只在空数据目录时执行

第一次启动，镜像创建 `reimbursement_demo` 和业务用户，并执行挂载的 `schema.sql`。已有数据卷时，重启不会重新创建用户、修改密码或重跑全部初始化 SQL。[MySQL 官方镜像说明](https://hub.docker.com/_/mysql)

如果你修改了 `.env` 密码而保留旧数据卷，数据库内仍是旧密码。使用已有管理员凭据在数据库内修改用户密码，再更新客户端；不要误以为编辑配置就改变了账户。

## 7. 第四步：连接 MySQL，理解三张教学表

命令行连接：

```powershell
docker compose exec mysql mysql -u reimbursement_app -p reimbursement_demo
```

输入 `.env` 中的 `MYSQL_PASSWORD`，终端不会显示密码。出现 `mysql>` 后，输入的是 SQL，不是 PowerShell。

```sql
SELECT VERSION(), DATABASE();
SHOW TABLES;
DESCRIBE invoices;
DESCRIBE attachments;
DESCRIBE knowledge_chunks;
```

成功标志：当前数据库为 `reimbursement_demo`，显示三张表。

| 表 | 主键 | 关键字段 | 作用 |
|---|---|---|---|
| `invoices` | `record_id` | `tenant_id`、`invoice_no`、`total_amount` | 保存发票提交记录 |
| `attachments` | `id` | `claim_no`、`storage_path`、`sha256` | 保存附件引用 |
| `knowledge_chunks` | `id` | `source_id`、`source_version`、`content`、`sync_status` | 保存知识原文和同步状态 |

- `VARCHAR`：字符串。发票号用字符串，保留前导零。
- `DECIMAL(18,2)`：总共最多 18 位数字，其中小数 2 位，用于本例人民币金额。
- `DATE`：日期，例如 `2026-09-01`。
- `PRIMARY KEY`：每条记录的唯一身份。
- `INDEX`：加速查询，例如按企业和发票号查找。
- `tenant_id`：企业标识；同一家企业的数据必须带相同标识。

`record_id` 是“这次提交的记录身份”，不是发票号码。因此不同提交可以含相同发票号，系统才能保留重复报销的证据。真实系统可另外维护规范化发票主表、报销关联表和入账记录，不能仅凭本例一个索引完成全部查重。

本例没有建完整的报销、预算、规则、审批、审计表。后续应按业务设计补齐，而不是把所有内容塞入这三张教学表。

退出 MySQL：

```sql
exit;
```

### 7.1 用图形界面连接

已有 DBeaver、Navicat 或 DataGrip 时，创建 MySQL 连接，填写：

```text
Host:     127.0.0.1
Port:     3307
Database: reimbursement_demo
User:     reimbursement_app
Password: .env 中 MYSQL_PASSWORD 的值
```

“测试连接”成功后刷新表列表。客户端有时需要下载 MySQL 驱动。

### 7.2 如果表不存在，手动执行建表文件

先确认连接的是教学库。SQL 使用 `CREATE TABLE IF NOT EXISTS`，可补建缺失表，但不会自动迁移已有字段。

```powershell
docker compose cp .\schema.sql mysql:/tmp/reimbursement-schema.sql
docker compose exec mysql mysql -u reimbursement_app -p reimbursement_demo
```

进入 `mysql>` 后：

```sql
SOURCE /tmp/reimbursement-schema.sql;
SHOW TABLES;
```

## 8. 第五步：准备 Python 导入环境

当前项目根目录的 `.venv` 是 Python 3.14。为了让教学依赖单独管理，在 `database_guide` 中新建 Python 3.12 环境，不覆盖原环境。

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe db_demo.py --help
```

成功标志：帮助中显示 `import-invoices`、`import-knowledge`、`attach`、`sync`、`search`。

不需要激活环境；一直使用这个 Python 的完整相对路径，避免安装到别的解释器。如果 `py -3.12` 不存在，先安装 Python 3.12，或者用 `py -0p` 查找可用路径。

只想先试 MySQL 导入，可暂时只安装：

```powershell
.\.venv\Scripts\python.exe -m pip install 'PyMySQL[rsa]>=1.1,<2' 'python-dotenv>=1.0,<2'
```

运行 Milvus 同步前再安装完整 requirements。Embedding 库采用延迟导入，MySQL 操作不会提前下载模型。

本例固定模型在 CPU 运行。环境验证通过后可保存实际依赖版本：

```powershell
.\.venv\Scripts\python.exe -m pip freeze | Set-Content -Encoding utf8 requirements.lock.txt
```

## 9. 第六步：把发票数据导入 MySQL

### 9.1 CSV 文件是什么？

CSV 是一行一条记录、用逗号分列的文本文件。本例表头如下：

```csv
record_id,tenant_id,claim_no,invoice_no,issue_date,buyer_name,seller_name,total_amount,currency
```

打开 `samples/invoices.csv`，你会看到两条虚构发票。金额写 `580.00`，不要写 `￥580元`；日期使用 `YYYY-MM-DD`。用 Excel 编辑时，将发票号列设为文本，否则前导零可能丢失。

### 9.2 执行导入

```powershell
.\.venv\Scripts\python.exe db_demo.py import-invoices .\samples\invoices.csv
```

成功标志：打印 `MYSQL_INVOICES_OK rows=2`。这里 rows 是本次处理的输入行数，不一定是新增数量。

代码链路：

```text
main()
  → import_invoices(path)
  → csv.DictReader 读取每行
  → Decimal / date 校验金额和日期
  → 根据 tenant_id＋record_id 计算数据库主键
  → cur.executemany(...) 批量参数化 INSERT
  → db.commit() 提交事务
```

SQL 中 `%s` 是参数占位符，真实值通过参数列表传入。不要用字符串拼接把用户输入直接放进 SQL。

`ON DUPLICATE KEY UPDATE` 表示同一个主键已存在时更新该行。因此重复导入相同样例不会增加为四行；修改同一 `record_id` 的金额会更新对应记录。这个行为适合教学导入，不是已入账票据的修改策略。

### 9.3 在数据库里确认

重新打开 MySQL 命令行，执行：

```sql
SELECT tenant_id, claim_no, invoice_no, total_amount, currency
FROM invoices
WHERE tenant_id = 'demo-company';

SELECT COUNT(*) AS invoice_count, SUM(total_amount) AS total
FROM invoices
WHERE tenant_id = 'demo-company';
```

全新教学库的预期结果是 2 条，合计 `666.50`。如已自行导入其他样例，数量和合计会变化。

### 9.4 精确查询与重复候选查询

```sql
SELECT claim_no, invoice_no, issue_date, total_amount
FROM invoices
WHERE tenant_id = 'demo-company'
  AND invoice_no = '00000000000000000001';

SELECT tenant_id, invoice_no, issue_date, COUNT(*) AS submissions
FROM invoices
GROUP BY tenant_id, invoice_no, issue_date
HAVING COUNT(*) > 1;
```

第二条找出多次提交候选。正式判断还需考虑票种、号码规则、开票方、红冲作废、分摊、原报销单状态及历史入账，不能一律按号码重复退回。

### 9.5 自己的 CSV 如何导入？

复制样例文件，保留表头，改为真实抽取后的字段，再把命令最后的路径换成自己的 CSV 路径即可。含空格的路径用引号包住。

图形工具也可导入 CSV，但配套 CSV 的 `record_id` 会在 Python 中加企业标识后哈希化；直接用图形工具导入不会执行这层转换。为了保持同一主键规则，本例推荐一直使用脚本导入。

脚本会一次读取整个 CSV，适合小规模教学；大文件应改为分批读取、分批提交、记录导入批次和失败行。

## 10. 第七步：原始 PDF/图片如何“上传”？

数据库不会自动理解 PDF。这里演示的是“保存文件＋登记附件”，不包含 OCR。

在 PowerShell 中选择你自己已有的文件：

```powershell
.\.venv\Scripts\python.exe db_demo.py attach 'D:\票据样例\酒店发票.pdf' --tenant demo-company --claim BX-DEMO-001
```

请把示例路径换成实际文件。成功标志：`ATTACHMENT_OK`，并显示保存位置。

脚本会：

1. 读取文件并计算 SHA-256 哈希。
2. 复制到 `database_guide/data/attachments/企业ID/文件哈希`。
3. 把相对路径、原文件名、文件大小和报销单号写入 MySQL `attachments`。
4. 相同企业、同一报销单、相同文件重复执行时复用同一附件身份。

查询验证：

```sql
SELECT claim_no, original_name, storage_path, size_bytes
FROM attachments
WHERE tenant_id = 'demo-company' AND claim_no = 'BX-DEMO-001';
```

实际 Web 项目以后可用 `POST /claims/{id}/attachments` 接收文件，再调用文件保存和数据库写入服务。当前没有实现这个 HTTP 接口，也没有识别出任何真实发票字段。

文件复制和数据库提交不是一个事务；数据库失败可能留下孤立文件，正式系统需要补偿或清理机制。迁移开发环境时，同时备份附件目录和 MySQL。

## 11. 第八步：先把制度条款原文存入 MySQL

### 11.1 为什么先存 MySQL？

因为后续需要知道条款来自哪个制度、哪个版本，以及 Milvus 中的副本是否过期。MySQL 保留来源事实，Milvus 保存检索副本。

配套 JSON 的一条记录形如：

```json
{
  "tenant_id": "demo-company",
  "source_id": "travel-policy",
  "source_version": "demo-v1",
  "chunk_no": 1,
  "doc_type": "policy",
  "title": "演示制度：住宿标准",
  "content": "普通员工在一线城市出差，住宿费标准为每人每天600元……"
}
```

- `source_id`：原制度身份。
- `source_version`：制度版本。
- `chunk_no`：该版本里的切片编号。
- `doc_type`：policy 制度、subject 科目、audit_case 案例、ticket_text 票据摘要。
- `content`：真正参与检索的文字。

脚本将“企业＋来源＋版本＋切片编号”组合后计算固定 SHA-256 主键。MySQL 和 Milvus 使用同一个主键，便于回查和重试。

### 11.2 执行导入与验证

```powershell
.\.venv\Scripts\python.exe db_demo.py import-knowledge .\samples\knowledge.json
```

成功标志：`MYSQL_KNOWLEDGE_OK rows=3`。

MySQL 中执行：

```sql
SELECT id, source_id, source_version, title, sync_status
FROM knowledge_chunks
WHERE tenant_id = 'demo-company';
```

预期看到 3 条记录，`sync_status` 为 `pending`，表示原文入库成功、尚待向量化。**此时 Milvus 中还没有这些向量。**

### 11.3 自己的制度文件如何变成 JSON？

```text
制度 PDF/Word
  → 提取正文；扫描件先 OCR
  → 按章节和条款切分
  → 为每条记录填写来源、版本、切片号
  → 人工核对条款是否完整
  → 保存 UTF-8 JSON
  → import-knowledge
```

这一步目前需要自行整理，本例没有自动 PDF/Word 解析器。每片优先围绕一个完整条款，避免把“标准”和“例外条件”拆开。超长条款拆片时附带章节标题、适用范围和来源位置。

BGE-small 模型有输入长度上限；脚本按实际 tokenizer 检查，超长会报错，防止悄悄截掉后半段。先按约 150～300 个中文字准备短条款，再以 token 检查为准，字数不等于 token 数。

## 12. 第九步：创建 Milvus 集合并上传向量

### 12.1 先理解集合结构

Milvus 的 Collection 可以先类比为“表”。本例在第一次同步或查询时自动创建集合：

```text
reimbursement_knowledge_bge_small_zh_v1
```

| 字段 | 类型 | 含义 |
|---|---|---|
| id | VARCHAR 主键 | 与 MySQL 知识切片主键一致 |
| tenant_id | VARCHAR | 企业过滤 |
| doc_type | VARCHAR | 制度/科目/案例等类型过滤 |
| source_id、source_version | VARCHAR | 原始来源和版本 |
| title、content | VARCHAR | 召回结果的文本副本 |
| content_hash | VARCHAR | 检查副本是否过期 |
| embedding_model | VARCHAR | 记录向量模型身份 |
| vector | FLOAT_VECTOR，512 维 | Embedding 输出 |

本例明确设置 `auto_id=False`，由应用提供固定主键；创建 `AUTOINDEX`，相似度度量用 `COSINE`。建好索引后加载集合，再查询。[Milvus 集合创建说明](https://milvus.io/docs/v2.6.x/create-collection.md)

### 12.2 执行真正的向量化和写入

```powershell
.\.venv\Scripts\python.exe db_demo.py sync --tenant demo-company
```

首次执行会下载 BGE 模型；如果下载网络不可用，将失败。可在有网络的机器下载完整模型目录，复制到本机，并在 `.env` 设置 `EMBEDDING_PATH`。不要用随机数字代替模型向量来验证语义检索。

成功标志：`MILVUS_SYNC_OK rows=3 collection=...`。

数据流：

```text
sync(tenant)
  → vector_resources() 连接 Milvus、加载 CPU 模型、建集合和索引
  → MySQL 每批读取最多 64 条 pending/目标不一致的有效记录
  → encode() 将“标题＋正文”变成真实 512 维向量
  → client.upsert(...) 写入 Milvus
  → MySQL 将仍匹配原文哈希的记录标记为 synced
```

写入的核心形状是：

```python
entity = {
    "id": "与MySQL相同的固定主键",
    "tenant_id": "demo-company",
    "doc_type": "policy",
    "source_id": "travel-policy",
    "source_version": "demo-v1",
    "title": "住宿标准",
    "content": "原文条款",
    "content_hash": "实际内容哈希",
    "embedding_model": "BAAI/bge-small-zh-v1.5",
    "vector": actual_embedding  # 由模型生成的512个浮点数
}
client.upsert(collection_name=collection_name, data=[entity])
```

这个片段用于解释字段，不是可单独运行的脚本；完整实现见 `db_demo.py`。

### 12.3 为什么使用 upsert？

`insert` 表示插入，不能作为自动按业务主键去重的保证；`upsert` 用于按已有主键插入或替换。本例发送完整实体、使用固定主键，便于同步失败后重试。[Milvus upsert 官方说明](https://milvus.io/docs/v2.6.x/upsert-entities.md)

再次运行 sync，正常应显示 `rows=0`；重新导入同一份知识 JSON 后，会重新置为 pending，再同步会更新相同主键的实体。

### 12.4 查询 MySQL 同步状态

```sql
SELECT title, sync_status, sync_target, synced_at
FROM knowledge_chunks
WHERE tenant_id = 'demo-company';
```

预期为 `synced`。但状态只是同步记录，下一步还应真正查询 Milvus，不能只看这列判断检索可用。

## 13. 第十步：用自然语言检索制度

```powershell
.\.venv\Scripts\python.exe db_demo.py search '出差住酒店超过标准，需要什么审批？' --tenant demo-company --type policy
```

处理链路：

```text
问题
  → 同一个 BGE 模型生成查询向量（按模型说明加入中文检索前缀）
  → Milvus 按 tenant_id 和 doc_type 过滤，再做 COSINE 相似检索
  → 返回候选切片 ID、相似度、哈希和模型身份
  → MySQL 回查原文，排除已停用、已修改、模型身份不符的副本
  → 打印最多三条有效候选
```

成功标志：输出包含来源、版本、标题和正文的 JSON，并打印 `SEARCH_OK`。若有效候选数为 0，不算语义检索验收通过，应检查导入、同步、过滤条件和集合名。

全新样例中应能找到“演示制度：住宿标准”；具体相似度和排序以实际运行为准，不预先保证某个分数。

查询科目说明：

```powershell
.\.venv\Scripts\python.exe db_demo.py search '员工因公出差的酒店住宿费放什么科目？' --tenant demo-company --type subject
```

### 13.1 查看 Milvus 中的原始记录

进入 Python 交互环境：

```powershell
.\.venv\Scripts\python.exe
```

输入：

```python
import os
from dotenv import load_dotenv
from pymilvus import MilvusClient
load_dotenv('.env')
client = MilvusClient(uri=os.environ['MILVUS_URI'], token=os.getenv('MILVUS_TOKEN', ''))
name = os.environ['MILVUS_COLLECTION']
client.list_collections()
client.describe_collection(collection_name=name)
client.load_collection(collection_name=name)
client.query(collection_name=name, filter='tenant_id == "demo-company"', output_fields=['id', 'title', 'source_id'], limit=10, consistency_level='Strong')
client.close()
exit()
```

这一步是客户端直接访问 Milvus，不是查询 MySQL。

### 13.2 教学查询还没有实现的部分

- 自动按费用发生日期选择制度版本。
- 按职级、部门、城市做适用性过滤。
- 对相似度做业务阈值标定。
- 重排模型与无相关结果识别。
- 从登录身份获取 tenant_id 的权限系统。

因此它只返回“候选依据”，没有实现自动通过/退回。真实 API 的 tenant_id 必须由服务端登录上下文决定，不能相信调用者随意传来的企业 ID。

## 14. 数据更新、停用和两个库的一致性

### 14.1 修改同一条款

修改 JSON 的正文，保持企业、来源、版本、切片号不变，然后执行：

```powershell
.\.venv\Scripts\python.exe db_demo.py import-knowledge .\samples\knowledge.json
.\.venv\Scripts\python.exe db_demo.py sync --tenant demo-company
```

MySQL 更新原文并置 pending；Milvus 按相同主键覆盖。正式制度发布应新建版本，不能直接覆盖过去审核所引用的制度内容。

### 14.2 发布新制度版本

新版本使用新的 `source_version`，产生新主键。旧版本为历史审计保留；在线检索需根据适用日期、部门等筛选。当前示例的版本筛选尚未实现，测试时可手动停用不再参与检索的演示版本。

### 14.3 停用演示条款

在 MySQL 中停用确实需要退出当前演示检索的版本：

```sql
UPDATE knowledge_chunks
SET is_active = FALSE, sync_status = 'pending'
WHERE tenant_id = 'demo-company'
  AND source_id = 'travel-policy'
  AND source_version = 'demo-v1';
```

本示例查询会回查 MySQL，因此不会把该版本作为有效结果返回，但 Milvus 的旧向量仍占空间，也可能挤占前十条候选。正式系统需增加删除同步任务，依据主键调用 Milvus `delete`，或为历史版本建立独立检索策略。仅从 JSON 中移除一条记录，不会自动删除数据库中的记录。

重新导入相同 JSON 会重新激活对应记录，这是教学工具的明确行为。

### 14.4 MySQL 成功、Milvus 失败怎么办？

两者没有自动共享事务。不要把“两个 API 都调用过”当作一致性保证。

当前示例流程：

1. 原文先提交到 MySQL，状态为 pending。
2. Milvus 写入成功后，再标记 synced。
3. 中途失败保留 pending，修复连接后重跑 sync。
4. 若 Milvus 成功但状态更新失败，重试按固定主键 upsert。
5. 查询时回查当前原文哈希和有效性，避免直接使用过期副本。

这是单进程教学方案，不是完整生产同步系统。生产建议在 MySQL 事务中同时写业务数据和 outbox 事件，由 worker 处理重试、删除、版本顺序、失败原因及定期对账。多个并发 worker 还需要领取任务、版本检查和过期写保护。

### 14.5 换模型、换集合或重建 Milvus

- 同一个集合不要混用不同模型，即使它们维度相同。
- 换模型需新集合、新向量，文档与查询都使用同一模型及预处理方式。
- 本脚本只支持配置中声明的 BGE 模型；换模型还需改编码逻辑和检索前缀，不能只改名字。
- 模型本地目录内容也要版本化；不能用同名目录悄悄替换权重。
- 本例 `sync_target` 记录集合和模型，只适合单一活动目标；正式多目标同步应有独立任务表。

如果 Milvus 集合丢失，但 MySQL 仍显示 synced，需要把对应企业的有效知识重新置为 pending，然后同步：

```sql
UPDATE knowledge_chunks
SET sync_status = 'pending'
WHERE tenant_id = 'demo-company' AND is_active = TRUE;
```

原始知识、模型版本和切分方式齐全，才具备可靠重建条件。

## 15. 常见故障：看什么、下一步做什么

| 现象 | 常见原因 | 下一步 |
|---|---|---|
| dockerDesktopLinuxEngine 不存在 | Docker Linux 引擎未启动 | 打开 Docker Desktop，等待 Server 就绪 |
| 拉镜像超时 | 镜像站连接或代理问题 | 检查 Docker 网络/可信镜像源；未拉完不算启动成功 |
| 端口被占用 | 本机已有相同端口服务 | 改宿主端口，同时改 `.env` 客户端端口 |
| MySQL Access denied | 用户密码错误，或旧数据卷保留旧密码 | 用原凭据确认账户后修改；不靠重启改密码 |
| Table doesn't exist | 连错库或初始化未执行 | 查询 DATABASE()/SHOW TABLES，按第7.2节补建 |
| 发票号前导零消失 | 被 Excel 当数值保存 | 重新准备文本格式列，核对原始票据 |
| 字符乱码 | CSV 编码不对或连接字符集不对 | CSV 用 UTF-8；本例读取兼容 UTF-8 BOM |
| Milvus unhealthy | etcd/MinIO 不就绪、内存不足、凭据不一致 | 查看三者日志及 Docker 内存资源 |
| Connection refused | 服务没就绪、端口或地址错误 | 查 compose ps 和本机端口映射 |
| collection not found | 未同步或集合名改变 | 检查 MILVUS_COLLECTION，执行 sync |
| dimension mismatch | 模型与集合维度不同 | 新建匹配模型的集合，重新生成向量 |
| 模型下载失败 | Hugging Face 网络不可达 | 使用完整本地模型目录 EMBEDDING_PATH |
| Text has ... tokens | 条款超过模型长度 | 按完整语义拆成更短条款，再导入同步 |
| 同步后查不到 | tenant/type 不匹配、过期哈希、无有效记录 | 查 MySQL 状态及 Milvus 实体，核对过滤条件 |
| 找到相似但不适用的条款 | 语义检索未做业务适用性判断 | 增加生效日期、职级、城市等过滤和规则校验 |

如果把 Python 后端也放进同一个 Compose 网络，MySQL 地址应是 `mysql:3306`，Milvus 地址是 `http://milvus:19530`。容器内 `127.0.0.1` 指向容器自身，不是 Windows 主机，也不是另外一个数据库容器。

## 16. 日常启动、停止与备份

在 `database_guide` 目录执行：

```powershell
docker compose stop
docker compose start
docker compose ps
```

需要按 Compose 文件重新协调配置时使用 `docker compose up -d`。`docker compose down` 会移除容器和网络，默认保留命名卷；不要附加删除卷的参数，除非已经确认要销毁数据。

### 16.1 MySQL 教学库备份

用容器内交互 shell 执行备份，可以避免 PowerShell 管道编码干扰 SQL 文件：

```powershell
docker compose exec mysql sh
```

在容器 shell 输入：

```sh
mysqldump -u reimbursement_app -p --single-transaction --no-tablespaces --set-gtid-purged=OFF reimbursement_demo --result-file=/tmp/reimbursement-demo.sql
exit
```

输入应用密码；dump 完成无报错后，在 PowerShell 复制出来：

```powershell
docker compose cp mysql:/tmp/reimbursement-demo.sql .\reimbursement-demo.sql
```

备份文件包含业务数据，不应直接提交公共代码仓库。备份时避免同时执行表结构变更。

恢复验证应在另一套测试数据库中进行，不要直接覆盖正在使用的业务库。MySQL 备份之外，还需备份 `data/attachments`、模型/切片版本配置；Milvus 可使用专门备份方案，或在本例规模下从 MySQL 知识原文重建。不要把运行中的内部数据目录随意复制当作一致性备份。

## 17. 一次完整验收应看到什么？

| 步骤 | 成功证据 |
|---|---|
| 配置解析 | `docker compose config --quiet` 无错误 |
| 服务就绪 | 四个容器 healthy，Milvus healthz 返回 200 |
| MySQL 初始化 | reimbursement_demo 中存在三张教学表 |
| 发票导入 | 2 条样例，合计 666.50，重复导入不增行 |
| 附件登记 | 本地存在文件，MySQL 有对应路径和哈希 |
| 制度原文入库 | 3 条 knowledge_chunks，初始 pending |
| 向量同步 | 打印 MILVUS_SYNC_OK，原文状态变为 synced |
| Milvus 实体查询 | 能看到对应企业的切片 ID 和标题 |
| 语义检索 | 住宿问题召回住宿标准，包含原文来源 |
| 企业隔离演示 | 改用一个没有数据的 tenant，不应返回其他企业记录 |

这些验证通过，才说明“本地数据库与导入检索链路”打通。仍不代表 OCR、预算接口、规则审核、财务准确率或生产权限体系已经完成。

## 18. 官方资料

- [MySQL 8.4 Docker 部署](https://dev.mysql.com/doc/refman/8.4/en/docker-mysql-getting-started.html)
- [MySQL 官方镜像环境变量与初始化目录](https://hub.docker.com/_/mysql)
- [Milvus 2.6 Windows Docker 部署](https://milvus.io/docs/v2.6.x/install_standalone-windows.md)
- [Milvus 单机资源要求](https://milvus.io/docs/v2.6.x/prerequisite-docker.md)
- [Milvus 集合创建、字段与索引](https://milvus.io/docs/v2.6.x/create-collection.md)
- [Milvus 按主键写入更新](https://milvus.io/docs/v2.6.x/upsert-entities.md)
- [BGE-small-zh-v1.5 官方模型卡](https://huggingface.co/BAAI/bge-small-zh-v1.5)

一句话记忆：**MySQL 保存可追溯的业务事实和原文，Milvus 帮助按意思找到候选依据；原始附件独立保存，最后由业务规则执行审核。**
