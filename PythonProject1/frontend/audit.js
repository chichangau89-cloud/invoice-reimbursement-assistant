/* User declarations are explicitly distinct from independently verified evidence. */
const auditForm = document.querySelector('#auditForm');
const auditStatus = document.querySelector('#auditStatus');
const auditResult = document.querySelector('#auditResult');
const documentSummary = document.querySelector('#documentSummary');
const recheckButton = document.querySelector('#recheckBtn');
let currentCase = null;
let auditBusy = false;
const fieldSpecs = [
 ['expense_type','费用类型','category'],['project','项目','text'],['purpose','业务用途','text'],['expected_buyer','费用承担法人名称','text'],
 ['payment_proof','支付证明','bool'],['contract','合同','bool'],['supplier_event_total','同供应商同事项累计金额','money'],['original_electronic_file','是否为开票原始电子文件','bool'],
 ['employee_grade','人员档位（A/B/C）','grade'],['city','住宿城市','text'],['lodging_nights','实际住宿夜数（单人）','int'],['lodging_amount','住宿房费合计','money'],['hotel_statement','酒店水单','bool'],
 ['event_total','整次招待实际总额','money'],['consecutive_invoices','涉及连号招待发票','bool'],['consecutive_total','连号组发票原金额合计','money'],
 ['approval_date','事前审批日期','date'],['expense_date','费用发生日期','date'],['payment_date','支付日期','date'],['submitted_date','提交日期','date'],
 ['unit_net_price','单件物品不含税单价','money'],['existing_loan','同员工同项目已有在途借款','bool'],['overdue_workdays','事项办结后经过工作日','int'],['loan_balance','未结清借款余额','money'],
 ['taxi_subsidy_overlap','市内车费与当日交通补助重叠','bool'],['high_speed_rail_available','自驾两地有高铁','bool'],['driving_total','燃油停车路桥费用合计','money'],['comparison_fare','本人适用高铁比较票价','money'],
 ['telecom_already_paid','通讯补助已随工资发放','bool'],['sole_trader_risk','个体工商户增强核验提示','bool'],['duplicate_risk','发现重复报销风险','bool'],
 ['remaining_allocatable','票据剩余可分摊金额','money'],['claimed_amount','本次申请金额','money'],['prepaid_fuel','是否为加油卡充值','bool']
];
fieldSpecs.forEach(([key,label,type],index)=>{
  const wrapper=policyText('label',label);
  let input;
  if (['bool','category','grade'].includes(type)) {
    input=document.createElement('select');
    const choices=type==='bool' ? [['','未知 / 未核对'],['true','是 / 已提供'],['false','否 / 未提供']] : type==='grade' ? [['','未确定'],['A','A'],['B','B'],['C','C']] : [['unknown','未确定'],['lodging','住宿'],['entertainment','业务招待'],['office','办公采购'],['transport','交通'],['self_drive','因公自驾'],['fuel','车辆燃油'],['telecom','通讯'],['loan','借款'],['other','其他']];
    choices.forEach(([value,text])=>{const option=policyText('option',text);option.value=value;input.append(option);});
  } else {
    input=document.createElement('input');
    input.type=['money','int'].includes(type)?'number':type;
    if(input.type==='number'){input.min=key==='lodging_nights'?'1':'0';input.step=type==='money'?'.01':'1';}
    if(input.type==='text') input.maxLength=key==='purpose'?500:key==='city'?100:200;
  }
  input.name=key;wrapper.append(input);
  document.querySelector(index<8?'#auditFields':'#auditExtraFields').append(wrapper);
});
function auditContext(){
  const data={};
  fieldSpecs.forEach(([key,,type])=>{const value=auditForm.elements[key].value.trim();if(value!=='') data[key]=type==='bool'?value==='true':type==='int'?Number(value):value;});
  return data;
}
function renderAudit(report){
  auditResult.replaceChildren();
  auditResult.append(policyText('h3',report.decision_label||'需人工复核'));
  auditResult.append(policyText('p',report.summary||'请检查审核结果'));
  const fields=report.fields||{};
  auditResult.append(policyText('p',`识别结果（待核对）：票号 ${fields.invoice_no||'未识别'} · 金额 ${fields.amount??'未识别'} · 日期 ${fields.issue_date||'未识别'} · 购方 ${fields.buyer_name||'未识别'}`));
  auditResult.append(policyText('p',`制度版本：${report.policy_version||'不可用'} · 报告编号：${report.report_id}`, 'policy-meta'));
  documentSummary.replaceChildren();
  for(const document of report.documents||[]) documentSummary.append(policyText('span',`${document.filename} · ${document.kind==='invoice'?'发票':document.kind==='itinerary'?'行程/住宿材料':document.kind==='approval'?'审批材料':'其他材料'} · ${document.recognized?'已识别':'未识别'}`,'document-chip'));
  if(report.retrievals?.length){
    const retrievals=policyText('section','','retrieval-list');
    for(const result of report.retrievals){
      const row=policyText('div','','retrieval-item');
      const name=result.channel==='mysql_exact_invoice'?'MySQL 精确历史查重':'Milvus 制度候选召回';
      row.append(policyText('strong',`${name} · ${result.status}`));
      row.append(policyText('span',result.reason));
      if(result.items?.length) row.append(policyText('p',result.channel==='mysql_exact_invoice'?`命中 ${result.items.length} 条历史记录。`:`召回 ${result.items.length} 条制度候选；详细原文见下方。`,'policy-meta'));
      retrievals.append(row);
    }
    auditResult.append(retrievals);
  }
  const names={pass:'本项未触发问题',flagged:'需处理',needs_evidence:'缺少证据',not_applicable:'本次未适用'};
  for(const check of report.checks||[]){
    const card=policyText('article','','policy-card');
    card.append(policyText('h3',`${check.rule_id} · ${names[check.status]||check.status}`));
    card.append(policyText('p',check.message));
    if(Object.keys(check.values||{}).length) card.append(policyText('p',Object.entries(check.values).map(([k,v])=>`${k}：${v}`).join('；'),'policy-meta'));
    const basis=check.basis;
    if(basis){
      card.append(policyText('p',`依据：${basis.file} / ${basis.section}${basis.line_start?` / 第${basis.line_start}—${basis.line_end}行`:''}`,'policy-meta'));
      card.append(policyText('p',`${basis.condition}；所需证据：${basis.evidence_required||'详见原条款'}`));
    }
    auditResult.append(card);
  }
  for(const reason of report.reasons||[]) if(!(report.checks||[]).some(c=>c.rule_id===reason.code)) auditResult.append(policyText('p',reason.message,'danger'));
  if(report.policy_hits?.length){
    const detail=document.createElement('details');detail.append(policyText('summary','查看相关制度原文'));
    for(const hit of report.policy_hits){detail.append(policyText('h3',hit.title));detail.append(policyText('p',hit.content,'policy-content'));}
    auditResult.append(detail);
  }
}
async function requestReview(){
  auditStatus.textContent=`${currentCase.documents.length} 份材料已保存，正在识别、查重并依据条款预审…`;
  const controller=new AbortController();const timer=setTimeout(()=>controller.abort(),120000);
  try{
    const response=await fetch(`http://127.0.0.1:8000${currentCase.review_url}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(auditContext()),signal:controller.signal});
    const report=await response.json();
    if(!response.ok) throw new Error(typeof report.detail==='string'?report.detail:'业务信息格式错误，请核对日期、金额及夜数');
    renderAudit(report);auditStatus.textContent='预审完成。具体问题、缺失证据及依据列在下方。';
  }finally{clearTimeout(timer);}
}
function busy(value){auditBusy=value;document.querySelector('#uploadBtn').disabled=value;document.querySelector('#uploadBtn').textContent=value?'处理中…':'＋ 上传材料';recheckButton.disabled=value||!currentCase;}
function auditError(error){auditStatus.textContent=`${currentCase?'材料已保存，预审未完成':'上传未完成'}：${error.name==='AbortError'?'请求超时，可重新审核':error.message}。请检查后端服务。`;}
async function uploadFiles(files){
  if(!files.length||auditBusy)return;
  if(!auditForm.reportValidity())return;
  busy(true);currentCase=null;auditResult.replaceChildren();documentSummary.replaceChildren();location.hash='upload';
  const controller=new AbortController();const timer=setTimeout(()=>controller.abort(),60000);
  try{
    auditStatus.textContent=`正在上传 ${files.length} 份材料…`;
    const body=new FormData();files.forEach(file=>body.append('files',file));
    const response=await fetch('http://127.0.0.1:8000/api/audits/documents',{method:'POST',body,signal:controller.signal});
    const result=await response.json();if(!response.ok)throw new Error(result.detail||'上传失败');
    currentCase=result;clearTimeout(timer);await requestReview();
  }catch(error){auditError(error);}finally{clearTimeout(timer);busy(false);}
}
const fileInput=document.querySelector('#fileInput');
fileInput.addEventListener('change',async event=>{
  await uploadFiles(Array.from(event.target.files));
  event.target.value='';
});
document.querySelectorAll('[data-open-file]').forEach(button=>button.addEventListener('click',event=>{event.stopPropagation();fileInput.click();}));
const dropZone=document.querySelector('#fileDropZone');
dropZone.addEventListener('click',()=>fileInput.click());
dropZone.addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();fileInput.click();}});
['dragenter','dragover'].forEach(type=>dropZone.addEventListener(type,event=>{event.preventDefault();dropZone.classList.add('dragging');}));
['dragleave','drop'].forEach(type=>dropZone.addEventListener(type,event=>{event.preventDefault();dropZone.classList.remove('dragging');}));
dropZone.addEventListener('drop',event=>uploadFiles(Array.from(event.dataTransfer.files)));
auditForm.addEventListener('submit',async event=>{
  event.preventDefault();if(!currentCase||auditBusy)return;busy(true);auditResult.replaceChildren();
  try{await requestReview();}catch(error){auditError(error);}finally{busy(false);}
});
