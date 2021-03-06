# -*- coding: iso-8859-1 -*-
# Copyright (C) 2000-2014 Bastian Kleineidam
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
"""
Handle https links.
"""
import time
import threading
from . import _ContentPlugin
from .. import log, LOG_PLUGIN, strformat, LinkCheckerError
from ..decorators import synchronized

_lock = threading.Lock()

# configuration option names
sslcertwarndays = "sslcertwarndays"

class SslCertificateCheck(_ContentPlugin):
    """Check SSL certificate expiration date. Only internal https: links
    will be checked. A domain will only be checked once to avoid duplicate
    warnings.
    The expiration warning time can be configured with the sslcertwarndays
    option."""

    def __init__(self, config):
        """Initialize clamav configuration."""
        super(SslCertificateCheck, self).__init__(config)
        self.warn_ssl_cert_secs_valid = config[sslcertwarndays] * strformat.SECONDS_PER_DAY
        # do not check hosts multiple times
        self.checked_hosts = set()

    @synchronized(_lock)
    def check(self, url_data):
        """Run all SSL certificate checks that have not yet been done.
        OpenSSL already checked the SSL notBefore and notAfter dates.
        """
        if url_data.extern[0]:
            # only check internal pages
            return
        if not url_data.valid:
            return
        if url_data.scheme != 'https':
            return
        host = url_data.urlparts[1]
        if host in self.checked_hosts:
            return
        self.checked_hosts.add(host)
        ssl_sock = url_data.url_connection.raw._connection.sock
        cert = ssl_sock.getpeercert()
        log.debug(LOG_PLUGIN, "Got SSL certificate %s", cert)
        #if not cert:
        #    return
        if 'notAfter' in cert:
            self.check_ssl_valid_date(url_data, ssl_sock, cert)
        else:
            msg = _('certificate did not include "notAfter" information')
            self.add_ssl_warning(url_data, ssl_sock, msg)

    def check_ssl_valid_date(self, url_data, ssl_sock, cert):
        """Check if the certificate is still valid, or if configured check
        if it's at least a number of days valid.
        """
        import ssl
        try:
            notAfter = ssl.cert_time_to_seconds(cert['notAfter'])
        except ValueError as msg:
            msg = _('invalid certficate "notAfter" value %r') % cert['notAfter']
            self.add_ssl_warning(url_data, ssl_sock, msg)
            return
        curTime = time.time()
        # Calculate seconds until certifcate expires. Can be negative if
        # the certificate is already expired.
        secondsValid = notAfter - curTime
        if secondsValid < 0:
            msg = _('certficate is expired on %s') % cert['notAfter']
            self.add_ssl_warning(url_data, ssl_sock, msg)
        elif secondsValid < self.warn_ssl_cert_secs_valid:
            strSecondsValid = strformat.strduration_long(secondsValid)
            msg = _('certificate is only %s valid') % strSecondsValid
            self.add_ssl_warning(url_data, ssl_sock, msg)

    def add_ssl_warning(self, url_data, ssl_sock, msg):
        """Add a warning message about an SSL certificate error."""
        cipher_name, ssl_protocol, secret_bits = ssl_sock.cipher()
        err = _(u"SSL warning: %(msg)s. Cipher %(cipher)s, %(protocol)s.")
        attrs = dict(msg=msg, cipher=cipher_name, protocol=ssl_protocol)
        url_data.add_warning(err % attrs)

    @classmethod
    def read_config(cls, configparser):
        """Read configuration file options."""
        config = dict()
        section = cls.__name__
        option = sslcertwarndays
        if configparser.has_option(section, option):
            num = configparser.getint(section, option)
            if num > 0:
                config[option] = num
            else:
                msg = _("invalid value for %s: %d must not be less than %d") % (option, num, 0)
                raise LinkCheckerError(msg)
        else:
            # set the default
            config[option] = 30
        return config
