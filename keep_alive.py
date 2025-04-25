from threading import Thread

from flask import Flask

app = Flask("")


@app.route("/")
def home():
    return "Bot is running"


def run():
    app.run(host="0.0.0.0", port=8080)


def keep_alive():
    bot_thread = Thread(target=run)
    bot_thread.start
