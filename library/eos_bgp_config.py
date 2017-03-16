#!/usr/bin/python
#
# Copyright (c) 2015, Arista Networks, Inc.
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are
# met:
#
#   Redistributions of source code must retain the above copyright notice,
#   this list of conditions and the following disclaimer.
#
#   Redistributions in binary form must reproduce the above copyright
#   notice, this list of conditions and the following disclaimer in the
#   documentation and/or other materials provided with the distribution.
#
#   Neither the name of Arista Networks nor the names of its
#   contributors may be used to endorse or promote products derived from
#   this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
# A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL ARISTA NETWORKS
# BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR
# BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY,
# WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE
# OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN
# IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
#
DOCUMENTATION = """
---
module: eos_bgp_config
short_description: Manage BGP routing configuraiton in EOS
description:
  - The eos_bgp_config module provides resource management of the
    global BGP routing process for Arista EOS nodes
version_added: 1.1.0
category: BGP
author: Arista EOS+
requirements:
  - Arista EOS 4.13.7M or later with command API enable
  - Python Client for eAPI 0.4.0 or later
notes:
  - All configuraiton is idempontent unless otherwise specified
  - Supports eos metaparameters for using the eAPI transport
  - Supports tateful resource configuration
options:
  bgp_as:
    description:
      - The BGP autonomous system number to be configured for the
        local BGP routing instance.  The value must be in the valid
        BGP AS range of 1 to 65535.
    required: true
    default: null
    choices: []
    aliases: []
    version_added: 1.1.0
  enable:
    description:
      - Configures the administrative state for the global BGP routing
        process. If enable is True then the BGP routing process is
        administartively enabled and if enable is False then
        the BGP routing process is administratively disabled.
    default: true
    required: false
    choices: ['True', 'False']
    aliases: []
    version_added: 1.1.0
  router_id:
    description:
      - Configures the BGP routing process router-id value.  The router
        id must be in the form of A.B.C.D
    default: false
    required: false
    choices: []
    aliases: []
    version_added: 1.1.0
  maximum_paths:
    description:
      - Configures the maximum number of parallel routes. The EOS default for
        this attribute is 1. This value should be less than or equal to
        maximum_ecmp_paths.
    default: null
    required: false
    choices: []
    aliases: []
    version_added: 1.2.0
  maximum_ecmp_paths:
    description:
      - Configures the maximum number of ecmp paths for each route.
        The EOS default for this attribute is the maximum value, which varies
        by hardware platform. Check your Arista documentation for more
        information. This value should be greater than or equal to
        maximum_paths.
    default: null
    required: false
    choices: []
    aliases: []
    version_added: 1.2.0
"""

EXAMPLES = """

- name: enable BGP routing with AS 65535
  eos_bgp_config: bgp_as=65535 state=present enable=yes

- name: disable the BGP routing process
  eos_bgp_config: bgp_as=65535 enable=no

- name: configure the BGP router-id
  eos_bgp_config: bgp_as=65535 router_id=1.1.1.1

- name: configure the BGP with just max paths
  eos_bgp_config: bgp_as=65535 router_id=1.1.1.1 maximum_paths=20

- name: configure the BGP with maximum_paths and maximum_ecmp_paths
  eos_bgp_config: bgp_as=65535 router_id=1.1.1.1 maximum_paths=20
  maximum_ecmp_paths=20
"""
#<<EOS_COMMON_MODULE_START>>

import syslog
import collections

from ansible.module_utils.basic import *

try:
    import pyeapi
    PYEAPI_AVAILABLE = True
except ImportError:
    PYEAPI_AVAILABLE = False

DEFAULT_SYSLOG_PRIORITY = syslog.LOG_NOTICE
DEFAULT_CONNECTION = 'localhost'
TRANSPORTS = ['socket', 'http', 'https', 'http_local']

