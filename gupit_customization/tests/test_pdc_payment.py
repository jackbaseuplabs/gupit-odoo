"""Coverage tests for PDC payment method, account.payment extensions, and deposit wizard.

Covers:
- account_payment_method.py: _get_payment_method_information (check method registration)
- account_payment.py: _compute_is_pdc, _compute_state (PDC state preservation),
  _compute_reconciliation_status, action_deposit, action_validate (deposited→paid),
  action_bounced, action_pulled_out
- deposit_wizard.py: action_confirm (error path and happy path)
"""
from odoo import fields
from odoo.tests.common import TransactionCase
from odoo.exceptions import UserError


class TestPDCPayment(TransactionCase):
    """Tests for PDC payment method registration and deposit wizard."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.journal = cls.env['account.journal'].search(
            [('type', '=', 'bank')], limit=1
        )
        cls.partner = cls.env['res.partner'].search(
            [('customer_rank', '>', 0)], limit=1
        )
        if not cls.partner:
            cls.partner = cls.env['res.partner'].create({'name': 'PDC Test Customer'})

        # Find or create the check payment method line on the bank journal
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

    def _create_draft_payment(self, use_check_method=False):
        self.assertTrue(self.journal, "No bank journal found — cannot run PDC tests")
        vals = {
            'payment_type': 'inbound',
            'partner_type': 'customer',
            'partner_id': self.partner.id,
            'amount': 100.0,
            'journal_id': self.journal.id,
        }
        if use_check_method and self.check_method_line:
            vals['payment_method_line_id'] = self.check_method_line.id
        return self.env['account.payment'].create(vals)

    def _create_payment_in_state(self, state, use_check_method=False):
        """Create a draft payment and force it to the given state."""
        payment = self._create_draft_payment(use_check_method=use_check_method)
        payment.write({'state': state})
        return payment

    # ------------------------------------------------------------------ #
    #  PAYMENT METHOD REGISTRATION                                         #
    # ------------------------------------------------------------------ #

    def test_get_payment_method_information(self):
        """The 'check' payment method is registered with mode='multi' for bank journals."""
        result = self.env['account.payment.method']._get_payment_method_information()
        self.assertIn('check', result)
        self.assertEqual(result['check']['mode'], 'multi')
        self.assertIn('bank', result['check']['type'])

    # ------------------------------------------------------------------ #
    #  _compute_is_pdc                                                     #
    # ------------------------------------------------------------------ #

    def test_compute_is_pdc_with_check_method(self):
        """Payment with check method line has is_pdc=True."""
        if not self.check_method_line:
            self.skipTest("Check payment method line not available on bank journal")
        payment = self._create_draft_payment(use_check_method=True)
        self.assertTrue(payment.is_pdc, "Payment with check method should have is_pdc=True")

    def test_compute_is_pdc_without_check_method(self):
        """Payment without check method has is_pdc=False."""
        payment = self._create_draft_payment(use_check_method=False)
        # Verify: if no check method line is used, is_pdc should be False
        # (payment_method_code != 'check')
        if payment.payment_method_code != 'check':
            self.assertFalse(payment.is_pdc)

    # ------------------------------------------------------------------ #
    #  _compute_state — PDC state preservation                             #
    # ------------------------------------------------------------------ #

    def test_compute_state_preserves_deposited(self):
        """_compute_state skips payments already in 'deposited' state."""
        payment = self._create_payment_in_state('deposited')
        # Call _compute_state directly — our override should skip this payment
        payment._compute_state()
        self.assertEqual(payment.state, 'deposited')

    def test_compute_state_preserves_bounced(self):
        """_compute_state skips payments already in 'bounced' state."""
        payment = self._create_payment_in_state('bounced')
        payment._compute_state()
        self.assertEqual(payment.state, 'bounced')

    def test_compute_state_preserves_pulled_out(self):
        """_compute_state skips payments already in 'pulled_out' state."""
        payment = self._create_payment_in_state('pulled_out')
        payment._compute_state()
        self.assertEqual(payment.state, 'pulled_out')

    # ------------------------------------------------------------------ #
    #  _compute_reconciliation_status                                      #
    # ------------------------------------------------------------------ #

    def test_compute_reconciliation_status_paid_pdc_is_matched(self):
        """PDC payment in 'paid' state has is_matched=True after reconciliation compute."""
        if not self.check_method_line:
            self.skipTest("Check payment method line not available")
        payment = self._create_draft_payment(use_check_method=True)
        payment.write({'state': 'paid'})
        payment._compute_reconciliation_status()
        self.assertTrue(payment.is_matched)

    # ------------------------------------------------------------------ #
    #  action_deposit                                                      #
    # ------------------------------------------------------------------ #

    def test_action_deposit_wrong_state_raises(self):
        """action_deposit raises UserError when payment is not in 'in_process'."""
        payment = self._create_draft_payment()
        self.assertEqual(payment.state, 'draft')
        with self.assertRaises(UserError):
            payment.action_deposit()

    def test_action_deposit_in_process_returns_wizard_action(self):
        """action_deposit on an in_process payment returns a wizard action."""
        payment = self._create_payment_in_state('in_process')
        result = payment.action_deposit()
        self.assertEqual(result.get('res_model'), 'gupit.deposit.wizard')

    # ------------------------------------------------------------------ #
    #  action_validate                                                     #
    # ------------------------------------------------------------------ #

    def test_action_validate_deposited_pdc_sets_paid(self):
        """action_validate on a deposited PDC payment moves it to 'paid'."""
        if not self.check_method_line:
            self.skipTest("Check payment method line not available")
        payment = self._create_draft_payment(use_check_method=True)
        payment.write({'state': 'deposited'})
        self.assertTrue(payment.is_pdc)
        payment.action_validate()
        self.assertEqual(payment.state, 'paid')

    # ------------------------------------------------------------------ #
    #  action_bounced                                                      #
    # ------------------------------------------------------------------ #

    def test_action_bounced_from_non_deposited_raises(self):
        """action_bounced raises UserError when payment is not deposited."""
        payment = self._create_payment_in_state('in_process')
        with self.assertRaises(UserError):
            payment.action_bounced()

    def test_action_bounced_from_deposited_sets_state(self):
        """action_bounced from deposited state sets state to 'bounced'."""
        payment = self._create_payment_in_state('deposited')
        payment.action_bounced()
        self.assertEqual(payment.state, 'bounced')

    # ------------------------------------------------------------------ #
    #  action_pulled_out                                                   #
    # ------------------------------------------------------------------ #

    def test_action_pulled_out_from_non_deposited_raises(self):
        """action_pulled_out raises UserError when payment is not deposited."""
        payment = self._create_payment_in_state('in_process')
        with self.assertRaises(UserError):
            payment.action_pulled_out()

    def test_action_pulled_out_from_deposited_sets_state(self):
        """action_pulled_out from deposited state sets state to 'pulled_out'."""
        payment = self._create_payment_in_state('deposited')
        payment.action_pulled_out()
        self.assertEqual(payment.state, 'pulled_out')

    # ------------------------------------------------------------------ #
    #  DEPOSIT WIZARD — happy path                                         #
    # ------------------------------------------------------------------ #

    def test_deposit_wizard_wrong_state_raises(self):
        """action_confirm raises UserError when payment is not in 'in_process' state."""
        payment = self._create_draft_payment()
        self.assertEqual(payment.state, 'draft')
        wizard = self.env['gupit.deposit.wizard'].create({
            'payment_id': payment.id,
            'deposited_date': fields.Date.today(),
        })
        with self.assertRaises(UserError):
            wizard.action_confirm()

    def test_deposit_wizard_confirm_sets_deposited_state(self):
        """action_confirm on a wizard for an in_process payment sets state to deposited."""
        payment = self._create_payment_in_state('in_process')
        deposit_date = fields.Date.today()
        wizard = self.env['gupit.deposit.wizard'].create({
            'payment_id': payment.id,
            'deposited_date': deposit_date,
        })
        result = wizard.action_confirm()
        self.assertEqual(payment.state, 'deposited')
        self.assertEqual(payment.deposited_date, deposit_date)
        self.assertEqual(result.get('type'), 'ir.actions.act_window_close')

    # ------------------------------------------------------------------ #
    #  _compute_payment_channel — edge cases                               #
    # ------------------------------------------------------------------ #

    def test_compute_payment_channel_bank_for_bank_journal(self):
        """payment_channel is 'bank' for bank journal without check method."""
        payment = self._create_draft_payment(use_check_method=False)
        if payment.journal_id.type == 'bank' and payment.payment_method_code != 'check':
            self.assertEqual(payment.payment_channel, 'bank')

    # ------------------------------------------------------------------ #
    #  action_validate — clear_date and invalid PDC                        #
    # ------------------------------------------------------------------ #

    def test_action_validate_sets_clear_date(self):
        """action_validate on deposited PDC sets clear_date to today."""
        if not self.check_method_line:
            self.skipTest("Check payment method line not available")
        payment = self._create_draft_payment(use_check_method=True)
        payment.write({'state': 'deposited'})
        payment.action_validate()
        self.assertEqual(payment.state, 'paid')
        self.assertEqual(payment.clear_date, fields.Date.today())

    def test_action_validate_invalid_pdc_not_deposited_raises(self):
        """action_validate raises UserError when PDC is not in deposited state."""
        if not self.check_method_line:
            self.skipTest("Check payment method line not available")
        payment = self._create_draft_payment(use_check_method=True)
        payment.write({'state': 'in_process'})
        self.assertTrue(payment.is_pdc)
        with self.assertRaises(UserError):
            payment.action_validate()

    # ------------------------------------------------------------------ #
    #  _compute_payment_channel                                            #
    # ------------------------------------------------------------------ #

    def test_compute_payment_channel_pdc_from_check_method(self):
        """Payment with check method computes payment_channel='pdc'."""
        if not self.check_method_line:
            self.skipTest("Check payment method line not available")
        payment = self._create_draft_payment()
        payment.payment_method_line_id = self.check_method_line
        self.assertEqual(payment.payment_channel, 'pdc')

    def test_compute_payment_channel_bank_from_non_check_method(self):
        """Payment without check method computes payment_channel='bank'."""
        payment = self._create_draft_payment()
        if payment.payment_method_code == 'check':
            self.skipTest("Default method is check on this journal")
        self.assertEqual(payment.payment_channel, 'bank')
