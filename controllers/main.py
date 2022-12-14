# ©️ OdooPBX by Odooist, Odoo Proprietary License v1.0, 2020
import logging
import uuid
from odoo import http, SUPERUSER_ID, registry, tools
from odoo.api import Environment
from werkzeug.exceptions import BadRequest

logger = logging.getLogger(__name__)


class AsteriskPlusController(http.Controller):

    def check_ip(self, db=None):
        if db:
            with registry(db).cursor() as cr:
                env = Environment(cr, SUPERUSER_ID, {})
                allowed_ips = env[
                    'asterisk_plus.settings'].sudo().get_param(
                    'permit_ip_addresses')
        else:
            allowed_ips = http.request.env[
                'asterisk_plus.settings'].sudo().get_param(
                'permit_ip_addresses')
        if allowed_ips:
            remote_ip = http.request.httprequest.remote_addr
            if remote_ip not in [
                    k.strip(' ') for k in allowed_ips.split(',')]:
                return BadRequest(
                    'Your IP address {} is not allowed!'.format(remote_ip))

    def _get_partner_by_number(self, db, number, country_code):
        # If db is passed init env for this db
        dst_partner_info = {'id': None}  # Defaults
        if db:
            try:
                with registry(db).cursor() as cr:
                    env = Environment(cr, SUPERUSER_ID, {})
                    dst_partner_info = env[
                        'res.partner'].sudo().get_partner_by_number(
                        number, country_code)
            except Exception:
                logger.exception('Db init error:')
                return BadRequest('Db error, check Odoo logs')
        else:
            dst_partner_info = http.request.env[
                'res.partner'].sudo().get_partner_by_number(
                number, country_code)
        return dst_partner_info

    @http.route('/asterisk_plus/get_caller_name', type='http', auth='none')
    def get_caller_name(self, **kw):
        db = kw.get('db')
        try:
            checked = self.check_ip(db=db)
            if checked is not None:
                return checked
            number = kw.get('number', '').replace(' ', '')  # Strip spaces
            country_code = kw.get('country') or False
            if not number:
                return BadRequest('Number not specified in request')
            dst_partner_info = self._get_partner_by_number(
                db, number, country_code)
            logger.info('get_caller_name number {} country {} id: {}'.format(
                number, country_code, dst_partner_info['id']))
            if dst_partner_info['id']:
                return dst_partner_info['name']
            return ''
        except Exception as e:
            logger.exception('Error:')
            if 'request not bound to a database' in str(e):
                return 'db_not_specified'
            elif 'database' in str(e) and 'does not exist' in str(e):
                return 'db_not_exists'
            else:
                return 'Error'

    @http.route('/asterisk_plus/get_partner_manager', type='http', auth='none')
    def get_partner_manager(self, **kw):
        db = kw.get('db')
        try:
            checked = self.check_ip(db=db)
            if checked is not None:
                return checked
            number = kw.get('number', '').replace(' ', '')  # Strip spaces
            country_code = kw.get('country') or False
            exten = kw.get('exten', False)
            if not number:
                return BadRequest('Number not specified in request')
            dst_partner_info = self._get_partner_by_number(
                db, number, country_code)
            if dst_partner_info['id']:
                # Partner found, get manager.
                with registry(db).cursor() as cr:
                    env = Environment(cr, SUPERUSER_ID, {})
                    partner = env['res.partner'].sudo().browse(
                        dst_partner_info['id'])
                    if partner.user_id and partner.user_id.asterisk_users:
                        # We have user configured so let return his exten or channels
                        if exten:
                            result = partner.user_id.asterisk_users[0].exten
                        else:
                            originate_channels = [
                                k.name for k in partner.user_id.asterisk_users[0].channels
                                if k.originate_enabled]
                            result = '&'.join(originate_channels)
                        logger.info(
                            "Partner %s manager search result:  %s",
                            partner.id, result)
                        return result
            return ''
        except Exception as e:
            logger.exception('Error:')
            if 'request not bound to a database' in str(e):
                return 'db_not_specified'
            elif 'database' in str(e) and 'does not exist' in str(e):
                return 'db_not_exists'
            else:
                return 'Error'

    @http.route('/asterisk_plus/get_caller_tags', auth='none', type='http')
    def get_caller_tags(self, **kw):
        db = kw.get('db')
        try:
            checked = self.check_ip(db=db)
            if checked is not None:
                return checked
            number = kw.get('number', '').replace(' ', '')  # Strip spaces
            country_code = kw.get('country') or False
            if not number:
                return BadRequest('Number not specified in request')
            dst_partner_info = self._get_partner_by_number(
                db, number, country_code)
            if dst_partner_info['id']:
                # Partner found, get manager.
                partner = http.request.env['res.partner'].sudo().browse(
                    dst_partner_info['id'])
                if partner:
                    return ','.join([k.name for k in partner.category_id])
            return ''
        except Exception as e:
            logger.exception('Error:')
            if 'request not bound to a database' in str(e):
                return 'db_not_specified'
            elif 'database' in str(e) and 'does not exist' in str(e):
                return 'db_not_exists'
            else:
                return 'Error'

    @http.route('/asterisk_plus/ping', type='http', auth='none')
    def asterisk_ping(self, **kwargs):
        dbname = kwargs.get('dbname', 'odoopbx_15')
        with registry(dbname).cursor() as cr:
            env = Environment(cr, SUPERUSER_ID, {})
            try:
                res = env['asterisk_plus.server'].browse(1).local_job(
                    fun='test.ping', sync=True)
                return http.Response('{}'.format(res))
            except Exception as e:
                logger.exception('Error:')
                return '{}'.format(e)

    @http.route('/asterisk_plus/asterisk_ping', type='http', auth='none')
    def ping(self, **kwargs):
        dbname = kwargs.get('dbname', 'demo_15.0')
        with registry(dbname).cursor() as cr:
            env = Environment(cr, http.request.env.ref('base.user_admin').id, {})
            try:
                res = env['asterisk_plus.server'].browse(1).ami_action(
                    {'Action': 'Ping'}, sync=True)
                return http.Response('{}'.format(res))
            except Exception as e:
                logger.exception('Error:')
                return '{}'.format(e)

    @http.route('/asterisk_plus/signup', auth='user')
    def signup(self):
        user = http.request.env['res.users'].browse(http.request.uid)
        email = user.partner_id.email
        if not email:
            return http.request.render('asterisk_plus.email_not_set')
        mail = http.request.env['mail.mail'].create({
            'subject': 'Asterisk calls subscribe request',
            'email_from': email,
            'email_to': 'odooist@gmail.com',
            'body_html': '<p>Email: {}</p>'.format(email),
            'body': 'Email: {}'.format(email),
        })
        mail.send()
        return http.request.render('asterisk_plus.email_sent',
                                   qcontext={'email': email})

    @http.route('/asterisk_plus/initialize', auth='public', type='json')
    def initialize(self, **kw):
        data = http.request.jsonrequest
        # Try to get all needed data for successful request
        try:
            ip = http.request.httprequest.remote_addr
            id = data.get('id')
            saltapi_passwd = data.get('saltapi_passwd')
            tz = data.get('tz')
        except Exception as e:
            logger.info('Initialization request process error {}'.format(e))
            return {'error': 'Request process error'}
        if not (ip and id and saltapi_passwd):
            logger.info('Not enough data provided for initialization')
            return {'error': 'Not enough data provided'}
        logger.info('{} initialize from {}'.format(id, ip))
        # Get Environment
        if http.request.session.db and tools.odoo.release.version_info[0] > 12:
            # Single DB mode
            env = http.request.env(su=True)
        else:
            # Non single DB mode
            db = data.get('db')
            if not db:
                logger.warning('initialzie error: db param not specified')
                return {'error': 'db param not received'}
            cr = registry(db).cursor()
            env = Environment(cr, SUPERUSER_ID, {})
        # Set server to default server
        server = env.ref('asterisk_plus.default_server')
        # Check if initialize mode is open
        if not server.initialize_open:
            logger.info('initialize mode not open')
            return {'error': 'Initialize mode not open'}
        # Update Server and General settings
        new_odoo_passwd = uuid.uuid4()
        try:
            server.update({'server_id': id, 'password': new_odoo_passwd})
        except Exception as e:
            logger.warning('Cannot update server: %s', e)
            return {'error': 'Server update failure'}
        if tz:
            try:
                server.tz = tz
            except Exception as e:
                # It's not a critical error just inform.
                logger.warning('Cannot set server timezone to %s: %s', tz, e)
        env['asterisk_plus.settings'].set_param('permit_ip_addresses', ip)
        env['asterisk_plus.settings'].set_param(
            'saltapi_passwd', saltapi_passwd)
        if not env['asterisk_plus.settings'].get_param('saltapi_url'):
            env['asterisk_plus.settings'].set_param(
                'saltapi_url', 'https://{}:48008'.format(ip))
        server.initialize_open = False
        env.cr.commit()
        # Return expected fields as "opts" dict
        res = {'opts': {
            'odoo_user': server.user.login,
            'odoo_password': new_odoo_passwd,
            }}
        return res
