import psutil
import time
import thread
import subprocess

from flask import Flask
from flask import json
from flask import request

from crossdomain import crossdomain

app = Flask(__name__)
NUM_PG = 128
NUM_OSD = 3
WATCHED_POOL = 'volumes'

data = { 
        'read_op': [],
        'write_op': [],
        'read_bytes': [],
        'write_bytes': [],
        'space_used': [],
        'space_avail': [],
        'objects': [],
        'pointStart': 0, 
        'pointInterval': 0}

def collect_data():
    data['pointStart'] = int(time.time()) * 1000
    data['pointInterval'] = 60 * 1000
    res = subprocess.check_output(['rados', 'df', '-p', WATCHED_POOL, '--format', 'json'])
    res = json.loads(res)
    pre_io = res['pools'][0]['categories'][0]
    while True:
        time.sleep(60)
        res = subprocess.check_output(['rados', 'df', '-p', WATCHED_POOL, '--format', 'json'])
        res = json.loads(res)
        data['space_used'].append(int(res['total_used']))
        data['space_avail'].append(int(res['total_avail']))
        io = res['pools'][0]['categories'][0]
        data['objects'].append(int(io['num_objects']))
        data['read_op'].append(int(io['read_bytes']) - int(pre_io['read_bytes']))
        data['read_bytes'].append(int(io['read_kb']) - int(pre_io['read_kb']))
        data['write_op'].append(int(io['write_bytes']) - int(pre_io['write_bytes']))
        data['write_bytes'].append(int(io['write_kb']) - int(pre_io['write_kb']))
        pre_io = io

def setup():
    app.add_url_rule('/chart/overview', '/chart/overview', handle)
    app.add_url_rule('/chart/topology/osd', '/chart/topology/osd', handle)
    app.add_url_rule('/chart/topology/tree', '/chart/topology/tree', handle)
    app.add_url_rule('/host/cpu_percent', '/host/cpu_percent', handle)
    app.add_url_rule('/host/memory', '/host/memory', handle)
    app.add_url_rule('/host/disk', '/host/disk', handle)
    app.add_url_rule('/ceph/status', '/ceph/status', handle)
    app.add_url_rule('/ceph/osd/crush/rule/dump', '/ceph/osd/crush/rule/dump', handle)
    app.add_url_rule('/perf', '/perf', handle)
    app.add_url_rule('/query', '/query', handle)

name_dic = {#cluster information
            'read_op':'Read Times', 
            'read_bytes':'Read KB', 
            'write_op':'Write Times', 
            'write_bytes':'Write KB',
            'space_used': 'Space Used',
            'space_avail': 'Space Available',
            'objects': 'Object Number',
            }

@crossdomain(origin='*')
def handle():
    ep = request.path
    ep = ep[1:].split('/')
    resp = []
    if ep[0] == 'chart':
        if ep[1] == 'overview':
            requests = request.args.get('req', '')
            requests = requests.split(',')
            for req in requests:
                if data.has_key(req):
                    resp.append({'name': name_dic[req], 'data': data[req], 'pointStart': data['pointStart'], 'pointInterval': data['pointInterval']})
        elif ep[1] == 'topology':
            if ep[2] == 'tree':
                osds = subprocess.check_output(['ceph', 'osd', 'dump', '--format', 'json'])
                osds = json.loads(osds)['osds']
                id_info = dict()
                for osd in osds:
                    id_info[osd['osd']] = {'address':osd['public_addr'].split(':',1)[0],
                                           'in':osd['in'],
                                          }

                osds = subprocess.check_output(['ceph', 'osd', 'tree', '--format', 'json'])
                osd_nodes = json.loads(osds)['nodes']
                id_node = dict()
                for node in osd_nodes:
                    id_node[node['id']] = node
                    if node['type'] == 'osd':
                        node['address'] = id_info[node['id']]['address']
                        node['in'] = id_info[node['id']]['in']
                    node['cid'] = node['id']
                    del node['id']
                for node in osd_nodes:
                    if node.has_key('children'):
                        children = []
                        for child in node['children']:
                            children.append(id_node[child])
                        node['children'] = children

                for node in osd_nodes:
                    if node['type'] == 'root':
                        resp = node
            elif ep[2] == 'osd':
                osd_id = request.args.get('osd_id', '0')
                resp = dict()
                resp['cpu_percent'] = psutil.cpu_percent()
                resp['memory'] = psutil.virtual_memory()
                resp['disk'] = psutil.disk_usage('/var/lib/ceph/osd/ceph-'+osd_id)
                admin_socket = '/var/run/ceph/ceph-osd.%s.asok' % osd_id
                perf = subprocess.check_output(['ceph', '--admin-daemon',admin_socket, 'perf', 'dump']) 
                perf = json.loads(perf)
                resp['numpg'] = perf['osd']['numpg']
                resp['numpg_primary'] = perf['osd']['numpg_primary']
    elif ep[0] == 'ceph':
        command = ep
        command.append('--format')
        command.append('json')
        status = subprocess.check_output(command)
        resp = json.loads(status)
    elif ep[0] == 'host':
        if ep[1] == 'cpu_percent':
            resp = psutil.cpu_percent()
        elif ep[1] == 'memory':
            resp = psutil.virtual_memory()
        elif ep[1] == 'disk':
            osd_id = request.args.get('osd_id','0')
            resp = psutil.disk_usage('/var/lib/ceph/osd/ceph-'+osd_id) 
    elif ep[0] == 'perf':
        osd_id = request.args.get('osd_id','0')
        perf = subprocess.check_output(['ceph', '--admin-daemon', '/var/run/ceph/ceph-osd.%s.asok' % osd_id, 'perf', 'dump'])
        resp = json.loads(perf)
    elif ep[0] == 'query':
        query_type = request.args.get('type','')
        if query_type == 'volume':
            rbd_name = query_type + '-' + request.args.get('id','')
        else:
            rbd_name = request.args.get('id','')
        resp = dict()
        pool_name = query_type + 's'
        info = subprocess.check_output(['rbd', '-p', pool_name, 'info', rbd_name, '--format', 'json'])
        info = json.loads(info)
        num_obj = info['objects']
        prefix = info['block_name_prefix']
        pool_id = {'volumes':3, 'images':4}
        pg_cnt = subprocess.check_output(['./obj-pg', '%d' % NUM_PG, '%d' % num_obj, prefix])
        pg_cnt = json.loads(pg_cnt)
        resp['pg_cnt'] = pg_cnt
        osd_cnt = [0 for i in range(NUM_OSD)]
        for i in range(NUM_PG):
            pg_map = subprocess.check_output(['ceph', 'pg', 'map', '%d.%x' % (pool_id[pool_name], i), '--format', 'json'])
            pg_map = json.loads(pg_map)
            act_osd = pg_map['acting'][0]
            osd_cnt[act_osd] += pg_cnt[i]
        resp['osd_cnt'] = osd_cnt 
        resp['pool_id'] = pool_id[pool_name];

    return json.dumps(resp)

if __name__ == '__main__':
    setup()
    thread.start_new_thread(collect_data, ())
    app.run(host='0.0.0.0', port=2333, debug=True)
