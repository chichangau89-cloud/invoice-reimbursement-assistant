import unittest

from document_review_service import document_kind, extract_approval_fields, extract_trip_fields, material_checks


class DocumentReviewTests(unittest.TestCase):
    def test_classifies_supported_business_materials(self):
        self.assertEqual(document_kind('住宿行程单.pdf', '入住人：张三'), 'itinerary')
        self.assertEqual(document_kind('出差审批单.pdf', '审批编号：AP-100'), 'approval')
        self.assertEqual(document_kind('电子发票.pdf', '价税合计：100.00'), 'invoice')

    def test_extracts_trip_and_approval_identifiers(self):
        trip = extract_trip_fields('乘车人：张三\n出发日期：2026-09-16\n订单号：TRIP-100')
        approval = extract_approval_fields('审批编号：AP-100\n审批日期：2026-09-15')
        self.assertEqual(trip['departure_date'], '2026-09-16')
        self.assertEqual(trip['order_no'], 'TRIP-100')
        self.assertEqual(approval['approval_no'], 'AP-100')

    def test_duplicate_and_missing_itinerary_are_not_auto_passed(self):
        checks = material_checks(
            [{'kind': 'invoice', 'fields': {}}],
            {'invoice_no': 'INV-1', 'issue_date': '2026-09-16', 'amount': 680},
            {'status': 'matched', 'reason': 'exact', 'items': [{'claim_no': 'C-1'}]},
            'lodging',
        )
        statuses = {row['rule_id']: row['status'] for row in checks}
        self.assertEqual(statuses['M02'], 'needs_evidence')
        self.assertEqual(statuses['M04'], 'flagged')


if __name__ == '__main__':
    unittest.main()
