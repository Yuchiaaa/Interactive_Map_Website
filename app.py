from flask import Flask, render_template, request, redirect, url_for, flash, session, abort
import sqlite3
from flask_session import Session

app = Flask(__name__)
app.config['SECRET_KEY'] = '14806762'

@app.route('/')
def index():
    return render_template("index.html")
