#
# Copyright (C) Stanislaw Adaszewski, 2020
# License: GNU General Public License v3.0
# URL: https://github.com/sadaszewski/focker
# URL: https://adared.ch/focker
#

import os
import yaml
from .zfs import AmbiguousValueError, \
    zfs_find, \
    zfs_tag, \
    zfs_untag, \
    zfs_mountpoint, \
    zfs_poolname, \
    zfs_set_props
from .jail import jail_fs_create, \
    jail_create, \
    jail_remove, \
    backup_file, \
    quote
from .misc import random_sha256_hexdigest, \
    find_prefix
import subprocess
import jailconf
import os
from .misc import focker_lock, \
    focker_unlock
import pdb


def exec_prebuild(spec, path):
    if isinstance(spec, str):
        spec = [ spec ]
    if not isinstance(spec, list):
        raise ValueError('exec.prebuild should be a string or a list of strings')
    spec = ' && '.join(spec)
    print('Running exec.build command:', spec)
    spec = [ '/bin/sh', '-c', spec ]
    oldwd = os.getcwd()
    os.chdir(path)
    res = subprocess.run(spec)
    if res.returncode != 0:
        raise RuntimeError('exec.prebuild failed')
    os.chdir(oldwd)


def build_volumes(spec):
    poolname = zfs_poolname()
    for tag, params in spec.items():
        name = None
        try:
            name, _ = zfs_find(tag, focker_type='volume')
        except ValueError:
            pass
        if name is None:
            sha256 = random_sha256_hexdigest()
            name = find_prefix(poolname + '/focker/volumes/', sha256)
            subprocess.check_output(['zfs', 'create', '-o', 'focker:sha256=' + sha256, name])
            zfs_untag([ tag ], focker_type='volume')
            zfs_tag(name, [ tag ])
        mountpoint = zfs_mountpoint(name)
        print('params:', params)
        if 'chown' in params:
            os.chown(mountpoint, *map(int, params['chown'].split(':')))
        if 'chmod' in params:
            os.chmod(mountpoint, params['chmod'])
        if 'zfs' in params:
            zfs_set_props(name, params['zfs'])


def build_images(spec, path, args):
    # print('build_images(): NotImplementedError')
    for (tag, focker_dir) in spec.items():
        cmd = ['focker', 'image', 'build',
            os.path.join(path, focker_dir), '-t', tag]
        if args.squeeze:
            cmd.append('--squeeze')
        focker_unlock()
        res = subprocess.run(cmd)
        focker_lock()
        if res.returncode != 0:
            raise RuntimeError('Image build failed: ' + str(res.returncode))


def setup_dependencies(spec, generated_names):
    if os.path.exists('/etc/jail.conf'):
        conf = jailconf.load('/etc/jail.conf')
    else:
        conf = jailconf.JailConf()
    for (jailname, jailspec) in spec.items():
        if 'depend' not in jailspec:
            continue
        depend = jailspec.get('depend', [])
        if isinstance(depend, str):
            depend = [ depend ]
        if not isinstance(depend, list):
            raise ValueError('depend must be a string or a list of strings')
        # pdb.set_trace()
        depend = list(map(lambda a: generated_names[a], depend))
        if len(depend) == 1:
            depend = depend[0]
        conf[generated_names[jailname]]['depend'] = \
            depend
    conf.write('/etc/jail.conf')


def build_jails(spec):
    backup_file('/etc/jail.conf')
    generated_names = {}
    for (jailname, jailspec) in spec.items():
        try:
            name, _ = zfs_find(jailname, focker_type='jail')
            jail_remove(zfs_mountpoint(name))
        except AmbiguousValueError:
            raise
        except ValueError:
            pass
        name = jail_fs_create(jailspec['image'])
        zfs_untag([ jailname ], focker_type='jail')
        zfs_tag(name, [ jailname ])
        path = zfs_mountpoint(name)
        generated_names[jailname] = \
            jail_create(path,
            jailspec.get('exec.start', '/bin/sh /etc/rc'),
            jailspec.get('env', {}),
            [ [from_, on] \
                for (from_, on) in jailspec.get('mounts', {}).items() ],
            hostname=jailname,
            overrides={
                'exec.stop': jailspec.get('exec.stop', '/bin/sh /etc/rc.shutdown'),
                'ip4.addr': jailspec.get('ip4.addr', '127.0.1.0'),
                'interface': jailspec.get('interface', 'lo1'),
                'host.hostname': jailspec.get('host.hostname', jailname)
            })

    setup_dependencies(spec, generated_names)


def command_compose_build(args):
    if not os.path.exists(args.filename):
        raise ValueError('File not found: ' + args.filename)
    path, _ = os.path.split(args.filename)
    print('path:', path)
    with open(args.filename, 'r') as f:
        spec = yaml.safe_load(f)
    if 'exec.prebuild' in spec:
        exec_prebuild(spec['exec.prebuild'], path)
    if 'volumes' in spec:
        build_volumes(spec['volumes'])
    if 'images' in spec:
        build_images(spec['images'], path, args)
    if 'jails' in spec:
        build_jails(spec['jails'])


def command_compose_run(args):
    raise NotImplementedError
