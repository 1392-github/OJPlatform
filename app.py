from flask import *
from sqlite3 import connect
from zipfile import ZipFile
from tempfile import TemporaryDirectory
import os
from io import BytesIO
from subprocess import Popen
from threading import Thread, Lock
from time import sleep
'''from asyncio import get_event_loop
from websockets import serve
from json import loads'''

version = 1

PORT = 80
JUDGE_DATA_DELAY = 0.1
DOMAIN = "127.0.0.1"

lock = Lock()
rt = render_template
db = connect("data.db", isolation_level=None, check_same_thread=False)
c = db.cursor()

queue = []

with open("init.txt") as f:
    c.executescript(f.read())

c.execute("insert into config select 'version', ? where not exists (select * from config where name='version')", (version,))
dbver = int(c.execute("select value from config where name='version'").fetchone()[0])

if not c.execute("select exists (select * from config where name='password')").fetchone()[0]:
    c.execute("insert into config values('password',?)", (input('관리자 비밀번호를 입력하세요 -> '),))
c.execute("insert into config select 'start', 0 where not exists (select * from config where name = 'start')")

app = Flask(__name__)
app.secret_key = "12345678"

'''async def accept(ws, _):
    #data = await ws.recv()
    #page = int(data)
    while True:
        r = c.execute("select id, prob, result, result2 from submit").fetchall()
        j = []
        for a in r:
            j.append({"id":a[0], "prob":a[1], "result":a[2], "result2":a[3]})
        ws.send(j)'''
def judge_thread():
    c = db.cursor()
    while True:
        if len(queue) == 0:
            continue
        current = queue.pop(0)
        print('judging', current)
        c.execute('update submit set result=1 where id=?', (current,))
        with open('judge.py', 'w', encoding="UTF-8") as f:
            f.write(c.execute("select code from submit where id=?", (current,)).fetchone()[0])
        for case in c.execute('select input, output from testcase where problem=(select prob from submit where id=?)', (current,)):
            proc = Popen(['python', 'judge.py'], stdin=-1, stdout=-1, stderr=-3)
            result, _ = proc.communicate(input=case[0].encode('utf-8'))
            result = result.decode('cp949').replace('\r\n', '\n').rstrip('\n')
            if result != case[1]:
                c.execute('update submit set result=3 where id=?', (current,))
                break
        else:
            c.execute('update submit set result=2 where id=?', (current,))
        sleep(3)
@app.route("/")
def root():
    if not session.get('admin', False):
        if not c.execute("select exists (select * from whitelist where ip=?)", (request.remote_addr,)).fetchone()[0]:
            return rt('not_whitelist.html')
        if not int(c.execute("select value from config where name='start'").fetchone()[0]):
            return rt('not_start.html')
    return rt('master.html', p=c.execute('select id, name, score from problem').fetchall())
@app.route("/admin")
def admin():
    if not session.get('admin', False):
        return rt('input_password.html')
    return rt('admin.html', problem=c.execute('select id, name from problem').fetchall(), user=[x[0] for x in c.execute('select ip from whitelist').fetchall()])
@app.route("/password", methods=['POST'])
def password():
    if request.form['password'] == c.execute("select value from config where name='password'").fetchone()[0]:
        session['admin'] = True
        return redirect('/admin')
    else:
        return rt('alert.html', msg='비밀번호가 잘못되었습니다', redirect='/')
@app.route("/logout")
def logout():
    del session['admin']
    return redirect('/')
@app.route("/start")
def start():
    if not session.get('admin', False):
        return rt('input_password.html')
    c.execute("update config set value=1 where name='start'")
    return redirect('/admin')
@app.route("/stop")
def stop():
    if not session.get('admin', False):
        return rt('input_password.html')
    c.execute("update config set value=0 where name='start'")
    return redirect('/admin')
@app.route("/add_problem", methods=['GET','POST'])
def add_problem():
    if not session.get('admin', False):
        return rt('input_password.html')
    if request.method == 'POST':
        c.execute('insert into problem (name, score, type, time, memory, content) values(?,?,0,?,?,?)', (request.form['title'], request.form['score'], request.form['time'], request.form['ram'], request.form['content']))
        return redirect('/admin')
    return rt('add_problem.html')
