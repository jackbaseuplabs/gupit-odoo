from odoo import fields, models, _
from odoo.exceptions import UserError


class DepositWizard(models.TransientModel):
    _name = 'gupit.deposit.wizard'
    _description = 'Deposit Check Wizard'

    payment_id = fields.Many2one(
        'account.payment',
        string="Payment",
    )
    payment_ids = fields.Many2many(
        'account.payment',
        string="Payments",
    )
    deposited_date = fields.Date(
        string="Deposited Date",
        required=True,
        default=fields.Date.context_today,
    )

    def action_confirm(self):
        self.ensure_one()
        payments = self.payment_ids or self.payment_id
        if not payments:
            raise UserError(_("No payments selected."))
        invalid = payments.filtered(lambda p: p.state != 'in_process')
        if invalid:
            names = ', '.join(n or _("Unknown") for n in invalid.mapped('name'))
            raise UserError(_(
                "Only payments in 'In Process' state can be deposited. "
                "The following cannot be deposited: %s"
            ) % names)
        payments.write({
            'deposited_date': self.deposited_date,
            'state': 'deposited',
        })
        return {'type': 'ir.actions.act_window_close'}
