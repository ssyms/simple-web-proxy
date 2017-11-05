import threading, BaseHTTPServer, socket, ssl, select, httplib, urlparse
import datetime, thread
from SocketServer import ThreadingMixIn
from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit
from threading import Thread

BLOCKED_URLS = []

app = Flask(__name__)
socketio = SocketIO(app)

# Cache to store responses to avoid repeating requests
class ProxyCache:

    # initilizes the cache
    def __init__(self):
        self.cache = {}
        self.max_cache_size = 50

    def __contains__(self, key):
        return key in self.cache

    # adds new request/response to cache
    def update(self, key, value):
        if key not in self.cache and len(self.cache) >= self.max_cache_size:
            self.pop_oldest()

        self.cache[key] = {'date_accessed': datetime.datetime.now(),
                           'value': value}

    # removes the oldest entry from the cache
    def pop_oldest(self):
        oldest_entry = None
        for key in self.cache:
            if oldest_entry is None:
                oldest_entry = key
            elif self.cache[key]['date_accessed'] < self.cache[oldest_entry][
                'date_accessed']:
                oldest_entry = key
        self.cache.pop(oldest_entry)

    # returns the response to the request
    def get_key(self, key):
        return self.cache[key]['value']

    @property
    def size(self):
        return len(self.cache)

    def empty(self):
        self.cache = {}

# create global thread for proxy server
thread = Thread()

# create cache instance
cache = ProxyCache()

# creates a http server that can handle multiple requests using threading
class ThreadingHTTPServer(ThreadingMixIn, BaseHTTPServer.HTTPServer):
    pass

# forwards and process the requests
class WebProxyRequestHandler(BaseHTTPServer.BaseHTTPRequestHandler):
    timeout = 5
    lock = threading.Lock()

    # creates thread for requests that need connection
    def __init__(self, *args, **kwargs):
        self.thr_loc = threading.local()
        self.thr_loc.conns = {}
        BaseHTTPServer.BaseHTTPRequestHandler.__init__(self, *args, **kwargs)

    # connect method for ssl
    def do_CONNECT(self):
        req = self

        # update the management console
        con_print = "CONNECT: " + req.headers['Host'].split(':')[0]

        # checks whether the url is blocked
        if(req.headers['Host'].split(':')[0] in BLOCKED_URLS):
            con_data = {'req': con_print, 'blocked': 1}
            socketio.emit('update_console', con_data, namespace='/test')
            socketio.sleep(0)
            self.send_error(501)
            return

        con_data = {'req': con_print, 'blocked': 0}
        socketio.emit('update_console', con_data, namespace='/test')
        socketio.sleep(0)

        # creating socket and completing hand shake
        conn_addr = self.path.split(':', 1)
        conn_addr[1] = int(conn_addr[1]) or 443
        try:
            soc = socket.create_connection(conn_addr)
        except:
            self.send_error(502)
            return
        self.send_response(200, 'Connection Established')
        self.end_headers()

        soc_conns = [self.connection, soc]
        self.end_con = 0
        while not self.end_con:
            # determines when connection has response
            reads, _, excepts = select.select(soc_conns, [], soc_conns)
            if not (excepts or not reads):
                for read in reads:
                    if read is soc_conns[0]:
                        add = soc_conns[1]
                    else:
                        add = soc_conns[0]
                    data = read.recv(8192)
                    if data:
                        add.sendall(data)
                    else:
                        self.end_con = 1

    def do_GET(self):
        req = self

        # send request to front end console
        con_print = "GET: " + req.headers['Host']
        if(req.headers['Host'] in BLOCKED_URLS):
            con_data = {'req': con_print, 'blocked': 1}
            socketio.emit('update_console', con_data, namespace='/test')
            socketio.sleep(0)
            self.send_error(501)
            return
        con_data = {'req': con_print, 'blocked': 0}
        socketio.emit('update_console', con_data, namespace='/test')
        socketio.sleep(0)

        # parsing the url data, checking for errors
        url_data = urlparse.urlsplit(req.path)
        netloc = url_data.netloc
        scheme = url_data.scheme
        if url_data.query:
            path = url_data.path + '?' + url_data.query
        else:
            path = url_data.path

        if scheme not in ('http', 'https'):
            self.send_error(502)
            return

        if netloc:
            req.headers['Host'] = netloc

        # getting the data
        try:
            req_origin = (scheme, netloc)

            # checks in cache first
            if req_origin in cache:
                response = cache.get_key(req_origin)
            else:
                # if request has not been made, create connection
                if not req_origin in self.thr_loc.conns:
                    if scheme == 'https':
                        self.thr_loc.conns[req_origin] = httplib.HTTPSConnection(netloc, timeout=self.timeout)
                    else:
                        self.thr_loc.conns[req_origin] = httplib.HTTPConnection(netloc, timeout=self.timeout)

                # get connection and read response, update cache
                conn = self.thr_loc.conns[req_origin]
                content_length = int(req.headers.get('Content-Length', 0))
                req_body = self.rfile.read(content_length) if content_length else None
                conn.request(self.command, path, req_body, dict(req.headers))
                response = conn.getresponse()
                cache.update(req_origin, response)

            # process the response
            version_table = {10: 'HTTP/1.0', 11: 'HTTP/1.1'}
            setattr(response, 'headers', response.msg)
            setattr(response, 'response_version', version_table[response.version])

            res_body = response.read()
        except Exception as e:
            if req_origin in self.thr_loc.conns:
                del self.thr_loc.conns[req_origin]
            self.send_error(502)
            return

        # send back the data to client
        self.wfile.write("%s %d %s\r\n" % (self.protocol_version, response.status, response.reason))
        for line in response.headers.headers:
            self.wfile.write(line)
        self.end_headers()
        self.wfile.write(res_body)
        self.wfile.flush()

    # only really need get and connect
    do_HEAD = do_GET
    do_POST = do_GET
    do_PUT = do_GET
    do_DELETE = do_GET
    do_OPTIONS = do_GET

    def log_error(self, msg, arg):
        pass


# initializes the web proxy server as a separate thread
class WebProxyStart(Thread):
    def __init__(self):
        super(WebProxyStart, self).__init__()

    # initializes the proxy server
    def start_proxy(self):
        server_address = ('localhost', 8080)
        cache.empty()
        # pass in the request handler to the server
        httpd = ThreadingHTTPServer(server_address, WebProxyRequestHandler)
        server_addr = httpd.socket.getsockname()
        print "Serving HTTP Proxy on", server_addr[0], "port", server_addr[1], "..."
        httpd.serve_forever()

    def run(self):
        self.start_proxy()

# renders the management console
@app.route('/')
def index():
    print "running"
    return render_template('console.html')

# adds a url to list of blocked urls
@socketio.on('block url', namespace='/url')
def add_blocked_url(message):
    block_url = message['data']
    BLOCKED_URLS.append(block_url)

# starts the webproxy and connects to management console
@socketio.on('connect', namespace='/test')
def connect_proxy():
    global thread

    # Starts the proxy in a separate thread
    if not thread.isAlive():
        print "Starting Thread"
        thread = WebProxyStart()
        thread.start()

# run the entire application
if __name__ == '__main__':
    print "main running"
    socketio.run(app)
