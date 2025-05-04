from threading import Thread
import os
from flask import Flask

app = Flask("")


@app.route("/")
def home():
    return "Bot is running."


def run():
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)


def keep_alive():
    t = Thread(target=run)
    t.start()
