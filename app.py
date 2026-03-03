import sqlite3
from flask import Flask, render_template, request, redirect, url_for, flash, session, abort


app = Flask(__name__)
app.config['SECRET_KEY'] = '14806762'

@app.route('/')
def index():
    return render_template("index.html")

@app.route('/map')
def map():
    return render_template("map.html")
