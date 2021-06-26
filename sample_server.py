import atexit
import ipaddress
import json
import threading
import time

import flask
import requests
from apscheduler.schedulers.background import BackgroundScheduler
from flask import request, Flask, jsonify


class Client:
    CLIENT_PORT = 4000
    ip: str
    last_seen: time
    alive: bool
    base_url: str
    is_v6: bool
    access_token: str
    query_count: int

    def __init__(self, ip: str, is_v6: bool):
        self.ip = ip
        self.last_seen = time.time()
        self.alive = True
        self.query_count = 0

        if is_v6:
            self.base_url = "http://[%s]:%d" % (ip, self.CLIENT_PORT)
        else:
            self.base_url = "http://%s:%d" % (ip, self.CLIENT_PORT)

    def seen(self, token: str):
        self.last_seen = time.time()
        self.access_token = token
        self.query_count = 0

        if not self.alive:
            print("Client %s state change to alive" % self.ip)
            self.alive = True

    def fetch(self):
        print("fetch data from client: %s" % self.query_count)

        if self.query_count < 5:
            try:
                response = requests.get(self.base_url + "/user",
                                        headers={"Authorization": "Bearer " + self.access_token},
                                        params={'format': 'json'}, verify=False)
                print(response.json())
                self.query_count += 1
            except requests.ConnectionError:
                self.alive = False
                print("client %s dead!" % self.ip)


class ClientFetchingThread(threading.Thread):
    client: Client

    def __init__(self, client: Client):
        threading.Thread.__init__(self)
        self.client = client

    def run(self):
        self.client.fetch()


class ResponseStatus:
    status: str

    def __init__(self, status: str):
        self.status = status

    def to_json(self):
        return json.dumps(self, default=lambda o: o.__dict__,
                          sort_keys=True, indent=4)


class ClientManager:
    clients: dict  # key -> client IP,  value -> Client
    lock: threading.Lock

    def __init__(self):
        self.clients = {}
        self.lock = threading.Lock()

    def client_notify(self, data, ip, is_v6):
        token = None

        if data is not None:
            token = data['accessToken']
        if token is None:
            return jsonify(ResponseStatus("failed"))

        self.clients.setdefault(ip, Client(ip, is_v6))  # (ATOMIC) insert if not exists
        client = self.clients[ip]
        client.seen(token)

        print("receive notification from %s" % ip)
        return ResponseStatus("success").to_json()

    def polling(self):
        with self.lock:
            print("Number of client: %d at %s" % (len(self.clients), time.strftime("%A, %d. %B %Y %I:%M:%S %p")))

            if len(self.clients) > 0:
                client_threads = []
                dead_entry = []

                for ip, client in self.clients.items():
                    if client.alive:
                        print("Client: %s, %s" % (client.ip, client.last_seen))
                        client_thread = ClientFetchingThread(client)
                        client_thread.start()
                        client_threads.append(client_thread)
                    else:
                        dead_entry.append(ip)

                if len(dead_entry) > 0:
                    for ip in dead_entry:
                        del self.clients[ip]

                for t in client_threads:
                    t.join()


app = Flask(__name__)
clientManager = ClientManager()


@app.route('/notify', methods=['POST'])
def notify():
    ip = ipaddress.ip_address(request.remote_addr)
    ip_string = str(ip)
    ipv6 = True

    if str(ip.ipv4_mapped) is not None:
        ip_string = str(ip.ipv4_mapped)
        ipv6 = False

    return clientManager.client_notify(request.json, ip_string, ipv6)


def polling_all_clients():
    clientManager.polling()


if __name__ == '__main__':
    print("Flask version: %s" % flask.__version__)

    scheduler = BackgroundScheduler()
    scheduler.add_job(func=polling_all_clients, trigger='interval', seconds=10, id='client_polling')
    scheduler.start()

    # Shut down the scheduler when exiting the app
    atexit.register(lambda: scheduler.shutdown())
    app.run(host='::', debug=True, port=5000, use_reloader=False)