class EosConnection(object):

    __attributes__ = ['username', 'password', 'host', 'transport', 'port']

    def __init__(self, **kwargs):
        self.connection = kwargs['connection']
        self.transport = kwargs.get('transport')

        self.username = kwargs.get('username')
        self.password = kwargs.get('password')

        self.host = kwargs.get('host')
        self.port = kwargs.get('port')

        self.config = kwargs.get('config')

    def connect(self):
        if self.config is not None:
            pyeapi.load_config(self.config)

        config = dict()

        if self.connection is not None:
            config = pyeapi.config_for(self.connection)
            if not config:
                msg = 'Connection name "{}" not found'.format(self.connection)

        for key in self.__attributes__:
            if getattr(self, key) is not None:
                config[key] = getattr(self, key)

        if 'transport' not in config:
            raise ValueError('Connection must define a transport')

        connection = pyeapi.client.make_connection(**config)
        node = pyeapi.client.Node(connection, **config)

        try:
            node.enable('show version')
        except (pyeapi.eapilib.ConnectionError, pyeapi.eapilib.CommandError):
            raise ValueError('unable to connect to {}'.format(node))
        return node


class EosAnsibleModule(AnsibleModule):

    meta_args = {
        'config': dict(),
        'username': dict(),
        'password': dict(),
        'host': dict(),
        'connection': dict(default=DEFAULT_CONNECTION),
        'transport': dict(choices=TRANSPORTS),
        'port': dict(),
        'debug': dict(type='bool', default='false'),
        'logging': dict(type='bool', default='true')
    }

    stateful_args = {
        'state': dict(default='present', choices=['present', 'absent']),
    }

    def __init__(self, stateful=True, autorefresh=False, *args, **kwargs):

        kwargs['argument_spec'].update(self.meta_args)

        self._stateful = stateful
        if stateful:
            kwargs['argument_spec'].update(self.stateful_args)

        ## Ok, so in Ansible 2.0,
        ## AnsibleModule.__init__() sets self.params and then
        ##   calls self.log()
        ##   (through self._log_invocation())
        ##
        ## However, self.log() (overridden in EosAnsibleModule)
        ##   references self._logging
        ## and self._logging (defined in EosAnsibleModule)
        ##   references self.params.
        ##
        ## So ... I'm defining self._logging without "or self.params['logging']"
        ##   *before* AnsibleModule.__init__() to avoid a "ref before def".
        ##
        ## I verified that this works with Ansible 1.9.4 and 2.0.0.2.
        ## The only caveat is that the first log message in
        ##   AnsibleModule.__init__() won't be subject to the value of
        ##   self.params['logging'].
        self._logging = kwargs.get('logging')
        super(EosAnsibleModule, self).__init__(*args, **kwargs)

        self.result = dict(changed=False, changes=dict())

        self._debug = kwargs.get('debug') or self.boolean(self.params['debug'])
        self._logging = kwargs.get('logging') or self.params['logging']

        self.log('DEBUG flag is %s' % self._debug)

        self.debug('pyeapi_version', self.check_pyeapi())
        self.debug('stateful', self._stateful)
        self.debug('params', self.params)

        self._attributes = self.map_argument_spec()
        self.validate()
        self._autorefresh = autorefresh
        self._node = EosConnection(**self.params)
        self._node.connect()

        self._node = self.connect()
        self._instance = None

        self.desired_state = self.params['state'] if self._stateful else None
        self.exit_after_flush = kwargs.get('exit_after_flush')

    @property
    def instance(self):
        if self._instance:
            return self._instance

        func = self.func('instance')
        if not func:
            self.fail('Module does not support "instance"')

        try:
            self._instance = func(self)
        except Exception as exc:
            self.fail('instance[error]: %s' % exc.message)

        self.log("called instance: %s" % self._instance)
        return self._instance

    @property
    def attributes(self):
        return self._attributes

    @property
    def node(self):
        return self._node

    def check_pyeapi(self):
        if not PYEAPI_AVAILABLE:
            self.fail('Unable to import pyeapi, is it installed?')
        return pyeapi.__version__

    def map_argument_spec(self):
        """map_argument_spec maps only the module argument spec to attrs

        This method will map the argumentspec minus the meta_args to attrs
        and return the attrs.  This returns a dict object that includes only
        the original argspec plus the stateful_args (if self._stateful=True)

        Returns:
            dict: Returns a dict object that includes the original
                argument_spec plus stateful_args with values minus meta_args

        """
        keys = set(self.params).difference(self.meta_args)
        attrs = dict()
        attrs = dict([(k, self.params[k]) for k in self.params if k in keys])
        if 'CHECKMODE' in attrs:
            del attrs['CHECKMODE']
        return attrs

    def validate(self):
        for key, value in self.attributes.iteritems():
            func = self.func('validate_%s' % key)
            if func:
                self.attributes[key] = func(value)

    def create(self):
        if not self.check_mode:
            func = self.func('create')
            if not func:
                self.fail('Module must define "create" function')
            return self.invoke(func, self)

    def remove(self):
        if not self.check_mode:
            func = self.func('remove')
            if not func:
                self.fail('Module most define "remove" function')
            return self.invoke(func, self)

    def flush(self, exit_after_flush=False):
        self.exit_after_flush = exit_after_flush

        if self.desired_state == 'present' or not self._stateful:
            if self.instance.get('state') == 'absent':
                changed = self.create()
                self.result['changed'] = changed or True
                self.refresh()
                # After a create command, flush the running-config
                # so we get the latest for any other attributes
                self._node._running_config = None

            changeset = self.attributes.viewitems() - self.instance.viewitems()

            if self._debug:
                self.debug('desired_state', self.attributes)
                self.debug('current_state', self.instance)

            changes = self.update(changeset)
            if changes:
                self.result['changes'] = changes
                self.result['changed'] = True

            self._attributes.update(changes)

            flush = self.func('flush')
            if flush:
                self.invoke(flush, self)

        elif self.desired_state == 'absent' and self._stateful:
            if self.instance.get('state') == 'present':
                changed = self.remove()
                self.result['changed'] = changed or True

        elif self._stateful:
            if self.desired_state != self.instance.get('state'):
                func = self.func(self.desired_state)
                changed = self.invoke(func, self)
                self.result['changed'] = changed or True

        self.refresh()
        # By calling self.instance here we trigger another show running-config
        # all which causes delay.  Only if debug is enabled do we call this
        # since it will display the latest state of the object.
        if self._debug:
            self.result['instance'] = self.instance

        if self.exit_after_flush:
            self.exit()

    def update(self, changeset):
        changes = dict()
        for key, value in changeset:
            if value is not None:
                changes[key] = value
                func = self.func('set_%s' % key)
                if func and not self.check_mode:
                    try:
                        self.invoke(func, self)
                    except Exception as exc:
                        self.fail(exc.message)
        return changes

    def connect(self):
        if self.params['config']:
            pyeapi.load_config(self.params['config'])

        config = dict()

        if self.params['connection']:
            config = pyeapi.config_for(self.params['connection'])
            if not config:
                msg = 'Connection name "%s" not found' % self.params['connection']
                self.fail(msg)

        if self.params['username']:
            config['username'] = self.params['username']

        if self.params['password']:
            config['password'] = self.params['password']

        if self.params['transport']:
            config['transport'] = self.params['transport']

        if self.params['port']:
            config['port'] = self.params['port']

        if self.params['host']:
            config['host'] = self.params['host']

        if 'transport' not in config:
            self.fail('Connection must define a transport')

        connection = pyeapi.client.make_connection(**config)
        self.log('Creating connection with autorefresh=%s' % self._autorefresh)
        node = pyeapi.client.Node(connection, autorefresh=self._autorefresh,
                                  **config)

        try:
            resp = node.enable('show version')
            self.debug('eos_version', resp[0]['result']['version'])
            self.debug('eos_model', resp[0]['result']['modelName'])
        except (pyeapi.eapilib.ConnectionError, pyeapi.eapilib.CommandError):
            self.fail('unable to connect to %s' % node)
        else:
            self.log('Connected to node %s' % node)
            self.debug('node', str(node))

        return node

    def config(self, commands):
        self.result['changed'] = True
        if not self.check_mode:
            self.node.config(commands)

    def api(self, module):
        return self.node.api(module)

    def func(self, name):
        return globals().get(name)

    def invoke(self, func, *args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as exc:
            self.fail(exc.message)

    def invoke_function(self, name, *args, **kwargs):
        func = self.func(name)
        if func:
            return self.invoke(func, *args, **kwargs)

    def fail(self, msg):
        self.invoke_function('on_fail', self)
        self.log('ERROR: %s' % msg, syslog.LOG_ERR)
        self.fail_json(msg=msg)

    def exit(self):
        self.invoke_function('on_exit', self)
        self.log('Module completed successfully')
        self.exit_json(**self.result)

    def refresh(self):
        self._instance = None

    def debug(self, key, value):
        if self._debug:
            if 'debug' not in self.result:
                self.result['debug'] = dict()
            self.result['debug'][key] = value

    def log(self, message, log_args=None, priority=None):
        if self._logging:
            syslog.openlog('ansible-eos')
            priority = priority or DEFAULT_SYSLOG_PRIORITY
            syslog.syslog(priority, str(message))

    @classmethod
    def add_state(cls, name):
        cls.stateful_args['state']['choices'].append(name)

#<<EOS_COMMON_MODULE_END>>

def instance(module):
    """Returns the BGP routing instance configuration
    """
    bgp_as = module.attributes['bgp_as']
    result = module.node.api('bgp').get()
    _instance = dict(bgp_as=bgp_as, state='absent')
    if result and bgp_as == str(result['bgp_as']):
        _instance['state'] = 'present'
        _instance['router_id'] = result['router_id']
        _instance['maximum_paths'] = str(result['maximum_paths'])
        _instance['maximum_ecmp_paths'] = str(result['maximum_ecmp_paths'])
        _instance['enable'] = not result['shutdown']
    return _instance

def create(module):
    """Creates a new isntance of BGP routing on the node
    """
    bgp_as = module.attributes['bgp_as']
    module.log('Invoked create for eos_bgp_config[{}]'.format(bgp_as))
    module.node.api('bgp').create(bgp_as)

def remove(module):
    """Removes the BGP routing instance from the node
    """
    bgp_as = module.attributes['bgp_as']
    module.log('Invoked remove for eos_bgp_config[{}]'.format(bgp_as))
    module.node.api('bgp').delete()

def set_enable(module):
    """Globally enables or disables the BGP process
    """
    # If enable is True, we disable shutdown (no shutdown)
    # If enable is False, we do not disable shutdown
    value = module.attributes['enable']
    bgp_as = module.attributes['bgp_as']
    module.log('Invoked set_enable for eos_bgp_config[{}] '
               'with value {}'.format(bgp_as, value))
    module.node.api('bgp').set_shutdown(disable=value)

def set_router_id(module):
    """Configures the BGP router-id
    """
    value = module.attributes['router_id']
    bgp_as = module.attributes['bgp_as']
    module.log('Invoked set_router_id for eos_bgp_config[{}] '
               'with value {}'.format(bgp_as, value))
    module.node.api('bgp').set_router_id(value)
    module.log('Ran command')

def set_maximum_paths(module):
    """Configures the BGP maximum-paths
    """
    module.log('Inside set_maximum_paths')
    bgp_as = module.attributes['bgp_as']
    try:
        max_paths = int(module.attributes['maximum_paths'])
    except:
        max_paths = None

    try:
        max_ecmp_paths = int(module.attributes['maximum_ecmp_paths'])
    except:
        max_ecmp_paths = None

    if max_ecmp_paths and max_paths > max_ecmp_paths:
        module.fail('maximum_paths {} must be less than or equal to '
                    'maximum_ecmp_paths {}'.format(max_paths, max_ecmp_paths))

    module.log('Invoked set_maximum_paths for eos_bgp_config[{}] '
               'with value {}'.format(bgp_as, max_paths))
    module.node.api('bgp').set_maximum_paths(max_paths)

def set_maximum_ecmp_paths(module):
    """Configures the BGP maximum-paths
    """
    module.log('Inside set_maximum_ecmp_paths')
    bgp_as = module.attributes['bgp_as']
    try:
        max_paths = int(module.attributes['maximum_paths'])
    except:
        max_paths = None

    try:
        max_ecmp_paths = int(module.attributes['maximum_ecmp_paths'])
    except:
        max_ecmp_paths = None

    if max_paths > max_ecmp_paths:
        module.fail('maximum_paths {} must be less than or equal to '
                    'maximum_ecmp_paths {}'.format(max_paths, max_ecmp_paths))

    module.log('Invoked set_maximum_paths for eos_bgp_config[{}] '
               'with values {}/{}'.format(bgp_as, max_paths, max_ecmp_paths))
    module.node.api('bgp').set_maximum_paths(max_paths, max_ecmp_paths)

def main():
    """The main module routine called when the module is run by Ansible
    """

    argument_spec = dict(
        bgp_as=dict(required=True),
        enable=dict(type='bool', default=True),
        router_id=dict(),
        maximum_paths=dict(),
        maximum_ecmp_paths=dict()
    )

    module = EosAnsibleModule(argument_spec=argument_spec,
                              supports_check_mode=True)

    module.flush(True)


main()