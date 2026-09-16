const alerts=[['发票号码 0792882104 发票代码与发票全…致，疑似重复提交','刚刚'],['报销金额超过部门预算 24,760 元，请核对发票证明','25 分钟前'],['发票抬头与公司名称不一致，请核对并驳回','1 小时前'],['供应商名称被标记为高风险，建议人工复核','2 小时前']];
const tasks=[['上海客户开拓差旅费','王思远','差旅费','¥ 2,490.00','06-18 09:24','高风险'],['华府办公用品采购','陈嘉禾','办公用品','¥ 1,168.50','06-18 08:57','中风险'],['内部差旅交通费用','赵庆安','差旅费','¥ 12,600.00','06-17 17:40','低风险'],['供应商沟通餐饮招待','刘婷婷','招待费','¥ 896.00','06-17 16:12','中风险'],['研发部云服务年度续费','何一凡','技术服务','¥ 8,940.00','06-17 14:05','低风险']];
const alertsEl=document.querySelector('#alerts'); alerts.forEach(([title,time])=>{alertsEl.insertAdjacentHTML('beforeend',`<div class="alert"><span class="alert-icon">!</span><div class="alert-text"><strong>${title}</strong><small>${time}</small></div><button>去处理</button></div>`)});
const rows=document.querySelector('#taskRows'); tasks.forEach(t=>{const cls=t[5].startsWith('高')?'high':t[5].startsWith('中')?'medium':'low'; rows.insertAdjacentHTML('beforeend',`<tr><td>${t[0]}</td><td>${t[1]}</td><td>${t[2]}</td><td>${t[3]}</td><td>${t[4]}</td><td><span class="risk ${cls}">${t[5]}</span></td><td><button class="action">通过</button><button class="action secondary">复核</button></td></tr>`)});
document.querySelector('#uploadBtn').addEventListener('click',()=>document.querySelector('#fileInput').click());
document.querySelector('#exportBtn').addEventListener('click',()=>alert('静态演示：这里将连接报表导出接口。'));

