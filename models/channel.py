# ©️ OdooPBX by Odooist, Odoo Proprietary License v1.0, 2020
from datetime import datetime, timedelta
import json
import logging
from odoo import models, fields, api, tools, _
from odoo.exceptions import ValidationError
from .server import debug


logger = logging.getLogger(__name__)


class Channel(models.Model):
    _name = 'asterisk_plus.channel'
    _rec_name = 'uniqueid'
    _order = 'id desc'
    _description = 'Channel'

    #: Call of the channel
    call = fields.Many2one('asterisk_plus.call', ondelete='cascade')
    #: Flag not to create a call (special cases when only channels are needed).
    no_call = fields.Boolean()
    #: Server of the channel. When server is removed all channels are deleted.
    server = fields.Many2one('asterisk_plus.server', ondelete='cascade', required=True)
    #: User who owns the channel
    user = fields.Many2one('res.users', ondelete='set null')
    #: Channel name. E.g. SIP/1001-000000bd.
    channel = fields.Char(index=True)
    #: Shorted channel to compare with user's channel as it is defined. E.g. SIP/1001
    channel_short = fields.Char(compute='_get_channel_short',
                                string=_('Chan'))
    #: Channels that were created from this channel.
    linked_channels = fields.One2many('asterisk_plus.channel',
        inverse_name='parent_channel')
    #: Parent channel
    parent_channel = fields.Many2one('asterisk_plus.channel', compute='_get_parent_channel')
    #: Channel unique ID. E.g. asterisk-1631528870.0
    uniqueid = fields.Char(size=64, index=True)
    #: Linked channel unique ID. E.g. asterisk-1631528870.1
    linkedid = fields.Char(size=64, index=True, string='Linked ID')
    #: Channel context.
    context = fields.Char(size=80)
    # Connected line number.
    connected_line_num = fields.Char(size=80)
    #: Connected line name.
    connected_line_name = fields.Char(size=80)
    #: Channel's current state.
    state = fields.Char(size=80, string='State code')
    #: Channel's current state description.
    state_desc = fields.Char(size=256, string=_('State'))
    #: Channel extension.
    exten = fields.Char(size=32)
    #: Caller ID number.
    callerid_num = fields.Char(size=32, string='CallerID number')
    #: Caller ID name.
    callerid_name = fields.Char(size=32, string='CallerID name')
    #: System name.
    system_name = fields.Char(size=128)
    #: Channel's account code.
    accountcode = fields.Char(size=80)
    #: Channel's current priority.
    priority = fields.Char(size=4)
    #: Channel's current application.
    app = fields.Char(size=32, string='Application')
    #: Channel's current application data.
    app_data = fields.Char(size=512, string='Application Data')
    #: Channel's language.
    language = fields.Char(size=2)
    # Hangup event fields
    cause = fields.Char(index=True)
    cause_txt = fields.Char(index=True)
    hangup_date = fields.Datetime(index=True)
    timestamp = fields.Char(size=20)
    event = fields.Char(size=64)
    #: Path to recorded call file
    recording_file_path = fields.Char()
    #: Flag to indicate if the channel is active
    is_active = fields.Boolean(index=True)

    ########################### COMPUTED FIELDS ###############################
    def _get_channel_short(self):
        # Makes SIP/1001-000000bd to be SIP/1001.
        for rec in self:
            if rec.channel:
                rec.channel_short = '-'.join(rec.channel.split('-')[:-1])
            else:
                rec.channel_short = False

    def _get_parent_channel(self):
        for rec in self:
            if rec.uniqueid != rec.linkedid:
                # Asterisk bound channels
                rec.parent_channel = self.search(
                    [('uniqueid', '=', rec.linkedid)], limit=1)
            else:
                rec.parent_channel = False

    def _get_linked_channels(self):
        for rec in self:
            print(rec)
            print(self.search(
                [('linkedid', '=', rec.uniqueid)]))
            rec.linked_channels = self.search(
                [('linkedid', '=', rec.uniqueid), ('id', '!=', rec.id)])

    def set_inactive(self):
        for rec in self:
            rec.is_active = False

    @api.model
    def reload_channels(self, data=None):
        """Reloads channels list view.
        """
        auto_reload = self.env[
            'asterisk_plus.settings'].get_param('auto_reload_channels')
        if not auto_reload:
            return
        if data is None:
            data = {}
        if tools.odoo.release.version_info[0] < 15:
            msg = {
                'action': 'reload_view',
                'model': 'asterisk_plus.channel'
            }
            self.env['bus.bus'].sendone('asterisk_plus_actions', json.dumps(msg))
        else:
            msg = {
                'model': 'asterisk_plus.channel'
            }
            self.env['bus.bus']._sendone(
                'asterisk_plus_actions',
                'reload_view',
                json.dumps(msg))

    def update_call_data(channel, country=None):
        """Updates call data to set: calling/called user,
            call direction, partner (if found) and call reference."""
        call_data = {}
        # Primary channel belonging to a user
        if channel.uniqueid == channel.call.uniqueid and channel.user:
            if not channel.call.calling_user:
                call_data['calling_user'] = channel.user.id
            if not channel.call.direction:
                call_data['direction'] = 'out'
            if not channel.call.partner:
                # Match the partner by called number
                partner = channel.env[
                    'res.partner'].get_partner_by_number(
                        channel.exten, country=country)['id']
                if partner:
                  call_data['partner'] = partner
            if not channel.call.calling_name:
                call_data['calling_name'] = channel.callerid_name
        # Secondary channel belonging to a user
        elif channel.uniqueid != channel.call.uniqueid and channel.user:
            if not channel.call.direction:
                call_data['direction'] = 'in'
            called_users = set(channel.call.called_users.mapped('id'))
            called_users.add(channel.user.id)
            call_data = {
                'called_users': list(called_users)
            }
            # Subscribe called user
            channel.call.message_subscribe(
                partner_ids=[channel.user.partner_id.id])
        # Primary channel not belonging to a user
        elif channel.uniqueid == channel.call.uniqueid and not channel.user:
            # Assign direction IN if direction is not set
            if not channel.call.direction:
                call_data['direction'] = 'in'
            # Try to match the partner by caller ID number
            if not channel.call.partner:
                # Check if there is a reference with partner ID
                if channel.call.ref and getattr(channel.call.ref, 'partner_id', False):
                    call_data['partner'] = channel.call.ref.partner_id.id
                else:
                    call_data['partner'] = channel.env[
                        'res.partner'].get_partner_by_number(
                        channel.callerid_num, country=country)['id']
                # Check if auto create partners is set & create partner.
                if not call_data['partner'] and \
                        channel.env['asterisk_plus.settings'].get_param(
                            'auto_create_partners'):
                    call_data['partner'] = channel.env['res.partner'].sudo().create({
                        'name': channel.callerid_num,
                        'phone': channel.callerid_num,
                    }).id
                    debug(channel, 'Call {} auto create partner id {}'.format(
                        channel.call.id, call_data['partner']
                    ))
            if not channel.call.calling_name and channel.callerid_name:
                call_data['calling_name'] = channel.callerid_name
        # Secondary channel not belonging to a user
        elif channel.uniqueid != channel.call.uniqueid and not channel.user:
            if not channel.call.direction:
                call_data['direction'] = 'out'
        # Update call call_data
        debug(channel,'Call {} update: {}'.format(
            channel.call.id, call_data
        ))
        channel.call.write(call_data)
        try:
            if channel.call and not channel.call.ref:
                channel.call.update_reference(country=country)
        except Exception:
            logger.exception('Update call reference error:')

    ########################### AMI Event handlers ############################
    @api.model
    def on_ami_new_channel(self, event):
        """AMI NewChannel event is processed to create a new channel in Odoo.
        """
        debug(self, json.dumps(event, indent=2))
        data = {
            'event': event['Event'],
            'server': self.env.user.asterisk_server.id,
            'channel': event['Channel'],
            'state': event['ChannelState'],
            'state_desc': event['ChannelStateDesc'],
            'callerid_num': event['CallerIDNum'],
            'callerid_name': event['CallerIDName'],
            'connected_line_num': event['ConnectedLineNum'],
            'connected_line_name': event['ConnectedLineName'],
            'language': event['Language'],
            'accountcode': event['AccountCode'],
            'priority': event['Priority'],
            'context': event['Context'],
            'exten': event['Exten'],
            'uniqueid': event['Uniqueid'],
            'linkedid': event['Linkedid'],
            'system_name': event['SystemName'],
            'is_active': True,
        }
        # Search for an active channel with this Uniqueid
        channel = self.env['asterisk_plus.channel'].search([
            ('is_active', '=', True),
            ('uniqueid', '=', event['Uniqueid'])])
        # Match the channel to a user
        if not channel.user:
            asterisk_user = self.env[
                'asterisk_plus.user_channel'].get_user_channel(
                    event['Channel'], event['SystemName']).asterisk_user
            if not asterisk_user and event['CallerIDNum']:
                asterisk_user = self.env['asterisk_plus.user'].search(
                    [('exten', '=', event['CallerIDNum'])],
                    limit=1)
            user = asterisk_user.user
            if user:
                data['user'] = user.id
        else:
            user = channel.user
            asterisk_user = user.asterisk_users[:1]
        # Define country for number formatting
        country = (user.partner_id.country_id.code or
            self.env.user.partner_id.country_id.code or None
        )
        debug(self, '{} id {} user {} country {}'.format(
            event['Channel'], channel.mapped('id'), user.id, country
        ))
        # Assign a call to the channel
        if not channel and not channel.no_call:
            # Create a new call for the primary channel.
            if event['Uniqueid'] == event['Linkedid']:
                # Check if call already exists
                call = self.env['asterisk_plus.call'].search(
                    [('uniqueid', '=', event['Uniqueid'])], limit=1)
                if not call:
                    call = self.env['asterisk_plus.call'].create({
                        'uniqueid': event['Uniqueid'],
                        'calling_number': event['CallerIDNum'],
                        'called_number': event['Exten'],
                        'started': datetime.now(),
                        'is_active': True,
                        'status': 'progress',
                        'server': self.env.user.asterisk_server.id,
                    })
                    debug(self, '{} spawn a new call: {}'.format(
                        event['Channel'], call.id
                    ))
            # Assign a call to the secondary channel(s)
            else:
                call = self.env['asterisk_plus.call'].search(
                    [('uniqueid', '=', event['Linkedid'])], limit=1)
                debug(self, '{} belongs to call: {}'.format(
                    event['Channel'], call.id
                ))
            data['call'] = call.id
        # Create or update channel object
        if not channel:
            channel = self.create(data)
            debug(self, '{} create id: {}'.format(
                event['Channel'], channel.id
            ))
        else:
            debug(self, '{} update: {}'.format(
                event['Channel'], data
            ))
            channel.write(data)
        # Update call based on channel.
        channel.update_call_data(country=country)
        if asterisk_user and channel.call.direction == 'in':
            channel.call.notify_called_user(asterisk_user)
        self.reload_channels()
        if self.env['asterisk_plus.settings'].sudo().get_param('trace_ami'):
            self.env['asterisk_plus.channel_message'].create_from_event(
                channel, event
            )
        return (channel.id, '{} Newchannel ACK'.format(event['Channel']))

    @api.model
    def on_ami_update_channel_state(self, event):
        """AMI Newstate event. Write call status and ansered time,
            create channel message and call event log records.
            Processed when channel's state changes.
        """
        debug(self, json.dumps(event, indent=2))
        get = event.get
        data = {
            'server': self.env.user.asterisk_server.id,
            'channel': get('Channel'),
            'uniqueid': get('Uniqueid'),
            'linkedid': get('Linkedid'),
            'context': get('Context'),
            'connected_line_num': get('ConnectedLineNum'),
            'connected_line_name': get('ConnectedLineName'),
            'state': get('ChannelState'),
            'state_desc': get('ChannelStateDesc'),
            'exten': get('Exten'),
            'callerid_num': get('CallerIDNum'),
            'callerid_name': get('CallerIDName'),
            'accountcode': get('AccountCode'),
            'priority': get('Priority'),
            'timestamp': get('Timestamp'),
            'system_name': get('SystemName', 'asterisk'),
            'language': get('Language'),
            'event': get('Event'),
            'is_active': True,
        }
        channel = self.env['asterisk_plus.channel'].search([
            ('is_active', '=', True),
            ('uniqueid', '=', get('Uniqueid'))], limit=1)
        if not channel:
            channel = self.create(data)
        else:
            channel.write(data)
        if self.env['asterisk_plus.settings'].sudo().get_param('trace_ami'):
            data['channel_id'] = channel.id
            self.env['asterisk_plus.channel_message'].create_from_event(channel, event)
        if not channel.call:
            logger.warning('{} id {} Newstate does not match any call'.format(
                    event['Channel'], channel.id))
            return (channel.id, '{} Newstate does not match any call'.format(event['Channel']))
        # Append an entry to call's events
        self.env['asterisk_plus.call_event'].create({
            'call': channel.call.id,
            'create_date': datetime.now(),
            'event': 'Channel {} status is {}'.format(
                channel.channel_short, get('ChannelStateDesc')),
        })
        # Update call when secondary channel gets new state Up
        if (channel.call.uniqueid != channel.uniqueid and
                channel.state_desc == 'Up'):
            call_data = {
                    'status': 'answered',
                    'answered': datetime.now()}
            user = self.env[
                'asterisk_plus.user_channel'].get_user_channel(
                    event['Channel'], event['SystemName']).user
            if user:
                call_data['answered_user'] = user.id
            debug(self,'Call {} update: {}'.format(channel.call.id, call_data))
            channel.call.write(call_data)
        return (channel.id, '{} Newstate ACK'.format(event['Channel']))

    @api.model
    def on_ami_hangup(self, event):
        """AMI Hangup event.
        Returns tuple (channel.id, message)
        """
        debug(self, json.dumps(event, indent=2))            
        # TODO: Limit search domain by create_date less then one day.
        channel = self.env['asterisk_plus.channel'].search([
            ('is_active', '=', True),
            ('uniqueid', '=', event['Uniqueid'])])
        if not channel:
            debug(self, 'Channel {} not found for hangup.'.format(event['Channel']))
            logger.warning('Channel {} not found for hangup.'.format(event['Channel']))
            return (None, '{} Hangup: not found'.format(event['Channel']))
        debug(self, 'Found {} channel(s) {}'.format(len(channel), event['Channel']))
        data = {
            'event': event['Event'],
            'channel': event['Channel'],
            'state': event['ChannelState'],
            'state_desc': event['ChannelStateDesc'],
            'callerid_num': event['CallerIDNum'],
            'callerid_name': event['CallerIDName'],
            'connected_line_num': event['ConnectedLineNum'],
            'connected_line_name': event['ConnectedLineName'],
            'language': event['Language'],
            'accountcode': event['AccountCode'],
            'context': event['Context'],
            'exten': event['Exten'],
            'priority': event['Priority'],
            'uniqueid': event['Uniqueid'],
            'linkedid': event['Linkedid'],
            'hangup_date': fields.Datetime.now(),
            'cause': event['Cause'],
            'cause_txt': event['Cause-txt'],
            'is_active': False,
        }
        channel.write(data)
        # Set call status by the primary channel
        if event['Uniqueid'] == event['Linkedid']:
            call_data = {
                'is_active': False,
                'ended': datetime.now(),
            }
            if channel.call.status != 'answered':
                if channel.cause == '17':
                    call_data['status'] = 'busy'
                elif channel.cause == '19':
                    call_data['status'] = 'noanswer'
                else:
                    call_data['status'] = 'failed'
            debug(self, 'Call {} update: {}'.format(
                channel.call.id, call_data))
            channel.call.write(call_data)
        # Create hangup event
        if channel.call:
            self.env['asterisk_plus.call_event'].create({
                'call': channel.call.id,
                'create_date': datetime.now(),
                'event': 'Channel {} hangup'.format(channel.channel_short),
            })
        self.reload_channels()
        if self.env['asterisk_plus.settings'].sudo().get_param('trace_ami'):
            # Remove and add fields according to the message
            data['channel_id'] = channel.id
            self.env['asterisk_plus.channel_message'].create_from_event(channel, event)
        # Check if call recording is enabled and save record
        if self.env['asterisk_plus.settings'].sudo().get_param('record_calls'):
            self.env['asterisk_plus.recording'].save_call_recording(channel)
        return (channel.id, '{} Hangup ACK'.format(event['Channel']))

    @api.model
    def on_ami_originate_response_failure(self, event):
        """AMI OriginateResponse event.
        """
        # This comes from Asterisk OriginateResponse AMI message when
        # call originate has been failed.
        if event['Response'] != 'Failure':
            logger.error(self, 'Response', 'UNEXPECTED ORIGINATE RESPONSE FROM ASTERISK!')
            return False
        channel = self.env['asterisk_plus.channel'].search(
            [('is_active', '=', True),
            ('uniqueid', '=', event['Uniqueid'])])
        if not channel:
            debug(self, 'CHANNEL NOT FOUND FOR ORIGINATE RESPONSE!')
            return False
        if self.env['asterisk_plus.settings'].sudo().get_param('trace_ami'):
            event['channel_id'] = channel.id
            self.env['asterisk_plus.channel_message'].create_from_event(channel, event)
        if channel.cause:
            # This is a response after Hangup so no need for it.
            return channel.id
        channel.write({
            'is_active': False,
            'cause': event['Reason'],  # 0
            'cause_txt': event['Response'],  # Failure
        })
        channel.call.write({'status': 'failed', 'is_active': False})
        reason = event.get('Reason')
        # Notify user on a failed click to dial.
        if channel.call and channel.call.model and channel.call.res_id:
            self.env.user.asterisk_plus_notify(
                _('Call failed, reason {0}').format(reason),
                uid=channel.create_uid.id, warning=True)
        return channel.id

    @api.model
    def update_recording_filename(self, event):
        """AMI VarSet event.
        """
        debug(self, json.dumps(event, indent=2))
        if event.get('Variable') == 'MIXMONITOR_FILENAME':
            file_path = event['Value']
            uniqueid = event['Uniqueid']
            channel = self.search([('uniqueid', '=', uniqueid)], limit=1)
            channel.recording_file_path = file_path
            return True
        return False

    @api.model
    def vacuum(self, hours):
        """Cron job to delete channel records.
        """
        expire_date = datetime.utcnow() - timedelta(hours=hours)
        channels = self.env['asterisk_plus.channel'].search([
            ('create_date', '<=', expire_date.strftime('%Y-%m-%d %H:%M:%S'))
        ])
        channels.unlink()
