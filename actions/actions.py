# This files contains your custom actions which can be used to run
# custom Python code.
#
# See this guide on how to implement these action:
# https://rasa.com/docs/rasa/custom-actions


# This is a simple example for a custom action which utters "Hello World!"

from typing import Any, Text, Dict, List

from rasa_sdk import Action, Tracker
from rasa_sdk.executor import CollectingDispatcher
from rasa_sdk.events import SlotSet
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

# Reporting Action
class ActionSubmitReport(Action):
    def name(self) -> Text:
        return "action_submit_report"
    
    def run(
        self, 
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any]
    ) -> List[Dict[Text, Any]]:
        """Menyimpan laporan ke database dan menghasilkan nomor referensi."""
        
        # Ambil semua data dari slots
        pelapor_kategori = tracker.get_slot("pelapor_kategori")
        nama_pelapor = tracker.get_slot("nama_pelapor")
        program_studi = tracker.get_slot("program_studi")
        kelas = tracker.get_slot("kelas")
        jenis_kelamin = tracker.get_slot("jenis_kelamin")
        nomor_telepon = tracker.get_slot("nomor_telepon")
        alamat = tracker.get_slot("alamat")
        email = tracker.get_slot("email")
        is_disabilitas = tracker.get_slot("is_disabilitas")
        jenis_disabilitas = tracker.get_slot("jenis_disabilitas") if is_disabilitas else None
        jenis_kekerasan = tracker.get_slot("jenis_kekerasan")
        deskripsi_kejadian = tracker.get_slot("deskripsi_kejadian")
        status_terlapor = tracker.get_slot("status_terlapor")
        alasan_pengaduan = tracker.get_slot("alasan_pengaduan")
        alasan_pengaduan_lainnya = tracker.get_slot("alasan_pengaduan_lainnya")
        kontak_konfirmasi = tracker.get_slot("kontak_konfirmasi")
        
        nomor_referensi = None
        try:
            with get_db_cursor() as cur:
                # 1. Dapatkan ID untuk kategori pelapor
                cur.execute("SELECT id_kategori FROM kategori_pelapor WHERE LOWER(nama) = %s", 
                        (pelapor_kategori.lower(),))
                result = cur.fetchone()
                if not result:
                    logger.warning(f"Kategori pelapor '{pelapor_kategori}' tidak ditemukan")
                    # Gunakan default jika tidak ditemukan
                    kategori_pelapor_id = 1
                else:
                    kategori_pelapor_id = result[0]
                
                # 2. Dapatkan ID untuk status terlapor
                cur.execute("SELECT id FROM status_terlapor WHERE LOWER(nama) = %s", 
                        (status_terlapor.lower(),))
                result = cur.fetchone()
                if not result:
                    logger.warning(f"Status terlapor '{status_terlapor}' tidak ditemukan")
                    # Gunakan default jika tidak ditemukan
                    status_terlapor_id = 1
                else:
                    status_terlapor_id = result[0]
                
                # 3. Dapatkan ID untuk jenis kekerasan
                cur.execute("SELECT id FROM jenis_kekerasan WHERE LOWER(nama) = %s OR %s ILIKE '%%' || LOWER(nama) || '%%'", 
                        (jenis_kekerasan.lower(), jenis_kekerasan.lower()))
                result = cur.fetchone()
                if not result:
                    # Jika tidak ditemukan, coba tambahkan jenis kekerasan baru
                    cur.execute("INSERT INTO jenis_kekerasan (nama) VALUES (%s) RETURNING id", 
                            (jenis_kekerasan,))
                    jenis_kekerasan_id = cur.fetchone()[0]
                else:
                    jenis_kekerasan_id = result[0]
                
                # 4. Simpan laporan ke database
                cur.execute("""
                    INSERT INTO laporan_kasus (
                        kategori_pelapor_id, 
                        nama_pelapor, 
                        program_studi, 
                        kelas, 
                        jenis_kelamin, 
                        nomor_telepon, 
                        alamat, 
                        email, 
                        is_disabilitas, 
                        jenis_disabilitas, 
                        jenis_kekerasan_id, 
                        deskripsi_kejadian, 
                        status_terlapor_id, 
                        kontak_konfirmasi, 
                        status_laporan
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id, nomor_referensi
                """, (
                    kategori_pelapor_id,
                    nama_pelapor,
                    program_studi,
                    kelas,
                    jenis_kelamin,
                    nomor_telepon,
                    alamat,
                    email,
                    is_disabilitas,
                    jenis_disabilitas,
                    jenis_kekerasan_id,
                    deskripsi_kejadian,
                    status_terlapor_id,
                    kontak_konfirmasi,
                    'Submitted'
                ))
                
                laporan_id, nomor_referensi = cur.fetchone()
                
                # 5. Simpan alasan pengaduan
                if alasan_pengaduan:
                    # Handle alasan yang dipilih oleh pengguna
                    for alasan in alasan_pengaduan:
                        cur.execute("SELECT id FROM alasan_pengaduan WHERE alasan ILIKE %s", 
                                (f"%{alasan}%",))
                        result = cur.fetchone()
                        if result:
                            alasan_id = result[0]
                            cur.execute("INSERT INTO laporan_alasan (laporan_id, alasan_id) VALUES (%s, %s)",
                                    (laporan_id, alasan_id))
                    
                    # Jika ada alasan lainnya, simpan sebagai alasan dengan jenis "Lainnya"
                    if alasan_pengaduan_lainnya:
                        cur.execute("SELECT id FROM alasan_pengaduan WHERE alasan ILIKE '%Lainnya%'")
                        result = cur.fetchone()
                        if result:
                            alasan_id = result[0]
                            cur.execute("""
                                INSERT INTO laporan_alasan (laporan_id, alasan_id, alasan_lainnya) 
                                VALUES (%s, %s, %s)
                            """, (laporan_id, alasan_id, alasan_pengaduan_lainnya))
                
                # 6. Log proses pelaporan
                logger.info(f"Laporan berhasil disimpan dengan nomor referensi: {nomor_referensi}")
                
                # Catat akses dalam log
                cur.execute("""
                    INSERT INTO log_akses_laporan (laporan_id, jenis_akses, detail_akses)
                    VALUES (%s, %s, %s)
                """, (
                    laporan_id, 
                    'create', 
                    f"Laporan dibuat oleh {nama_pelapor} via chatbot"
                ))
        
        except Exception as e:
            logger.error(f"Error saat menyimpan laporan: {str(e)}")
            dispatcher.utter_message(text="Mohon maaf, terjadi kendala teknis saat menyimpan laporan Anda. Tim kami akan segera mengatasi masalah ini. Silakan coba lagi nanti atau hubungi hotline kami di 081355060444.")
            # Generate nomor referensi manual jika database error
            from datetime import datetime
            import random
            nomor_referensi = f"PPKS-{datetime.now().strftime('%y%m%d')}-{random.randint(100, 999)}"
        
        # Return event untuk set nomor referensi slot
        return [SlotSet("nomor_referensi", nomor_referensi)]


