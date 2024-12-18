# This files contains your custom actions which can be used to run
# custom Python code.
#
# See this guide on how to implement these action:
# https://rasa.com/docs/rasa/custom-actions


# This is a simple example for a custom action which utters "Hello World!"

from typing import Any, Text, Dict, List

from rasa_sdk import Action, Tracker
from rasa_sdk.executor import CollectingDispatcher
import psycopg2
from psycopg2.extras import DictCursor
import logging
from datetime import datetime
from contextlib import contextmanager

# konfiguration logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# konfiguration koneksi database
DB_CONFIG = {
    "dbname":"db_ppks",
    "user":"postgres",
    "password":"123",
    "host":"localhost",
    "port":"5432"
}
db_connection = None

def get_db_connection():
    global db_connection
    try:
        if db_connection is None or db_connection.closed:
            db_connection = psycopg2.connect(**DB_CONFIG)
            db_connection.autocommit = True
            logger.info("created new database connection")
    except psycopg2.Error as e:
        logger.error(f"Database connection error: {e}")
        raise
    return db_connection

