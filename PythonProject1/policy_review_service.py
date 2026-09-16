"""Policy pre-audit grounded in the imported Markdown version."""
from policy_audit import evaluate, verified_bundle, AuditContext
from policy_search import search_policies, PolicyUnavailable


def review_invoice(fields: dict, context: AuditContext) -> dict:
    try:
        bundle=verified_bundle()
    except Exception:
        return {'decision':'manual_review','decision_label':'需人工复核','eligible_for_auto_approval':False,
            'risk_level':'medium','policy_source':'unavailable','policy_hits':[], 'checks':[],
            'reasons':[{'code':'POLICY_UNAVAILABLE','message':'条款版本未就绪或数据库核验失败，未执行合规通过判断。'}],
            'summary':'制度依据不可用，请检查入库版本和数据库连接。'}
    result=evaluate(fields,context,bundle)
    descriptions={'lodging':'住宿费用城市职级每人每夜限额酒店水单','entertainment':'业务招待餐费人数预算事前审批',
        'office':'办公采购合同清单验收','self_drive':'自驾高铁比较价交通补助','fuel':'车辆燃油充值实际消费',
        'telecom':'个人通讯补助工资重复报销','loan':'借款备用金在途核销','transport':'市内交通行程补助'}
    query=descriptions.get(context.expense_type,'发票支付证明购方验真查重报销时限')
    try:
        found=search_policies(query,5)
        if found['tenant_id']!=bundle['tenant_id']:
            raise PolicyUnavailable('检索租户与审核条款不一致')
        result.update(policy_hits=found['items'],policy_source='milvus+mysql')
    except PolicyUnavailable:
        result.update(policy_hits=[],policy_source='mysql_rules_only')
        result['reasons'].append({'code':'RETRIEVAL_UNAVAILABLE','message':'补充语义召回不可用；已按MySQL核验的完整规则执行预审。'})
    return result
