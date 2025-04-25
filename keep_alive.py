from threading import Thread

from flask import Flask

app = Flask("")


@app.route("/")
def home():
    return "Bot is running"


def run():
    port = int(os.environ.get('PORT', 5000))
    app.run(host="0.0.0.0", port=port)


def keep_alive():
    bot_thread = Thread(target=run)
    bot_thread.start()
