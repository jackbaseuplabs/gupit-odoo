"""Tests for PDC batch deposit and payment_channel computation."""
from odoo import fields
from odoo.tests.common import TransactionCase
from odoo.exceptions import UserError


class TestPDCBatchDeposit(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.journal = cls.env['account.journal'].search(
            [('type', '=', 'bank')], limit=1
        )
        cls.partner = cls.env['res.partner'].create({'name': 'Batch PDC Customer'})

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

    def _create_pdc_payment(self, state='draft'):
        if not self.check_method_line:
            self.skipTest("Check payment method line not available")
        payment = self.env['account.payment'].create({
            'payment_type': 'inbound',
            'partner_type': 'customer',
            'partner_id': self.partner.id,
            'amount': 100.0,
            'journal_id': self.journal.id,
            'payment_method_line_id': self.check_method_line.id,
        })
        if state != 'draft':
            payment.write({'state': state})
        return payment

    def _create_bank_payment(self, state='draft'):
        payment = self.env['account.payment'].create({
            'payment_type': 'inbound',
            'partner_type': 'customer',
            'partner_id': self.partner.id,
            'amount': 100.0,
            'journal_id': self.journal.id,
        })
        if state != 'draft':
            payment.write({'state': state})
        return payment

    # ------------------------------------------------------------------ #
    #  payment_channel compute                                             #
    # ------------------------------------------------------------------ #

    def test_payment_channel_pdc(self):
        """PDC payment has payment_channel='pdc'."""
        payment = self._create_pdc_payment()
        self.assertEqual(payment.payment_channel, 'pdc')

    def test_payment_channel_bank(self):
        """Non-PDC bank payment has payment_channel='bank'."""
        payment = self._create_bank_payment()
        if payment.payment_method_code == 'check':
            self.skipTest("Default method is check on this journal")
        self.assertEqual(payment.payment_channel, 'bank')

    # ------------------------------------------------------------------ #
    #  action_batch_deposit                                                #
    # ------------------------------------------------------------------ #

    def test_batch_deposit_non_pdc_raises(self):
        """action_batch_deposit raises UserError if any payment is not PDC."""
        pdc = self._create_pdc_payment(state='in_process')
        bank = self._create_bank_payment(state='in_process')
        if bank.payment_method_code == 'check':
            self.skipTest("Default method is check on this journal")
        payments = pdc | bank
        with self.assertRaises(UserError):
            payments.action_batch_deposit()

    def test_batch_deposit_wrong_state_raises(self):
        """action_batch_deposit raises UserError if any payment is not in_process."""
        p1 = self._create_pdc_payment(state='in_process')
        p2 = self._create_pdc_payment(state='draft')
        payments = p1 | p2
        with self.assertRaises(UserError):
            payments.action_batch_deposit()

    def test_batch_deposit_returns_wizard_action(self):
        """action_batch_deposit returns wizard action for valid PDC payments."""
        p1 = self._create_pdc_payment(state='in_process')
        p2 = self._create_pdc_payment(state='in_process')
        payments = p1 | p2
        result = payments.action_batch_deposit()
        self.assertEqual(result.get('res_model'), 'gupit.deposit.wizard')
        self.assertIn('default_payment_ids', result.get('context', {}))

    # ------------------------------------------------------------------ #
    #  Deposit wizard batch mode                                           #
    # ------------------------------------------------------------------ #

    def test_deposit_wizard_batch_confirms_all(self):
        """Deposit wizard with payment_ids deposits all payments."""
        p1 = self._create_pdc_payment(state='in_process')
        p2 = self._create_pdc_payment(state='in_process')
        deposit_date = fields.Date.today()
        wizard = self.env['gupit.deposit.wizard'].create({
            'payment_ids': [(6, 0, [p1.id, p2.id])],
            'deposited_date': deposit_date,
        })
        wizard.action_confirm()
        self.assertEqual(p1.state, 'deposited')
        self.assertEqual(p2.state, 'deposited')
        self.assertEqual(p1.deposited_date, deposit_date)
        self.assertEqual(p2.deposited_date, deposit_date)

    def test_deposit_wizard_no_payments_raises(self):
        """Deposit wizard with no payments raises UserError."""
        wizard = self.env['gupit.deposit.wizard'].create({
            'deposited_date': fields.Date.today(),
        })
        with self.assertRaises(UserError):
            wizard.action_confirm()

    def test_deposit_wizard_batch_mixed_states_raises(self):
        """Deposit wizard with mixed-state payments raises UserError."""
        p1 = self._create_pdc_payment(state='in_process')
        p2 = self._create_pdc_payment(state='deposited')
        wizard = self.env['gupit.deposit.wizard'].create({
            'payment_ids': [(6, 0, [p1.id, p2.id])],
            'deposited_date': fields.Date.today(),
        })
        with self.assertRaises(UserError):
            wizard.action_confirm()
