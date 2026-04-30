from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
from datetime import timedelta


class AccountPaymentRegister(models.TransientModel):
    _inherit = 'account.payment.register'

    check_date = fields.Date(
        string="Check Date",
        compute='_compute_check_date',
        store=True,
        readonly=False,
    )
    check_reference = fields.Char(string="Check/BTB Number")
    check_comment = fields.Text(string="Comment")
    reference_cr_number = fields.Char(string="Reference/CR Number")

    payment_channel = fields.Selection([
        ('bank', 'Bank'),
        ('pdc', 'Post Dated Check'),
    ], string='Payment Channel',
    )

    @api.depends('payment_date')
    def _compute_check_date(self):
        for wizard in self:
            wizard.check_date = wizard.payment_date

    @api.constrains('payment_date')
    def _check_payment_date_within_allowed_period(self):
        """Restrict payment date: current month (or previous month for admins)."""
        for wizard in self:
            if not wizard.payment_date:
                continue

            is_admin = self.env.user.has_group('base.group_system')
            today = fields.Date.context_today(self)
            current_month_start = today.replace(day=1)

            if today.month == 12:
                current_month_end = today.replace(day=31)
            else:
                next_month = today.replace(month=today.month + 1, day=1)
                current_month_end = next_month - timedelta(days=1)

            if is_admin:
                if today.month == 1:
                    prev_month_start = today.replace(year=today.year - 1, month=12, day=1)
                else:
                    prev_month_start = today.replace(month=today.month - 1, day=1)
                allowed_start = prev_month_start
                allowed_period = 'current or previous month'
            else:
                allowed_start = current_month_start
                allowed_period = 'current month'

            if wizard.payment_date < allowed_start or wizard.payment_date > current_month_end:
                raise ValidationError(_(
                    'Payment Date must be within the %s (%s to %s).\n'
                    'You selected: %s'
                ) % (
                    allowed_period,
                    allowed_start.strftime('%B %d, %Y'),
                    current_month_end.strftime('%B %d, %Y'),
                    wizard.payment_date.strftime('%B %d, %Y'),
                ))

    def _create_payment_vals_from_wizard(self, batch_result):
        vals = super()._create_payment_vals_from_wizard(batch_result)
        if self.payment_channel:
            vals['payment_channel'] = self.payment_channel
        if self.payment_channel == 'pdc':
            vals['check_date'] = self.check_date
            vals['check_reference'] = self.check_reference
            vals['check_comment'] = self.check_comment
            vals['reference_cr_number'] = self.reference_cr_number
        return vals
