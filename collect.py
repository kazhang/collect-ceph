import psutil
import time
import thread
import subprocess

from flask import Flask
from flask import json
from flask import request

from crossdomain import crossdomain

app = Flask(__name__)

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
    pre_io = {'read_bytes': 0, 'read_kb': 0, 'write_bytes': 0, 'write_kb': 0}
    while True:
        res = subprocess.check_output(['rados', 'df', '-p', 'volumes', '--format', 'json'])
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
        time.sleep(60)

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
                id_addr = dict()
                for osd in osds:
                    id_addr[osd['osd']] = osd['public_addr'].split(':',1)[0] 

                osds = subprocess.check_output(['ceph', 'osd', 'tree', '--format', 'json'])
                osd_nodes = json.loads(osds)['nodes']
                id_node = dict()
                for node in osd_nodes:
                    id_node[node['id']] = node
                    if node['type'] == 'osd':
                        node['address'] = id_addr[node['id']]
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

    return json.dumps(resp)

if __name__ == '__main__':
    setup()
    thread.start_new_thread(collect_data, ())
    app.run(host='0.0.0.0', port=2333, debug=True)