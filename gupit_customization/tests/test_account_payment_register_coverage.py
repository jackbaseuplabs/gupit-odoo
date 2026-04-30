"""Coverage tests for gupit_customization account_payment_register.py extensions.

Covers:
- _compute_check_date: defaults to payment_date
- _check_payment_date_within_allowed_period: ValidationError paths, December/January
  edge cases, admin vs non-admin
- _create_payment_vals_from_wizard: check method adds extra fields
"""
from datetime import date
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase


class TestAccountPaymentRegisterCoverage(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Find bank journal and a customer invoice to register payment on
        cls.journal = cls.env['account.journal'].search([('type', '=', 'bank')], limit=1)
        cls.partner = cls.env['res.partner'].create({
            'name': 'APR Coverage Test Customer'
        })

        # Find or create the check payment method on the bank journal
        check_method = cls.env['account.payment.method'].search(
            [('code', '=', 'check')], limit=1
        )
        cls.check_method_line = False
        if check_method and cls.journal:
            cls.check_method_line = cls.env['account.payment.method.line'].search([
                ('payment_method_id', '=', check_method.id),
                ('journal_id', '=', cls.journal.id),
            ], limit=1)
            if not cls.check_method_line:
                cls.check_method_line = cls.env['account.payment.method.line'].create({
                    'name': 'Check',
                    'payment_method_id': check_method.id,
                    'journal_id': cls.journal.id,
                })

    def _create_posted_invoice(self):
        """Create and post a customer invoice for use in register payment wizard."""
        income_account = self.env['account.account'].search([
            ('account_type', '=', 'income'),
            ('company_ids', 'in', self.env.company.id),
        ], limit=1)
        product = self.env['product.product'].search([('type', '=', 'consu')], limit=1)
        if not product:
            product = self.env['product.product'].create({
                'name': 'APR Test Product',
                'type': 'consu',
                'list_price': 100.0,
            })
        invoice = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': self.partner.id,
            'invoice_date': fields.Date.today(),
            'document_number': 'APR-TEST',
            'invoice_line_ids': [(0, 0, {
                'product_id': product.id,
                'name': 'Test line',
                'quantity': 1.0,
                'price_unit': 500.0,
                'account_id': income_account.id,
            })],
        })
        invoice.action_post()
        return invoice

    def _create_register_wizard(self, invoice=None, payment_date=None):
        """Create an account.payment.register wizard for an invoice."""
        if invoice is None:
            invoice = self._create_posted_invoice()
        ctx = {
            'active_model': 'account.move',
            'active_ids': [invoice.id],
        }
        vals = {}
        if payment_date:
            vals['payment_date'] = payment_date
        if self.journal:
            vals['journal_id'] = self.journal.id
        return self.env['account.payment.register'].with_context(**ctx).create(vals)

    # ------------------------------------------------------------------ #
    #  _compute_check_date                                                 #
    # ------------------------------------------------------------------ #

    def test_compute_check_date_defaults_to_payment_date(self):
        """check_date is computed from payment_date by default."""
        wizard = self._create_register_wizard()
        # check_date should equal payment_date (default)
        self.assertEqual(wizard.check_date, wizard.payment_date)

    def test_compute_check_date_updates_when_payment_date_changes(self):
        """check_date updates when payment_date is changed."""
        wizard = self._create_register_wizard()
        new_date = fields.Date.today()
        wizard.payment_date = new_date
        # Trigger recompute
        wizard._compute_check_date()
        self.assertEqual(wizard.check_date, new_date)

    # ------------------------------------------------------------------ #
    #  _check_payment_date_within_allowed_period — ValidationError paths  #
    # ------------------------------------------------------------------ #

    def test_payment_date_constraint_past_date_raises(self):
        """Payment date far in the past raises ValidationError."""
        # Dec 2024 is outside any allowed window
        with self.assertRaises(ValidationError):
            self._create_register_wizard(payment_date=date(2024, 12, 1))

    def test_payment_date_constraint_future_date_raises(self):
        """Payment date beyond current month raises ValidationError."""
        today = fields.Date.today()
        future_date = date(today.year + 1, today.month, 1)
        with self.assertRaises(ValidationError):
            self._create_register_wizard(payment_date=future_date)

    def test_payment_date_constraint_non_admin_previous_month_raises(self):
        """Non-admin user cannot use previous month date for payment."""
        non_admin = self.env['res.users'].create({
            'name': 'APR Coverage Non-Admin',
            'login': 'apr_coverage_non_admin@test.com',
            'group_ids': [(6, 0, [
                self.env.ref('base.group_user').id,
                self.env.ref('account.group_account_invoice').id,
            ])],
        })
        today = fields.Date.today()
        # Previous month's date
        if today.month == 1:
            prev_date = today.replace(year=today.year - 1, month=12, day=1)
        else:
            prev_date = today.replace(month=today.month - 1, day=1)

        invoice = self._create_posted_invoice()
        ctx = {
            'active_model': 'account.move',
            'active_ids': [invoice.id],
        }
        with self.assertRaises(ValidationError):
            self.env['account.payment.register'].with_user(non_admin).with_context(**ctx).create({
                'payment_date': prev_date,
                'journal_id': self.journal.id if self.journal else False,
            })

    def test_payment_date_constraint_december_edge_case(self):
        """December: current_month_end == Dec 31 is computed correctly (line 36-39 covered)."""
        invoice = self._create_posted_invoice()
        fake_today = date(2025, 12, 15)
        with patch.object(fields.Date, 'context_today', return_value=fake_today):
            ctx = {
                'active_model': 'account.move',
                'active_ids': [invoice.id],
            }
            # Dec 20 is within December — should pass
            wizard = self.env['account.payment.register'].with_context(**ctx).create({
                'payment_date': date(2025, 12, 20),
                'journal_id': self.journal.id if self.journal else False,
            })
        self.assertEqual(wizard.payment_date, date(2025, 12, 20))

    def test_payment_date_constraint_admin_january_allows_december(self):
        """Admin in January can use previous December (line 43-44 covered)."""
        invoice = self._create_posted_invoice()
        fake_today = date(2026, 1, 15)
        with patch.object(fields.Date, 'context_today', return_value=fake_today):
            ctx = {
                'active_model': 'account.move',
                'active_ids': [invoice.id],
            }
            # Dec 15, 2025 is previous month — valid for admin
            wizard = self.env['account.payment.register'].with_context(**ctx).create({
                'payment_date': date(2025, 12, 15),
                'journal_id': self.journal.id if self.journal else False,
            })
        self.assertEqual(wizard.payment_date, date(2025, 12, 15))

    # ------------------------------------------------------------------ #
    #  _create_payment_vals_from_wizard — check method adds fields         #
    # ------------------------------------------------------------------ #

    def test_create_payment_vals_from_wizard_includes_check_fields(self):
        """When payment method is 'check', wizard adds check_date/reference/comment."""
        if not self.check_method_line:
            self.skipTest("Check payment method line not available on bank journal")

        invoice = self._create_posted_invoice()
        ctx = {
            'active_model': 'account.move',
            'active_ids': [invoice.id],
        }
        wizard = self.env['account.payment.register'].with_context(**ctx).create({
            'payment_date': fields.Date.today(),
            'journal_id': self.journal.id,
            'payment_method_line_id': self.check_method_line.id,
            'payment_channel': 'pdc',
            'check_reference': 'CHK-001',
            'check_comment': 'Test comment',
            'reference_cr_number': 'CR-001',
        })

        # In Odoo 19, batches is a computed Binary field (replaces _get_batches())
        batches = wizard.batches
        if not batches:
            self.skipTest("No batches computed by wizard")

        vals = wizard._create_payment_vals_from_wizard(batches[0])
        self.assertIn('check_reference', vals)
        self.assertEqual(vals['check_reference'], 'CHK-001')
        self.assertIn('check_comment', vals)
        self.assertEqual(vals['check_comment'], 'Test comment')
        self.assertIn('reference_cr_number', vals)
        self.assertEqual(vals['reference_cr_number'], 'CR-001')
        self.assertIn('check_date', vals)
