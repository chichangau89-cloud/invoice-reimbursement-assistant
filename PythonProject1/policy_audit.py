"""Deterministic draft-policy checks. Retrieval scores never decide approval."""
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import re
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from policy_documents import load_bundle, active_policy
from database_guide.db_demo import mysql


class AuditContext(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    expense_type: Literal['unknown','lodging','entertainment','office','transport','self_drive','fuel','telecom','loan','other'] = 'unknown'
    project: str | None = Field(None,max_length=200)
    purpose: str | None = Field(None,max_length=500)
    expected_buyer: str | None = Field(None,max_length=200)
    payment_proof: bool | None = None
    contract: bool | None = None
    supplier_event_total: Decimal | None = Field(None,ge=0)
    unit_net_price: Decimal | None = Field(None,ge=0)
    event_total: Decimal | None = Field(None,ge=0)
    consecutive_invoices: bool | None = None
    consecutive_total: Decimal | None = Field(None,ge=0)
    approval_date: date | None = None
    expense_date: date | None = None
    payment_date: date | None = None
    submitted_date: date | None = None
    existing_loan: bool | None = None
    overdue_workdays: int | None = Field(None,ge=0)
    loan_balance: Decimal | None = Field(None,ge=0)
    taxi_subsidy_overlap: bool | None = None
    high_speed_rail_available: bool | None = None
    driving_total: Decimal | None = Field(None,ge=0)
    comparison_fare: Decimal | None = Field(None,ge=0)
    telecom_already_paid: bool | None = None
    sole_trader_risk: bool | None = None
    duplicate_risk: bool | None = None
    remaining_allocatable: Decimal | None = Field(None,ge=0)
    claimed_amount: Decimal | None = Field(None,ge=0)
    prepaid_fuel: bool | None = None
    original_electronic_file: bool | None = None
    employee_grade: Literal['A','B','C'] | None = None
    city: str | None = Field(None,max_length=100)
    lodging_nights: int | None = Field(None,ge=1,le=366)
    lodging_amount: Decimal | None = Field(None,ge=0)
    hotel_statement: bool | None = None
    # Daily, multi-person sharing and exceptional approvals need evidence review.


def number(value):
    try:
        result=Decimal(str(value))
        return result if result.is_finite() and result>=0 else None
    except (InvalidOperation, TypeError, ValueError):
        return None


def invoice_date(value):
    try:
        clean=re.sub(r'[年/月.]','-',str(value)).rstrip('日')
        return datetime.strptime(clean,'%Y-%m-%d').date()
    except ValueError:
        return None


def verified_bundle():
    bundle=load_bundle()
    active=active_policy()
    if not active or active['version']!=bundle['version'] or active['tenant_id']!=bundle['tenant_id']:
        raise ValueError('条款JSON与已入库版本不一致，请先完成入库')
    with mysql() as db, db.cursor() as cursor:
        cursor.execute("SELECT id,content_hash FROM knowledge_chunks WHERE tenant_id=%s AND source_version=%s AND is_active=TRUE AND sync_status='synced'",
            (bundle['tenant_id'],bundle['version']))
        hashes={row['id']:row['content_hash'] for row in cursor.fetchall()}
    if any(hashes.get(row['id'])!=row['content_hash'] for row in bundle['clauses']):
        raise ValueError('制度缺失、停用或内容已改变，请重新同步并复核规则')
    return bundle


def evaluate(fields, context: AuditContext, bundle):
    rules={r['id']:r for r in bundle['rules']}
    clauses={c['id']:c for c in bundle['clauses']}
    checks=[]
    amount=number(fields.get('amount'))
    issued=invoice_date(fields.get('issue_date'))
    def add(code,status,message,values=None,clause_id=None):
        rule=rules.get(code)
        clause=clauses[clause_id or rule['clause_id']]
        checks.append({'rule_id':code,'status':status,'message':message,'values':values or {},
            'basis':{'file':clause['source_id'],'section':clause['section'],'version':clause['source_version'],
            'line_start':clause['line_start'],'line_end':clause['line_end'],'clause_id':clause['id'],
            'condition':rule['condition'] if rule else clause['section'],
            'evidence_required':rule['evidence'] if rule else '',
            'action':rule['action'] if rule else '按适用档位和实际人夜审核'}})
    def check(code, condition, message, values=None):
        add(code,'needs_evidence' if condition is None else 'flagged' if condition else 'pass',message,values)
    def evidence(code,value,threshold,evidence_value):
        if value is None:
            add(code,'needs_evidence','缺少比较金额，不能判断是否触发材料要求')
        elif value<=threshold:
            add(code,'pass','未超过本项材料触发门槛',{'amount':str(value),'operator':'>','threshold':str(threshold)})
        else:
            check(code,None if evidence_value is None else not evidence_value,
                '超过门槛，应提供并核验对应材料；表单声明不等于证据验真',
                {'amount':str(value),'operator':'>','threshold':str(threshold),'declared_present':evidence_value})
    missing=[label for label,value in [('票号',fields.get('invoice_no')),('金额',amount),('开票日期',issued),
        ('购方名称',fields.get('buyer_name')),('费用类型',None if context.expense_type=='unknown' else context.expense_type),
        ('承担法人',context.expected_buyer),('项目',context.project),('业务用途',context.purpose)] if value is None or value=='']
    check('R01',bool(missing),'缺少：'+'、'.join(missing) if missing else '基础字段已提供')
    evidence('R02',amount,Decimal(rules['R02']['threshold']),context.payment_proof)
    evidence('R03',context.supplier_event_total,Decimal(rules['R03']['threshold']),context.contract)
    if context.expense_type=='office':
        check('R04',None if context.unit_net_price is None else context.unit_net_price>Decimal(rules['R04']['threshold']),
            '单件不含税单价超过5000元时转财务分类，不自动拒报',{'unit_net_price':str(context.unit_net_price)})
    else:
        add('R04','not_applicable','未选择物品采购；费用分类需人工确认')
    for code in ['R05','R06','R07']:
        if context.expense_type not in ['entertainment','unknown']:
            add(code,'not_applicable','本次未申报招待费用')
        elif context.expense_type=='unknown':
            add(code,'needs_evidence','缺少费用类别，无法确定招待规则是否适用')
        elif code=='R05':
            check(code,None if context.event_total is None else context.event_total>Decimal(rules[code]['threshold']),
                '按整次招待实际总额判断3000元上限，不以申请核减金额代替',{'event_total':str(context.event_total),'threshold':rules[code]['threshold']})
        elif code=='R06':
            if context.consecutive_invoices is False:
                add(code,'pass','申报未涉及连号组；仍需核对全组票据')
            elif context.consecutive_invoices is None:
                add(code,'needs_evidence','需要全组发票核对连号及同单关联')
            else:
                evidence(code,context.consecutive_total,Decimal(rules[code]['threshold']),context.payment_proof)
        else:
            dates=[issued,context.expense_date,context.payment_date]
            check(code,None if context.approval_date is None or any(d is None for d in dates) else any(context.approval_date>d for d in dates),
                '事前审批日期不得晚于消费、开票和支付日期')
    if context.expense_type=='loan':
        check('R08',context.existing_loan,'同员工同项目存在有效在途借款时须拦截新增，需核对借款台账')
        check('R09',None if context.overdue_workdays is None or context.loan_balance is None else context.overdue_workdays>5 and context.loan_balance>0,
            '办结超过5个工作日且未结清需催清；工作日需按实际节假日台账计算')
    else:
        for code in ['R08','R09']:
            add(code,'not_applicable' if context.expense_type!='unknown' else 'needs_evidence','借款业务须单独提供在途与结清台账')
    check('R10',context.taxi_subsidy_overlap,'需按人按日核对市内车费与交通补助，重叠日扣40元；城际票不适用')
    if context.expense_type=='self_drive':
        if context.high_speed_rail_available is True:
            check('R11',None if context.driving_total is None or context.comparison_fare is None else context.driving_total>context.comparison_fare,
                '燃油/充电、停车和路桥合计与本人适用高铁票价比较',{'total':str(context.driving_total),'comparison':str(context.comparison_fare)})
        else:
            add('R11','needs_evidence','无高铁或条件未确认，需核对同距离打车比较价及交通补助扣减')
    else:
        add('R11','not_applicable' if context.expense_type!='unknown' else 'needs_evidence','自驾比较规则仅适用于因公自驾')
    if context.expense_type=='telecom':
        check('R12',context.telecom_already_paid,'需核对工资通讯补助，个人补助不得再次贴票报销')
    else:
        add('R12','not_applicable' if context.expense_type!='unknown' else 'needs_evidence','需区分个人通讯补助与企业通信服务')
    check('R13',context.sole_trader_risk,'个体工商户风险需增强核验，不能据此认定假票')
    duplicate=context.duplicate_risk
    if context.claimed_amount is not None and context.remaining_allocatable is not None and context.claimed_amount>context.remaining_allocatable:
        duplicate=True
    check('R14',duplicate,'需核对跨单历史记录、退款和合法分摊，不能仅凭相似度查重')
    submitted=context.submitted_date or date.today()
    deadline=(date(issued.year+1,1,31) if issued.month==12 else date(issued.year,12,31)) if issued else None
    late=None if not issued else submitted>deadline or issued>submitted or (context.expense_type=='entertainment' and submitted.year>issued.year)
    check('R15',late,'跨年或逾期需人工核对结转清单、特殊类别时限',{'issue_date':str(issued),'submitted_date':str(submitted),'ordinary_deadline':str(deadline)})
    if context.expense_type=='fuel':
        check('R16',context.prepaid_fuel,'充值不得直接作为燃油耗用，需实际消费凭证')
    else:
        add('R16','not_applicable' if context.expense_type!='unknown' else 'needs_evidence','燃油充值需按预付流程核销')
    check('R17',None if context.original_electronic_file is None else not context.original_electronic_file,
        '文件为PDF不代表已取得开票原件，需核验原始电子凭证')
    check('R18',True,'当前制度为未签发草案，且含待确认口径，必须人工复核')
    lodging_id=bundle['lodging']['clause_id']
    if context.expense_type=='lodging':
        if not all([context.employee_grade,context.city,context.lodging_nights]) or context.lodging_amount is None:
            add('LODGING','needs_evidence','需提供人员档位、城市、实际住宿夜数及房费，不能拿发票总额直接套住宿标准',clause_id=lodging_id)
        else:
            city=context.city.removesuffix('市')
            nightly=Decimal(bundle['lodging']['limits'][context.employee_grade][int(city in ['北京','上海','广州','深圳'])])
            cap=nightly*context.lodging_nights
            add('LODGING','flagged' if context.lodging_amount>cap else 'pass',
                '单人住宿基础上限比较；还需核对国内适用范围、每晚房费、水单、免费住宿、分摊及特殊授权',
                {'nightly_limit':str(nightly),'nights':context.lodging_nights,'cap':str(cap),'actual':str(context.lodging_amount)},lodging_id)
        add('HOTEL_ATTACHMENT','pass' if context.hotel_statement else 'needs_evidence','需提供酒店水单和真实入住人夜记录',clause_id=lodging_id)
    buyer_clause=next(c for c in bundle['clauses'] if c['document_id']=='BX-06' and c['section']=='第一条 票据审核')
    if context.expected_buyer and fields.get('buyer_name'):
        add('BUYER','pass' if context.expected_buyer.strip()==fields['buyer_name'].strip() else 'flagged',
            '购方与申报承担法人比较；正式审核仍需企业主数据核验',clause_id=buyer_clause['id'])
    review_clause=next(c for c in bundle['clauses'] if c['document_id']=='BX-06' and c['section']=='第二条 验真与查重')
    add('AUTHENTICITY','needs_evidence','尚未接入官方验真、预算、历史台账与审批证据验证；未发现问题不等于合规通过',clause_id=review_clause['id'])
    issues=[c for c in checks if c['status'] in ['flagged','needs_evidence']]
    return {'decision':'manual_review','decision_label':'需人工复核','eligible_for_auto_approval':False,
        'risk_level':'medium','policy_version':bundle['version'],'policy_status':'draft',
        'checks':checks,'reasons':[{'code':c['rule_id'],'message':c['message']} for c in issues],
        'summary':f'已执行{len(checks)}项检查，{len(issues)}项需处理或补充证据。草案预审不等于最终审批。',
        'context_source':'用户申报，未独立核验'}
