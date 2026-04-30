from odoo import api, fields, models, _
from odoo.exceptions import UserError


class AccountPayment(models.Model):
    _inherit = 'account.payment'

    is_pdc = fields.Boolean(
        string="Is PDC",
        compute='_compute_is_pdc',
        store=True,
    )
    check_date = fields.Date(
        string="Check Date",
    )
    check_reference = fields.Char(
        string="Check/BTB Number",
    )
    check_comment = fields.Text(
        string="Comment",
    )
    reference_cr_number = fields.Char(
        string="Reference/CR Number",
    )
    deposited_date = fields.Date(
        string="Deposited Date",
        readonly=True,
    )
    clear_date = fields.Date(
        string="Clear Date",
        readonly=True,
    )

    payment_channel = fields.Selection([
        ('bank', 'Bank'),
        ('pdc', 'Post Dated Check'),
    ], string='Payment Channel',
        default=lambda self: 'pdc' if self.env.context.get('default_payment_method_code') == 'check' else 'bank',
    )

    @api.model_create_multi
    def create(self, vals_list):
        """Auto-default payment_channel to 'pdc' when creating with the check payment method.

        Field stays plain (not computed) after creation so manual user edits persist on save.
        """
        Method = self.env['account.payment.method.line']
        for vals in vals_list:
            if vals.get('payment_channel'):
                continue
            method_line_id = vals.get('payment_method_line_id')
            if method_line_id and Method.browse(method_line_id).payment_method_id.code == 'check':
                vals['payment_channel'] = 'pdc'
        return super().create(vals_list)

    @api.depends('payment_method_code')
    def _compute_is_pdc(self):
        for payment in self:
            payment.is_pdc = payment.payment_method_code == 'check'

    # --- Selection extension ------------------------------------------------

    state = fields.Selection(
        selection_add=[
            ('deposited', "Deposited"),
            ('bounced', "Bounced"),
            ('pulled_out', "Pulled Out"),
        ],
        ondelete={
            'deposited': 'set default',
            'bounced': 'set default',
            'pulled_out': 'set default',
        },
    )

    # --- Compute overrides --------------------------------------------------

    @api.depends('reconciled_invoice_ids.payment_state', 'move_id.line_ids.amount_residual')
    def _compute_state(self):
        # Preserve custom PDC states – the core compute only handles
        # transitions between in_process / paid, so we skip records that
        # are already in one of our extended states.
        pdc_states = {'deposited', 'bounced', 'pulled_out'}
        pdc_payments = self.filtered(lambda p: p.state in pdc_states)
        super(AccountPayment, self - pdc_payments)._compute_state()

    def _compute_reconciliation_status(self):
        """Treat validated PDC payments as matched so invoices become 'paid'."""
        super()._compute_reconciliation_status()
        for pay in self:
            if pay.payment_channel == 'pdc' and pay.state == 'paid':
                pay.is_matched = True

    # --- Action methods -----------------------------------------------------

    def action_deposit(self):
        """Open the deposit wizard to capture the deposited date."""
        self.ensure_one()
        if self.state != 'in_process':
            raise UserError(_("Only payments in 'In Process' state can be deposited."))
        return {
            'name': _("Deposit Check"),
            'type': 'ir.actions.act_window',
            'res_model': 'gupit.deposit.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_payment_id': self.id},
        }

    def action_batch_deposit(self):
        """Open the deposit wizard for multiple PDC payments from list view."""
        non_pdc = self.filtered(lambda p: p.payment_channel != 'pdc')
        if non_pdc:
            raise UserError(_("Only PDC (Check) payments can be deposited."))
        invalid_state = self.filtered(lambda p: p.state != 'in_process')
        if invalid_state:
            raise UserError(_("Only payments in 'In Process' state can be deposited."))
        return {
            'name': _("Deposit Check"),
            'type': 'ir.actions.act_window',
            'res_model': 'gupit.deposit.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_payment_ids': [(6, 0, self.ids)]},
        }

    def action_validate(self):
        """Override to allow validation from deposited state for PDC."""
        invalid_pdc = self.filtered(lambda p: p.payment_channel == 'pdc' and p.state != 'deposited')
        if invalid_pdc:
            names = ', '.join(invalid_pdc.mapped('name'))
            raise UserError(_(
                "PDC payments can only be validated from 'Deposited' state. "
                "The following cannot be validated: %s"
            ) % names)
        today = fields.Date.today()
        for payment in self:
            if payment.payment_channel == 'pdc' and payment.state == 'deposited':
                payment.state = 'paid'
                payment.clear_date = today
                payment._create_bank_statement_line_for_pdc()
            else:
                super(AccountPayment, payment).action_validate()

    def action_bounced(self):
        """Move payment to Bounced and cancel the journal entry."""
        invalid = self.filtered(lambda p: p.state != 'deposited')
        if invalid:
            names = ', '.join(invalid.mapped('name'))
            raise UserError(_(
                "Only deposited payments can be marked as bounced. "
                "The following cannot be bounced: %s"
            ) % names)
        for payment in self:
            payment.state = 'bounced'
            draft_moves = payment.move_id.filtered(lambda m: m.state == 'draft')
            draft_moves.unlink()
            (payment.move_id - draft_moves).button_cancel()

    def action_pulled_out(self):
        """Move payment to Pulled Out and cancel the journal entry."""
        invalid = self.filtered(lambda p: p.state != 'deposited')
        if invalid:
            names = ', '.join(invalid.mapped('name'))
            raise UserError(_(
                "Only deposited payments can be pulled out. "
                "The following cannot be pulled out: %s"
            ) % names)
        for payment in self:
            payment.state = 'pulled_out'
            draft_moves = payment.move_id.filtered(lambda m: m.state == 'draft')
            draft_moves.unlink()
            (payment.move_id - draft_moves).button_cancel()

    # --- Bank statement line for cleared PDC -----------------------------------

    def _create_bank_statement_line_for_pdc(self):
        """Create a bank statement line when a PDC is validated/cleared.

        This line appears in the bank reconciliation widget for matching.
        """
        self.ensure_one()
        sign = 1 if self.payment_type == 'inbound' else -1

        # Build reference: Invoice Number - Payment Name - Check Number
        parts = []
        invoice_names = self.reconciled_invoice_ids.mapped('name')
        if invoice_names:
            parts.append(', '.join(n for n in invoice_names if n))
        if self.name:
            parts.append(self.name)
        if self.check_reference:
            parts.append(self.check_reference)
        payment_ref = ' - '.join(parts) or self.name

        self.env['account.bank.statement.line'].create({
            'date': self.clear_date or fields.Date.today(),
            'journal_id': self.journal_id.id,
            'payment_ref': payment_ref,
            'partner_id': self.partner_id.id,
            'amount': sign * self.amount,
        })