const policyForm = document.querySelector('#policyForm');
const policyStatus = document.querySelector('#policyStatus');
const policyResults = document.querySelector('#policyResults');
const policyCatalog = document.querySelector('#policyCatalog');
let catalogLoaded = false;
let activeDocumentId = null;
let policiesLoading = false;
function policyText(tag, text, className) {
  const element = document.createElement(tag);
  element.textContent = text;
  if (className) element.className = className;
  return element;
}
function policyError(error, fallback) {
  return error instanceof TypeError ? '无法连接制度接口，请确认 Python 后端已运行在 8000 端口。' : error.message || fallback;
}
async function loadPolicyCatalog() {
  if (catalogLoaded) return;
  policyCatalog.setAttribute('aria-busy', 'true');
  policyStatus.className = '';
  policyStatus.textContent = '正在读取已入库的制度目录…';
  try {
    const response = await fetch('http://127.0.0.1:8000/api/policies/documents');
    const data = await response.json();
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : '制度目录读取失败。');
    catalogLoaded = true;
    policyCatalog.replaceChildren();
    policyStatus.textContent = `已加载 ${data.count} 个制度板块 · 当前版本：${data.version}${data.policy_status === 'draft' ? ' · 企业适配草案，未签发' : ''}`;
    for (const item of data.items) {
      const card = document.createElement('button');
      card.type = 'button';
      card.className = 'policy-doc-card';
      card.disabled = !item.available;
      card.dataset.documentId = item.document_id;
      card.append(policyText('span', item.document_id, 'policy-doc-id'));
      card.append(policyText('h3', item.title));
      card.append(policyText('span', `${item.clause_count} 条完整条款 · ${item.available ? '已同步' : '未同步'}`, 'policy-doc-meta'));
      card.addEventListener('click', () => loadPolicyDocument(item.document_id));
      policyCatalog.append(card);
    }
  } catch (error) {
    policyStatus.className = 'danger';
    policyStatus.textContent = policyError(error, '制度目录读取失败。');
  } finally {
    policyCatalog.removeAttribute('aria-busy');
  }
}
async function loadPolicyDocument(documentId) {
  policyResults.replaceChildren();
  policyResults.setAttribute('aria-busy', 'true');
  policyStatus.className = '';
  policyStatus.textContent = '正在从数据库读取完整制度条款…';
  try {
    const response = await fetch(`http://127.0.0.1:8000/api/policies/documents/${encodeURIComponent(documentId)}`);
    const data = await response.json();
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : '制度文件读取失败。');
    activeDocumentId = documentId;
    document.querySelectorAll('.policy-doc-card').forEach(card => card.classList.toggle('active', card.dataset.documentId === documentId));
    policyStatus.textContent = `${data.title} · 共 ${data.clauses.length} 条完整条款 · 数据来源：MySQL${data.policy_status === 'draft' ? ' · 企业适配草案，未签发' : ''}`;
    for (const clause of data.clauses) {
      const card = policyText('article', '', 'policy-card');
      card.append(policyText('h3', clause.title));
      card.append(policyText('p', `条款序号：${clause.chunk_no} · 来源：${data.filename} · 版本：${data.version}`, 'policy-meta'));
      card.append(policyText('p', clause.content, 'policy-content'));
      policyResults.append(card);
    }
  } catch (error) {
    policyStatus.className = 'danger';
    policyStatus.textContent = policyError(error, '制度文件读取失败。');
  } finally {
    policyResults.removeAttribute('aria-busy');
  }
}
async function loadPolicies(event) {
  if (event) event.preventDefault();
  if (policiesLoading) return;
  const query = document.querySelector('#policyQuery').value.trim();
  if (!query) { policyStatus.textContent = '请输入报销事项后再检索。'; return; }
  const button = document.querySelector('#policySearchBtn');
  policiesLoading = true;
  button.disabled = true;
  button.textContent = '检索中…';
  policyResults.replaceChildren();
  policyResults.setAttribute('aria-busy', 'true');
  policyStatus.textContent = '正在检索制度，首次加载向量模型可能需要稍候…';
  policyStatus.className = '';
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 120000);
  try {
    const response = await fetch(`http://127.0.0.1:8000/api/policies/search?${new URLSearchParams({q: query, limit: '5'})}`, {signal: controller.signal});
    const data = await response.json();
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : '检索请求失败，请检查后端版本及查询条件。');
    policyStatus.textContent = data.count ? `找到 ${data.count} 条相关制度条款 · 来源：Milvus${data.policy_status==='draft' ? ' · 企业适配草案，未签发' : data.is_demo ? ' · 当前为教学示例制度，不用于正式审批' : ''}` : '未找到有效制度条款，请调整描述，或确认制度已入库并同步。';
    for (const item of data.items) {
      const card = policyText('article', '', 'policy-card');
      card.append(policyText('h3', item.title || '未命名制度'));
      card.append(policyText('p', `来源：${item.source_id} · 版本：${item.source_version} · 条款片段：${item.chunk_no}`, 'policy-meta'));
      card.append(policyText('p', item.content, 'policy-content'));
      card.append(policyText('small', `检索相似度：${Number(item.score).toFixed(3)}（不是合规评分）`, 'muted'));
      policyResults.append(card);
    }
  } catch (error) {
    policyStatus.className = 'danger';
    policyStatus.textContent = error.name === 'AbortError' ? '检索超时，请稍后重试并检查模型和数据库服务。' : error instanceof TypeError ? '无法连接制度接口，请确认后端已重启并运行在 8000 端口。' : error.message;
  } finally {
    clearTimeout(timeout);
    policiesLoading = false;
    policyResults.removeAttribute('aria-busy');
    button.disabled = false;
    button.textContent = '检索制度';
  }
}
policyForm.addEventListener('submit', loadPolicies);
function syncNavigation() {
  document.querySelectorAll('.nav-item').forEach(link => link.classList.toggle('active', link.hash === (location.hash || '#dashboard')));
  if (location.hash === '#rules') loadPolicyCatalog();
}
window.addEventListener('hashchange', syncNavigation);
document.querySelector('a[href="#rules"]').addEventListener('click', loadPolicyCatalog);
syncNavigation();
