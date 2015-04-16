#!/usr/bin/env python

if __name__ != '__main__':
    from sys import path as syspath
    from os import path, chdir
    syspath.append(path.dirname(__file__))
    chdir(path.dirname(__file__))

from os import path
from hashlib import sha512
from uuid import uuid4
from urllib2 import quote,unquote

from sqlite3 import connect as sqconnect
from flask import (
    Flask, request, Response,
    render_template, session,
    redirect, g, url_for,
    flash)
from werkzeug.contrib.cache import SimpleCache
from rdflib import Graph

from lib.dataDB import (
    del_dataset,
    loadDatasetsDB, create_dataset,
    index_dir, update_dataset, cleanDate)


MT_RDF_XML = 'application/rdf+xml'


cache = SimpleCache()


app = Flask(__name__)
datasetRoot = 'datasets'
dbFile = ('./data.db')
with open('./secrets', 'r') as sfile:
    app.secret_key = sfile.read()

with open('./secrets', 'r') as sfile:
    salt = sfile.read()


def redirect_url(default='index'):
    return request.args.get('next') or \
        request.referrer or \
        url_for(default)


def dict_factory(cursor, row):
    d = {}
    for idx, col in enumerate(cursor.description):
        d[col[0]] = row[idx]
    return d


def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqconnect(dbFile)
    db.row_factory = dict_factory
    return db


@app.route('/')
def index():
    accepts = request.accept_mimetypes
    best = accepts.best_match([MT_RDF_XML, 'text/html'])
    if best == MT_RDF_XML and accepts[best] > accepts['text/html']:
        return index_rdf()
    else:
        return index_html()

@app.route('/index.html')
def index_html():
    datasets = []
    for dataset in loadDatasetsDB():
        datasets.append(dataset)
    return(
        render_template(
            'index.html',
            datasets=datasets,
            datasetRoot=datasetRoot
        )
    )

@app.route('/index.rdf')
def index_rdf():
    key = index_rdf.__name__
    data = cache.get(key)
    if data is None:
        data = Graph().parse(data=index_html(),
                format='rdfa', media_type='text/html'
                ).serialize(format='pretty-xml')
        cache.set(key, data, timeout=60 * 60)
    return Response(data, mimetype=MT_RDF_XML)

@app.before_request
def log_request():
    if app.config.get('LOG_REQUESTS'):
        app.logger.debug('whatever')


@app.route('/<datasets>/<int:year>/<month>/<dataset>/<path:directory>/')
@app.route('/<datasets>/<int:year>/<month>/<dataset>/')
def viewDataset(datasets, year, month, dataset, directory=None):
    if datasets != datasetRoot:
        return(render_template('error.html', message='Not found'))
    datasetPath = path.join(str(year), str(month), dataset)
    dataset = loadDatasetsDB(datasetPath=datasetPath, singleLookup=True)
    if len(dataset) > 0:
        dataset = dataset[0]
    else:
        return(render_template("error.html",
               message="Could not find dataset"))
    if dataset.get('created_at'):
        dataset['cleanCreated'] = cleanDate(dataset['created_at'])
    if dataset.get('updated_at'):
        dataset['cleanUpdated'] = cleanDate(dataset['updated_at'])
    pathDict = {}
    if dataset['url'] == '':
        try:
            pathDict, dirUp, metadata = index_dir(directory, dataset, datasetRoot)
        except Exception as e:
            print e
            return(render_template("error.html",
                   message="Could not generate index"))
    if dataset['url'] != '':
        pathDict = None
        dirUp = None
    return(
        render_template(
            'dataset.html',
            datasetRoot=datasetRoot,
            dataset=dataset,
            pathDict=pathDict,
            dirUp=dirUp,
            metadata=metadata,
            quote=quote,
            unquote=unquote,
            datasetID=dataset['datasetID']
        )
    )


@app.route('/<datasets>/<datasetName>')
def vieDatasetURL(datasets, datasetName):
    if datasets != datasetRoot:
        return(render_template('error.html', message='Not found'))
    dataset = loadDatasetsDB(datasetName=datasetName, singleLookup=True)
    if len(dataset) > 0:
        dataset = dataset[0]
    if dataset.get('created_at'):
        dataset['cleanCreated'] = cleanDate(dataset['created_at'])
    if dataset.get('updated_at'):
        dataset['cleanUpdated'] = cleanDate(dataset['updated_at'])
    return(render_template('dataset.html', dataset=dataset, dirUp=None, pathDict=None))

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    print request.headers
    print request.remote_user
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        pwHashed = sha512(password + salt).hexdigest()
        cur = get_db().cursor()
        cur.execute('SELECT * from users where username = ?', (username, ))
        res = cur.fetchone()
        if res['password'] == pwHashed:
            session['logged_in'] = True
            session['username'] = username
            return redirect(url_for('index'))
        else:
            error = 'Invalid password!'
    return(render_template('login.html', error=error))


@app.route('/login2')
def login2():
    redirectTo = request.args.get('next', '/')
    if request.headers['schacHomeOrganization'] == 'kb.se':
        session['username'] = request.headers['eppn']
        session['logged_in'] = True
        session['real_name'] = request.headers['displayName']
        return redirect(redirectTo)
    else:
        return('Can not authenticate')


@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    session.pop('username', None)
    return redirect(url_for('index'))


@app.route('/new', methods=['GET', 'POST'])
def addDataset():
    if request.method == 'GET':
        if not session.get('logged_in'):
            return(render_template("error.html",
                   message="You must be logged in!"))
        if session.get('logged_in'):
            return(render_template('newform.html'))
    if request.method == 'POST':
        if session.get('logged_in'):
            create_dataset(request.form)
            flash('Created!')
            return redirect(url_for('index'))
        else:
            return(render_template("error.html",
                   message="You must be logged in!"))


@app.route('/del/confirm/<int:datasetID>')
def confirmDel(datasetID):
    if session.get('logged_in'):
        cur = get_db().cursor()
        cur.execute('SELECT * FROM datasets where datasetid=?', (datasetID, ))
        dataset = cur.fetchone()
        return(render_template(
               'confirm.html', dataset=dataset)
               )


@app.route('/del/<int:datasetID>')
def delDataset(datasetID):
    if session.get('logged_in'):
        try:
            del_dataset(datasetID)
            flash('Deleted!')
            return redirect(url_for('index'))
        except Exception as e:
            return(render_template(
                   'error.html', message=e)
                   )


@app.route('/edit/<int:datasetID>', methods=['GET', 'POST'])
def editDataset(datasetID):
    if request.method == 'GET':
        if not session.get('logged_in'):
            return(render_template("error.html",
                   message="You must be logged in!"))
        if session.get('logged_in'):
            dataset = loadDatasetsDB(datasetID, singleLookup=True, useID=True)
            dataset = dataset[0]
            return render_template('editform.html', dataset=dataset)
    if request.method == 'POST':
        if session.get('logged_in'):
            update_dataset(request.form, datasetID)
            flash('Created!')
            return redirect(url_for('index'))
        else:
            return(render_template("error.html",
                   message="You must be logged in!"))


@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()


@app.after_request
def add_ua_compat(response):
    response.headers['X-UA-Compatible'] = 'IE=Edge'
    return response

if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument('-p', '--port', type=int)
    ap.add_argument('-d', '--debug', default=False, action='store_true')
    args = ap.parse_args()

    app.debug = args.debug
    app.run(host='0.0.0.0', port=args.port, debug=True)