@app.route('/whitelist', methods=['POST'])
def whitelist():
    c.execute('insert into whitelist values(?)', (request.form['name'],))
    return redirect('/admin')
@app.route('/whitelist_remove/<ip>')
def whitelist_remove(ip):
    c.execute('delete from whitelist where ip=?', (ip,))
    return redirect('/admin')
@app.route('/problem_admin/<int:n>', methods=['GET','POST'])
def problem_admin(n):
    if not session.get('admin', False):
        return rt('input_password.html')
    if request.method == 'POST':
        c.execute('update problem set name=?, score=?, time=?, memory=?, content=? where id=?', (request.form['name'], request.form['score'], request.form['time'], request.form['ram'], request.form['content'], n))
        return redirect('/admin')
    return rt('problem_admin.html', c=c.execute('select name, score, time, memory, content from problem where id=?', (n,)).fetchone(), n=n)
@app.route('/testcase', methods=['POST'])
def testcase():
    if not session.get('admin', False):
        return rt('input_password.html')
    f = request.files['file']
    z = ZipFile(f)
    with TemporaryDirectory() as d:
        z.extractall(path=d)
        d2 = {}
        for f in os.listdir(d):
            if f.endswith('.in'):
                if f[:-3] not in d2:
                    d2[f[:-3]] = [None, None]
                with open(os.path.join(d, f), encoding='utf-8') as fs:
                    d2[f[:-3]][0] = fs.read().replace("\r\n", "\n")
            elif f.endswith('.out'):
                if f[:-4] not in d2:
                    d2[f[:-4]] = [None, None]
                with open(os.path.join(d, f), encoding='utf-8') as fs:
                    d2[f[:-4]][1] = fs.read().replace("\r\n", "\n")
        c.execute('delete from testcase where problem=?', (request.form['id'],))
        for tc in d2.values():
            c.execute('insert into testcase (subtask, problem, input, output) values(0, ?, ?, ?)', (request.form['id'], tc[0], tc[1]))
    return redirect('/admin')
@app.route('/testcase_download/<int:id>')
def testcase_download(id):
    if not session.get('admin', False):
        return rt('input_password.html')
    data = c.execute('select id, input, output from testcase where problem=?', (id,)).fetchall()
    f = BytesIO()
    with ZipFile(f, 'w') as z:
        for tc in data:
            z.writestr(str(tc[0]) + '.in', tc[1])
            z.writestr(str(tc[0]) + '.out', tc[2])
    f.seek(0)
    return send_file(f, download_name='testcase.zip', as_attachment=True)
@app.route('/problem/<int:id>', methods=['GET', 'POST'])
def problem(id):
    if not session.get('admin', False):
        if not c.execute("select exists (select * from whitelist where ip=?)", (request.remote_addr,)).fetchone()[0]:
            return rt('not_whitelist.html')
        if not int(c.execute("select value from config where name='start'").fetchone()[0]):
            return rt('not_start.html')
    if request.method == 'POST':
        c.execute("insert into submit (prob, code, result) values(?,?,0)", (id, request.form['code']))
        queue.append(c.execute("select seq from sqlite_sequence where name='submit'").fetchone()[0])
        return redirect('/status')
    r = c.execute("select name, content from problem where id=?", (id,)).fetchone()
    return rt('problem.html', id=id, title=r[0], content=r[1])
@app.route('/delete/<int:id>')
def delete(id):
    if not session.get('admin', False):
        return rt('input_password.html')
    c.execute("delete from problem where id=?", (id,))
    return redirect('/admin')
@app.route('/status')
def status():
    if not session.get('admin', False):
        if not c.execute("select exists (select * from whitelist where ip=?)", (request.remote_addr,)).fetchone()[0]:
            return rt('not_whitelist.html')
        if not int(c.execute("select value from config where name='start'").fetchone()[0]):
            return rt('not_start.html')
    return rt('submit.html', status = c.execute("select id, prob, result from submit").fetchall())
t = Thread(target=judge_thread)
t.daemon = True
t.start()
'''print("ws://" + DOMAIN + "/")
ws_start = serve(accept, "127.0.0.1", 81)
get_event_loop().run_until_complete(ws_start)
get_event_loop().run_forever()'''
app.run(host='127.0.0.1', port=PORT, debug=False)