class ActionReportStatus(Action):
    def name(self) -> Text:
        return "action_report_status"
    
    def run(
        self, 
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any]
    ) -> List[Dict[Text, Any]]:
        """Memeriksa status laporan berdasarkan nomor referensi."""
        
        # Coba ekstrak nomor referensi dari pesan pengguna
        message = tracker.latest_message.get("text", "")
        
        # Cari pola PPKS-YYMMDD-XXX dalam pesan
        import re
        ref_match = re.search(r'PPKS-\d{6}-\d{3}', message)
        nomor_referensi = ref_match.group(0) if ref_match else None
        
        if not nomor_referensi:
            dispatcher.utter_message(text="Mohon maaf, saya tidak menemukan nomor referensi yang valid dalam pesan Anda. Nomor referensi memiliki format PPKS-YYMMDD-XXX (contoh: PPKS-250421-123). Mohon berikan nomor referensi lengkap untuk memeriksa status laporan.")
            return []
        
        try:
            with get_db_cursor() as cur:
                cur.execute("""
                    SELECT status_laporan, created_at 
                    FROM laporan_kasus 
                    WHERE nomor_referensi = %s
                """, (nomor_referensi,))
                
                result = cur.fetchone()
                
                if not result:
                    dispatcher.utter_message(text=f"Mohon maaf, tidak ditemukan laporan dengan nomor referensi {nomor_referensi}. Mohon periksa kembali nomor referensi Anda.")
                    return []
                
                status, tanggal = result
                
                # Format tanggal
                tanggal_str = tanggal.strftime("%d %B %Y, %H:%M")
                
                # Berikan informasi status yang bermakna
                status_info = {
                    'Submitted': "telah diterima dan sedang menunggu peninjauan oleh tim PPKS",
                    'Under Review': "sedang dalam proses peninjauan oleh tim PPKS",
                    'Investigation': "sedang dalam proses investigasi",
                    'In Progress': "sedang dalam proses penanganan",
                    'Pending': "sedang menunggu informasi tambahan",
                    'Resolved': "telah diselesaikan",
                    'Closed': "telah ditutup",
                    'Rejected': "tidak dapat ditindaklanjuti karena kurangnya informasi/bukti"
                }
                
                status_msg = status_info.get(status, f"berstatus {status}")
                
                # Catat akses status dalam log
                cur.execute("""
                    INSERT INTO log_akses_laporan (laporan_id, jenis_akses, detail_akses)
                    VALUES ((SELECT id FROM laporan_kasus WHERE nomor_referensi = %s), %s, %s)
                """, (
                    nomor_referensi, 
                    'view_status', 
                    f"Status laporan dilihat via chatbot"
                ))
                
                dispatcher.utter_message(text=f"Laporan dengan nomor referensi {nomor_referensi} yang dilaporkan pada {tanggal_str} saat ini {status_msg}. Jika Anda memiliki pertanyaan lebih lanjut, silakan hubungi tim PPKS di nomor 081355060444.")
        
        except Exception as e:
            logger.error(f"Error saat memeriksa status laporan: {str(e)}")
            dispatcher.utter_message(text="Mohon maaf, terjadi kendala teknis saat memeriksa status laporan Anda. Silakan coba lagi nanti atau hubungi hotline kami di 081355060444.")
        
        return []