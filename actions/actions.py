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
@contextmanager
def get_db_cursor():
    connection = get_db_connection()
    cursor = None
    try:
        cursor = connection.cursor(cursor_factory=DictCursor)
        yield cursor
    except psycopg2.Error as e:
        logger.error(f"Database cursor error: {e}")
        raise
    finally:
        if cursor is not None:
            cursor.close()
            
class ActionFAQ(Action):
    def name(self) -> Text:
        return "action_faq"
    
    def search_faq(self, category: str = None, topic : str = None,
                    user_message : str = None) -> Dict:
        try:
            with get_db_cursor() as cur:
                if category and topic:
                    query = """ 
                        SELECT m.*, k.kategori, k.deskripsi as kategori_deskripsi
                        FROM materi m 
                        JOIN kategori k ON m.kategori = k.id_kategori
                        WHERE k.kategori ILIKE %s
                        AND (
                            m.judul ILINE %s
                            OR %s = ANY(m.phrases)
                            OR to_tsvector('indonesia',m.deskripsi) @@
                                plainto_tsquery('indonesia', %s)
                        ) 
                        ORDER BY
                            CASE 
                                WHEN m.judul ILIKE &s THEN 1
                                WHEN %s = ANY(m.phrases) THEN 2
                                ELSE 3
                            END
                        LIMIT 1;
                    """
                    cur.execute(query, (
                        f"%{category}%",
                        f"%{topic}%",
                        topic,
                        topic,
                        f"%{topic}%",
                        topic
                    ))
                elif category:
                    query = """
                        SELECT 
                            k.id_kategori,
                            k.kategori,
                            k.deskripsi,
                            array_agg(m.judul) as related_topics
                        FROM kategori k
                        LEFT JOIN materi m ON k.id_kategori = m.kategori_id
                        WHERE k.kategori ILIKE %s
                        GROUP BY k.id_kategori, k.kategori, k.deskripsi
                        LIMIT 1;
                    """
                    cur.execute(query, (f"%{category}%",))
                
                elif topic:
                    query = """
                        SELECT m.*, k.kategori, k.deskripsi as kategori_deskripsi
                        FROM materi m
                        JOIN kategori k ON m.kategori_id = k.id_kategori
                        WHERE 
                            m.judul ILIKE %s
                            OR %s = ANY(m.phrases)
                            OR to_tsvector('indonesian', m.deskripsi) @@ 
                                plainto_tsquery('indonesian', %s)
                        ORDER BY 
                            CASE 
                                WHEN m.judul ILIKE %s THEN 1
                                WHEN %s = ANY(m.phrases) THEN 2
                                ELSE 3
                            END
                        LIMIT 1;
                    """
                    cur.execute(query, (
                        f"%{topic}%",
                        topic,
                        topic,
                        f"%{topic}%",
                        topic
                    ))
                
                else:
                    query = """
                        SELECT m.*, k.kategori, k.deskripsi as kategori_deskripsi
                        FROM materi m
                        JOIN kategori k ON m.kategori_id = k.id_kategori
                        WHERE to_tsvector('indonesian', 
                            m.judul || ' ' || m.deskripsi || ' ' || 
                            array_to_string(m.phrases, ' ')
                        ) @@ plainto_tsquery('indonesian', %s)
                        LIMIT 1;
                    """
                    cur.execute(query, (user_message,))

                result = cur.fetchone()
                return dict(result) if result else None

        except psycopg2.Error as e:
            logger.error(f"Database query error: {e}")
            return None

    def format_response(self, result: Dict) -> str:
        """Format hasil pencarian menjadi respons."""
        if not result:
            return ("Maaf, saya tidak menemukan informasi yang sesuai dengan "
                    "pertanyaan Anda. Mohon ajukan pertanyaan dengan cara yang "
                    "berbeda atau tanyakan hal lain.")

        if 'related_topics' in result:
            response = (
                f"Kategori: {result['kategori']}\n\n"
                f"{result['deskripsi']}\n\n"
                "Anda dapat bertanya lebih spesifik tentang topik-topik berikut:\n"
            )
            topics = [topic for topic in result['related_topics'] if topic]
            response += "\n".join(f"- {topic}" for topic in topics[:5])
            return response

        return (
            f"Kategori: {result['kategori']}\n\n"
            f"{result['deskripsi']}\n\n"
            "Apakah ada hal lain yang ingin Anda ketahui?"
        )

    def run(self, dispatcher: CollectingDispatcher,
            tracker: Tracker,
            domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:
        start_time = datetime.now()

        try:
            entities = tracker.latest_message.get('entities', [])
            user_message = tracker.latest_message.get('text', '')

            category = next((
                e['value'] for e in entities if e['entity'] == 'category'
            ), None)
            topic = next((
                e['value'] for e in entities if e['entity'] == 'topic'
            ), None)

            result = self.search_faq(category, topic, user_message)
            response = self.format_response(result)
            dispatcher.utter_message(text=response)

            execution_time = (datetime.now() - start_time).total_seconds()
            logger.info(
                f"FAQ query executed in {execution_time:.2f}s. "
                f"Category: {category}, Topic: {topic}"
            )

            return []

        except Exception as e:
            logger.error(f"Error in FAQ handler: {e}")
            dispatcher.utter_message(
                text="Maaf, terjadi kesalahan dalam memproses pertanyaan Anda. "
                        "Mohon coba lagi nanti."
            )
            return []
                    