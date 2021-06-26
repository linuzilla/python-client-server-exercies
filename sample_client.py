import ipaddress
import json
import random
import string
import threading
from datetime import datetime

import requests
from apscheduler.schedulers.background import BackgroundScheduler
from flask import Flask, jsonify, request


class ClientResponseStatus:
    status: str
    message: str

    def __init__(self, status: str, message: str):
        self.status = status
        self.message = message

    def to_json(self):
        return json.dumps(self, default=lambda o: o.__dict__,
                          sort_keys=True, indent=4)


class ControlServer:
    BASE_URL = 'http://192.168.1.101:5000'
    WHILE_LIST = ['127.0.0.1', '192.168.1.101']
    SERVER_AWAY_TIMEOUT = 40

    last_access: datetime
    access_token: str
    lock: threading.Lock
    server_not_response_extra_time: int

    def __init__(self):
        self.access_token = ''.join(random.choices(string.ascii_letters + string.digits, k=24))
        self.lock = threading.Lock()
        self.last_access = datetime(1999, 1, 1)
        self.server_not_response_extra_time = 0

    def check_server(self, f):
        ip = ipaddress.ip_address(request.remote_addr)
        ip_string = str(ip)

        if str(ip.ipv4_mapped) is not None:
            ip_string = str(ip.ipv4_mapped)

        if ip_string in self.WHILE_LIST:
            self.last_access = datetime.now()
            print("check ok and call lambda")
            return f()
        else:
            print("%s: server ip not allowed" % ip_string)
            return ClientResponseStatus("failed", "IP not allowed")

    def retrieve_user(self):
        print("call retrieve_user (%s)" % self.access_token)
        return jsonify({"user": "nobody"})

    def retrieve_process(self):
        return jsonify({"process": "empty"})

    def retrieve_vm(self):
        return jsonify({"vm": "no vm"})

    def notify(self):
        duration = (datetime.now() - self.last_access).total_seconds()

        if duration > self.SERVER_AWAY_TIMEOUT + self.server_not_response_extra_time:
            print("time diff: %s (try to notify server)" % duration)
            with self.lock:
                try:
                    data = {'accessToken': self.access_token}
                    result = requests.post(self.BASE_URL + "/notify", json=data)
                    print("status code: %s" % result.status_code)
                    print(result.json())
                    self.server_not_response_extra_time = 0
                except requests.ConnectionError:
                    print("cannot connect to server")
                    self.server_not_response_extra_time += self.SERVER_AWAY_TIMEOUT
        else:
            print("time diff: %s (no need to notify server)" % duration)


app = Flask(__name__)
controlServer = ControlServer()


def in_orphan_state_checker():
    controlServer.notify()


@app.route('/user', methods=['GET'])
def retrieve_user():
    return controlServer.check_server(lambda: controlServer.retrieve_user())


@app.route('/process', methods=['GET'])
def retrieve_process():
    return controlServer.check_server(lambda: controlServer.retrieve_process())


@app.route('/vm', methods=['GET'])
def retrieve_vm():
    return controlServer.check_server(lambda: controlServer.retrieve_vm())


if __name__ == '__main__':
    scheduler = BackgroundScheduler()
    # scheduler.init_app(app)
    scheduler.add_job(func=in_orphan_state_checker, trigger='interval', seconds=7, id='orphan_checker')
    scheduler.start()

    app.run(host='::', debug=True, port=4000, use_reloader=False)
