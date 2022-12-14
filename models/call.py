# ©️ OdooPBX by Odooist, Odoo Proprietary License v1.0, 2021
from datetime import datetime, timedelta
import json
import logging
import pytz
import phonenumbers
from odoo import models, fields, api, tools, _
from odoo.exceptions import ValidationError
from .server import debug

logger = logging.getLogger(__name__)


class Call(models.Model):
    _name = 'asterisk_plus.call'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'Call Detail Record'
    _order = 'id desc'
    _log_access = False
    _rec_name = 'id'

    uniqueid = fields.Char(size=64, index=True)
    server = fields.Many2one('asterisk_plus.server', ondelete='cascade')
    events = fields.One2many('asterisk_plus.call_event', inverse_name='call')
    calling_number = fields.Char(index=True, readonly=True)
    calling_name = fields.Char()
    called_number = fields.Char(index=True, readonly=True)
    started = fields.Datetime(index=True, readonly=True)
    answered = fields.Datetime(index=True, readonly=True)
    ended = fields.Datetime(index=True, readonly=True)
    direction = fields.Selection(selection=[('in', 'Incoming'), ('out', 'Outgoing')],
        index=True, readonly=True)
    direction_icon = fields.Html(string='Dir', compute='_get_direction_icon')
    status = fields.Selection(selection=[
         ('noanswer', 'No Answer'), ('answered', 'Answered'),
         ('busy', 'Busy'), ('failed', 'Failed'),
         ('progress', 'In Progress')], index=True, default='progress')
    # Boolean index for split all calls on this flag. Calls are by default in active state.
    is_active = fields.Boolean(index=True, default=True)
    channels = fields.One2many('asterisk_plus.channel', inverse_name='call', readonly=True)
    recordings = fields.One2many('asterisk_plus.recording', inverse_name='call', readonly=True)
    recording_icon = fields.Char(compute='_get_recording_icon', string='R')
    partner = fields.Many2one('res.partner', ondelete='set null')
    partner_img = fields.Binary(related='partner.image'
      if tools.odoo.release.version_info[0] < 13 else 'partner.image_1920')
    calling_user = fields.Many2one('res.users', ondelete='set null', readonly=False)
    calling_user_img = fields.Binary(related='calling_user.image'
      if tools.odoo.release.version_info[0] < 13 else 'calling_user.image_1920')
    answered_user = fields.Many2one('res.users', ondelete='set null', readonly=False)
    answered_user_img = fields.Binary(related='answered_user.image'
          if tools.odoo.release.version_info[0] < 13 else 'answered_user.image_1920')
    called_users = fields.Many2many('res.users')
    calling_avatar = fields.Text(compute='_get_calling_avatar', readonly=True)
    # Related object
    model = fields.Char()
    res_id = fields.Integer()
    ref = fields.Reference(
        string='Reference',
        selection=[
            ('res.partner', _('Partners')),
            ('asterisk_plus.call', _('Calls')),
            ('asterisk_plus.user', _('Users'))],
        compute='_get_ref',
        inverse='_set_ref')
    notes = fields.Html()
    duration = fields.Integer(readonly=True, compute='_get_duration', store=True)
    duration_human = fields.Char(
        string=_('Call Duration'),
        compute='_get_duration_human')

    @api.model
    def create(self, vals):
        # Reload after call is created
        call = super(Call, self.with_context(
            mail_create_nosubscribe=True, mail_create_nolog=True)).create(vals)
        self.reload_calls()
        return call

    def _get_recording_icon(self):
        for rec in self:
            if rec.recordings:
                rec.recording_icon = '<span class="fa fa-file-sound-o"/>'
            else:
                rec.recording_icon = ''

    def update_reference(self, **kwargs):
        """Inherit in other modules to update call reference.
        """
        self.ensure_one()

    @api.constrains('is_active')
    def reload_on_hangup(self):
        """Reloads active calls list view after hangup.
        """
        for rec in self:
            if not rec.is_active:
                self.reload_calls()

    def notify_called_user(self, asterisk_user):
        """Notify user about incomming call.
        """
        # Open partner or reference form
        self._open_reference_form(asterisk_user)
        # Convert call started time using user timezone
        tz = pytz.timezone(asterisk_user.user.tz or 'UTC')
        call_started = self.started.replace(
            tzinfo=pytz.timezone('UTC')).astimezone(tz)

        ref_block = ''
        if self.ref and hasattr(self.ref, 'name'):
            ref_block = """
                <p class="text-center"><strong>Reference:</strong>
                <a href='/web#id={}&model={}&view_type=form'>
                    {}
                </a>
                </p>
            """.format(
                    self.res_id,
                    self.model,
                    self.ref.name)
        message = """
        <div class="d-flex align-items-center justify-content-center">
            <div>
                <img style="max-height: 100px; max-width: 100px;"
                        class="rounded-circle"
                        src={}/>
            </div>
            <div>
                <p class="text-center">Incoming call from <strong>{}</strong> at {}</p>
                {}
            </div>
        </div>
        """.format(
                self.calling_avatar,
                self.calling_name,
                call_started.strftime("%H:%M:%S"),
                ref_block)
        # Check user notify settings.
        if asterisk_user.call_popup_is_enabled:
            self.env['res.users'].asterisk_plus_notify(
                message,
                uid=asterisk_user.user.id,
                sticky=asterisk_user.call_popup_is_sticky)

    def _open_reference_form(self, asterisk_user):
        """Open partner or reference form."""
        if not asterisk_user.open_reference:
            return
        # We have model and res_id when reference is found
        model = self.model or 'res.partner'
        res_id = self.res_id or self.partner.id

        if not res_id:
            return

        if tools.odoo.release.version_info[0] < 15:
            msg = {
                'action': 'open_record',
                'model': model,
                'res_id': res_id
            }
            self.env['bus.bus'].sendone(
                'asterisk_plus_actions_{}'.format(asterisk_user.user.id),
                json.dumps(msg))
        else:
            self.env['bus.bus']._sendone(
                'asterisk_plus_actions_{}'.format(asterisk_user.user.id),
                'open_record',
                {'model': model, 'res_id': res_id}
            )

    @api.depends('model', 'res_id') 
    def _get_ref(self):
        # We need a reference field to be computed because we want to
        # search and group by model.
        for rec in self:
            if rec.model and rec.model in self.env:
                try:
                    rec.ref = '%s,%s' % (rec.model, rec.res_id or 0)
                except ValueError as e:
                    logger.warning(e)
            else:
                rec.ref = None

    def _set_ref(self):
        for rec in self:
            if rec.ref:
                rec.write({'model': rec.ref._name, 'res_id': rec.ref.id})
            else:
                rec.write({'model': False, 'res_id': False})

    def _get_calling_avatar(self):
        """Get avatar for calling user.
        """
        for rec in self:
            if rec.partner:
                rec.calling_avatar = '/web/image/{}/{}/image_1024'.format(rec.partner._name, rec.partner.id)
            elif rec.calling_user:
                rec.calling_avatar = '/web/image/{}/{}/image_1024'.format(rec.calling_user._name, rec.calling_user.id)
            else:
                rec.calling_avatar = '/web/image'

    def _get_direction_icon(self):
        for rec in self:
            rec.direction_icon = '<span class="fa fa-arrow-left"/>' if rec.direction == 'in' else \
                '<span class="fa fa-arrow-right"/>'

    def reload_calls(self, data=None):
        """Reloads active calls list view.
        Returns: None.
        """
        auto_reload = self.env[
            'asterisk_plus.settings'].get_param('auto_reload_calls')
        if not auto_reload:
            return
        if data is None:
            data = {}
        if tools.odoo.release.version_info[0] < 15:
            msg = {
                'action': 'reload_view',
                'model': 'asterisk_plus.call'
            }
            self.env['bus.bus'].sendone('asterisk_plus_actions', json.dumps(msg))
        else:
            msg = {'model': 'asterisk_plus.call'}
            self.env['bus.bus']._sendone(
                'asterisk_plus_actions',
                'reload_view',
                json.dumps(msg)
            )

    def move_to_history(self):
        self.is_active = False

    def set_notes(self):
        return {
            'name': _("Set Note"),
            'type': 'ir.actions.act_window',
            'view_mode': 'form',
            'res_model': 'asterisk_plus.set_notes_wizard',
            'target': 'new',
            'context': {'default_notes': self.notes}
        }

    @api.model
    def delete_calls(self):
        """Cron job to delete calls history.
        """
        days = self.env[
            'asterisk_plus.settings'].get_param('calls_keep_days')
        expire_date = datetime.utcnow() - timedelta(days=int(days))
        expired_calls = self.env['asterisk_plus.call'].search([
            ('ended', '<=', expire_date.strftime('%Y-%m-%d %H:%M:%S'))
        ])
        logger.info('Expired {} calls'.format(len(expired_calls)))
        expired_calls.unlink()

    @api.depends('answered', 'ended')
    def _get_duration(self):
        for rec in self:
            if rec.answered and rec.ended:
                rec.duration = (rec.ended - rec.answered).total_seconds()

    def _get_duration_human(self):
        for rec in self:
            rec.duration_human = str(timedelta(seconds=rec.duration))

    @api.constrains('is_active')
    def register_call(self):
        self.ensure_one()
        # Missed calls to users
        rec = self
        if rec.is_active:
            return
        # Missed call notification
        if rec.status != 'answered' and rec.called_users:
            call_from = (rec.ref or rec.partner or rec.calling_user)
            rec.sudo().message_post(
                subject=_('Missed call notification'),
                body=_('From {} {}').format(
                    getattr(call_from, 'display_name', ''),
                    rec.calling_number),
                partner_ids=rec.called_users.mapped('partner_id').mapped('id'))
        # Register call at partner object
        if rec.partner and rec.model != 'res.partner':
            direction = 'outgoing' if rec.direction == 'out' else 'incoming'
            if rec.called_users:
                message = _('{} {} call to {}. Duration: {}').format(
                    rec.status.capitalize(),
                    direction,
                    rec.called_users.mapped('name'),
                    rec.duration_human)
            elif rec.calling_user:
                message = _('{} {} call from {}.  Duration: {}').format(
                    rec.status.capitalize(),
                    direction,
                    rec.calling_user.name,
                    rec.duration_human)
            else:
                message = _('{} {} call from {} to {}. Duration: {}').format(
                    rec.status.capitalize(),
                    direction,
                    rec.calling_number,
                    rec.called_number,
                    rec.duration_human)

            if tools.odoo.release.version_info[0] < 15:
                subtype_id = self.env[
                    'ir.model.data'].xmlid_to_res_id(
                    'mail.mt_note')
            else:
                subtype_id = self.env[
                    'ir.model.data']._xmlid_to_res_id(
                    'mail.mt_note')

            self.env['mail.message'].sudo().create({
                'subject': '',
                'body': message,
                'model': 'res.partner',
                'res_id': rec.partner.id,
                'message_type': 'comment',
                'subtype_id': subtype_id,
            })

    @api.constrains('is_active')
    def register_reference_call(self):
        self.ensure_one()
        rec = self
        if rec.is_active:
            return
        if rec.ref:
            try:
                direction = 'outgoing' if rec.direction == 'out' else 'incoming'
                if rec.called_users:
                    message = _('{} {} call to {}. Duration: {}').format(
                        rec.status.capitalize(),
                        direction,
                        rec.called_users.mapped('name'),
                        rec.duration_human)
                elif rec.calling_user:
                    message = _('{} {} call from {}.  Duration: {}').format(
                        rec.status.capitalize(),
                        direction,
                        rec.calling_user.name,
                        rec.duration_human)
                else:
                    message = _('{} {} call from {} to {}. Duration: {}').format(
                        rec.status.capitalize(),
                        direction,
                        rec.calling_number,
                        rec.called_number,
                        rec.duration_human)
                rec.ref.sudo().message_post(
                    subject=_('Call notification'),
                    body=message)
            except Exception:
                logger.exception('Register reference call error')

    def partner_button(self):
        self.ensure_one()
        context = {}
        if not self.partner:
            # Create a new parter
            self.partner = self.env['res.partner'].with_context(
                call_id=self.id).create({'name': self.calling_name or self.calling_number})
            context['form_view_initial_mode'] = 'edit'
        # Open call partner form.
        if self.partner:
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'res.partner',
                'res_id': self.partner.id,
                'name': 'Call Partner',
                'view_mode': 'form',
                'view_type': 'form',
                'target': 'current',
                'context': context,
            }
        else:
            raise ValidationError(_('Partner is already defined!'))

    def _spy(self, option):
        self.ensure_one()
        asterisk_user = self.env.user.asterisk_users.filtered(
            lambda x: x.server == self.server)
        if not asterisk_user:
            raise ValidationError(
                _('PBX user is not configured!'))

        if not asterisk_user.channels:
            raise ValidationError(_('User has not channels to originate!'))

        # Get parrent channel for a call
        channel = self.channels.filtered(lambda x: not x.parent_channel)

        if not channel:
            raise ValidationError(_('Parrent channel for a call not found!'))

        if option == 'q':
            callerid = 'Spy'
        elif option == 'qw':
            callerid = 'Whisper'
        elif option == 'qB':
            callerid = 'Barge'
        else:
            callerid = 'Unknown'

        for user_channel in asterisk_user.channels:
            if not user_channel.originate_enabled:
                logger.info('User %s channel %s not enabled to originate.',
                            self.env.user.id, user_channel.name)
                continue

            action = {
                'Action': 'Originate',
                'Async': 'true',
                'Callerid': '{} <1234567890>'.format(callerid, channel.exten),
                'Channel': user_channel.name,
                'Application': 'ChanSpy',
                'Data': '{},{}'.format(channel.channel, option),
                'Variable': asterisk_user._get_originate_vars()
            }

            user_channel.server.ami_action(action, res_notify_uid=self.env.uid)

    def listen(self):
        self._spy('q')

    def whisper(self):
        self._spy('qw')

    def barge(self):
        self._spy('qB')
